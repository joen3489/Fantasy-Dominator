"""Deterministic opponent context derived from preserved nflverse usage.

This is deliberately a small, inspectable matchup model.  It does not claim to
be a full defensive projection: it measures how many PPR points each NFL team
has allowed to each fantasy position per game in the available historical
player-stat data, then expresses that result relative to the position average.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


MATCHUP_COLUMNS = [
    "team",
    "position",
    "games_sample",
    "fantasy_points_allowed_per_game",
    "league_position_average",
    "matchup_factor",
    "confidence",
    "validation_seasons",
    "validation_games",
    "validation_mae",
    "validation_baseline_mae",
    "validation_mae_delta",
    "validation_direction_accuracy",
    "validation_status",
    "source_trace",
]
SOURCE_TRACE = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
POSITIONS = {"QB", "RB", "WR", "TE"}


def build_team_defense_factors(
    usage_df: pd.DataFrame | None,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Build position-specific opponent factors from historical game totals.

    ``usage_df`` is the normalized nflverse player usage table.  A missing or
    incomplete table returns an empty, typed result; callers must then keep the
    schedule context visible without pretending a matchup adjustment exists.
    """

    config = config or {}
    if usage_df is None or usage_df.empty:
        return pd.DataFrame(columns=MATCHUP_COLUMNS)
    required = {"season", "game_id", "opponent_team", "position", "fantasy_points_ppr"}
    if not required.issubset(usage_df.columns):
        return pd.DataFrame(columns=MATCHUP_COLUMNS)

    frame = usage_df.copy().fillna("")
    frame["season_num"] = pd.to_numeric(frame["season"], errors="coerce")
    current_season = _as_int(config.get("current_season"))
    if current_season is not None:
        frame = frame[frame["season_num"] < current_season]
    frame["position"] = frame["position"].astype(str).str.upper()
    frame["opponent_team"] = frame["opponent_team"].astype(str).str.upper().str.strip()
    frame["game_id"] = frame["game_id"].astype(str).str.strip()
    frame["fantasy_points_ppr"] = pd.to_numeric(frame["fantasy_points_ppr"], errors="coerce").fillna(0.0)
    frame = frame[
        frame["position"].isin(POSITIONS)
        & frame["opponent_team"].ne("")
        & frame["game_id"].ne("")
        & frame["season_num"].notna()
    ]
    if frame.empty:
        return pd.DataFrame(columns=MATCHUP_COLUMNS)

    # Sum the offense faced by each defense once per game and position before
    # averaging.  This prevents a team with more fantasy-player rows from being
    # mistaken for a larger number of games.
    game_points = (
        frame.groupby(["season_num", "game_id", "opponent_team", "position"], dropna=False)["fantasy_points_ppr"]
        .sum()
        .reset_index(name="game_points_allowed")
    )
    league_average = game_points.groupby("position")["game_points_allowed"].mean().to_dict()
    team_summary = (
        game_points.groupby(["opponent_team", "position"], dropna=False)
        .agg(
            games_sample=("game_id", "nunique"),
            fantasy_points_allowed_per_game=("game_points_allowed", "mean"),
        )
        .reset_index()
    )
    calibration = _calibrate_factors(game_points, config)

    rows: list[dict[str, Any]] = []
    for _, row in team_summary.iterrows():
        position = str(row["position"])
        average = float(league_average.get(position) or 0.0)
        allowed = float(row["fantasy_points_allowed_per_game"] or 0.0)
        sample = int(row["games_sample"] or 0)
        factor = round(min(1.25, max(0.75, allowed / average)) if average > 0 else 1.0, 4)
        validation = calibration.get((str(row["opponent_team"]), position), {})
        rows.append(
            {
                "team": str(row["opponent_team"]),
                "position": position,
                "games_sample": sample,
                "fantasy_points_allowed_per_game": round(allowed, 2),
                "league_position_average": round(average, 2),
                "matchup_factor": factor,
                "confidence": "high" if sample >= 12 else "medium" if sample >= 6 else "low",
                "validation_seasons": validation.get("validation_seasons", ""),
                "validation_games": validation.get("validation_games", ""),
                "validation_mae": validation.get("validation_mae", ""),
                "validation_baseline_mae": validation.get("validation_baseline_mae", ""),
                "validation_mae_delta": validation.get("validation_mae_delta", ""),
                "validation_direction_accuracy": validation.get("validation_direction_accuracy", ""),
                "validation_status": validation.get("validation_status", "insufficient_sample"),
                "source_trace": SOURCE_TRACE,
            }
        )
    return pd.DataFrame(rows, columns=MATCHUP_COLUMNS)


def _calibrate_factors(
    game_points: pd.DataFrame,
    config: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Evaluate factors on later seasons than the evidence used to build them.

    This is intentionally a bounded receipt, not a model-selection claim.  A
    factor is compared with the position average on held-out seasons so the
    reader can tell whether the historical adjustment added signal in this
    bundle.  Same-season evaluation is avoided to prevent leakage.
    """

    if game_points.empty or not {"season_num", "game_id", "opponent_team", "position", "game_points_allowed"}.issubset(game_points.columns):
        return {}
    seasons = sorted({int(value) for value in game_points["season_num"].dropna().tolist()})
    try:
        requested = max(1, int(float(config.get("matchup_validation_seasons", 3))))
    except (TypeError, ValueError):
        requested = 3
    target_seasons = seasons[-requested:]
    observations: list[pd.DataFrame] = []
    for target in target_seasons:
        train = game_points[game_points["season_num"] < target]
        target_games = game_points[game_points["season_num"] == target]
        if train.empty or target_games.empty:
            continue
        position_average = train.groupby("position")["game_points_allowed"].mean().to_dict()
        team_position = (
            train.groupby(["opponent_team", "position"], dropna=False)["game_points_allowed"]
            .mean()
            .reset_index(name="allowed")
        )
        team_position["league_average"] = team_position["position"].map(position_average)
        team_position["factor"] = (
            team_position["allowed"] / team_position["league_average"].replace(0, pd.NA)
        ).fillna(1.0).clip(lower=0.75, upper=1.25)
        expected = target_games.merge(
            team_position[["opponent_team", "position", "league_average", "factor"]],
            on=["opponent_team", "position"],
            how="inner",
        )
        if expected.empty:
            continue
        expected["factor_expected"] = expected["league_average"] * expected["factor"]
        expected["baseline_error"] = (expected["game_points_allowed"] - expected["league_average"]).abs()
        expected["factor_error"] = (expected["game_points_allowed"] - expected["factor_expected"]).abs()
        expected["direction_correct"] = (
            (expected["game_points_allowed"] >= expected["league_average"])
            == (expected["factor_expected"] >= expected["league_average"])
        )
        observations.append(expected)
    if not observations:
        return {}

    evaluated = pd.concat(observations, ignore_index=True)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for (team, position), group in evaluated.groupby(["opponent_team", "position"], dropna=False):
        games = int(len(group))
        mae = float(group["factor_error"].mean())
        baseline_mae = float(group["baseline_error"].mean())
        delta = baseline_mae - mae
        direction = float(group["direction_correct"].mean())
        status = (
            "validated_improvement" if games >= 12 and delta > 0.01
            else "validated_no_improvement" if games >= 12
            else "limited_sample" if games >= 6
            else "insufficient_sample"
        )
        rows[(str(team), str(position))] = {
            "validation_seasons": ",".join(str(value) for value in sorted({int(v) for v in group["season_num"].tolist()})),
            "validation_games": games,
            "validation_mae": round(mae, 2),
            "validation_baseline_mae": round(baseline_mae, 2),
            "validation_mae_delta": round(delta, 2),
            "validation_direction_accuracy": round(direction, 4),
            "validation_status": status,
        }
    return rows


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
