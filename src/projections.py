from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import RAW_EXTERNAL_DIR


NFLVERSE_PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"


def build_projection_tables(
    config: dict[str, Any],
    leagues_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    fantasy_nerds_projection_source_df: pd.DataFrame | None = None,
    projection_accuracy_df: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    season = str(config.get("current_season", ""))
    scoring = _scoring_settings(leagues_df)
    source_path = RAW_EXTERNAL_DIR / "nflverse" / season / "player_stats.csv"
    raw_stats = _load_raw_stats(source_path)
    current_roster_players = _current_season_roster(roster_players_df, season)
    fantasy_nerds_df = fantasy_nerds_projection_source_df if fantasy_nerds_projection_source_df is not None else pd.DataFrame()
    accuracy_df = projection_accuracy_df if projection_accuracy_df is not None else pd.DataFrame()

    component_rows = _build_projection_source_rows(season, raw_stats, current_roster_players, scoring, fantasy_nerds_df)
    source_df = pd.DataFrame(component_rows, columns=_projection_source_component_columns())
    season_df = _build_projection_consensus(source_df, accuracy_df)
    weekly_df = _build_weekly_projection_rows(season_df)
    freshness = pd.DataFrame(
        [
            {
                "source": "nflverse",
                "dataset": "player_stats_projection_input",
                "status": "cached" if source_path.exists() else "unavailable",
                "source_url": NFLVERSE_PLAYER_STATS_URL,
                "cache_path": str(source_path.as_posix()),
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "row_count": len(raw_stats),
            }
        ],
        columns=_freshness_columns(),
    )
    return {
        "player_projection_season": season_df,
        "player_projection_weekly": weekly_df,
        "projection_source_freshness": freshness,
        "projection_source_components": source_df,
    }


def calculate_fantasy_points(stats: dict[str, Any], scoring: dict[str, float], position: str = "") -> float:
    receptions = _num(stats.get("projected_receptions", stats.get("receptions")))
    points = 0.0
    points += _num(stats.get("projected_passing_yards", stats.get("passing_yards"))) * _score(scoring, "pass_yd", 0.04)
    points += _num(stats.get("projected_passing_tds", stats.get("passing_tds"))) * _score(scoring, "pass_td", 4.0)
    points += _num(stats.get("projected_interceptions", stats.get("interceptions"))) * _score(scoring, "pass_int", -1.0)
    points += _num(stats.get("projected_rushing_yards", stats.get("rushing_yards"))) * _score(scoring, "rush_yd", 0.1)
    points += _num(stats.get("projected_rushing_tds", stats.get("rushing_tds"))) * _score(scoring, "rush_td", 6.0)
    points += receptions * _score(scoring, "rec", 0.5)
    if position == "TE":
        points += receptions * _score(scoring, "bonus_rec_te", 0.0)
    points += _num(stats.get("projected_receiving_yards", stats.get("receiving_yards"))) * _score(scoring, "rec_yd", 0.1)
    points += _num(stats.get("projected_receiving_tds", stats.get("receiving_tds"))) * _score(scoring, "rec_td", 6.0)
    return round(points, 2)


def _build_projection_source_rows(
    season: str,
    raw_stats: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    scoring: dict[str, float],
    fantasy_nerds_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """One row per (player, source) -- the pre-blend component detail that feeds
    _build_projection_consensus(). nflverse is always attempted (falls back to an
    empty projection via _project_player when unmatched, exactly as before);
    Fantasy Nerds is added as a second component only when a name match exists."""
    rows: list[dict[str, Any]] = []
    if roster_players_df.empty:
        return rows

    stats = _prepared_stats(raw_stats, season)
    stat_groups = {name: group for name, group in stats.groupby("normalized_name")} if not stats.empty else {}
    fn_groups: dict[str, pd.DataFrame] = {}
    if not fantasy_nerds_df.empty and "normalized_name" in fantasy_nerds_df.columns:
        fn_groups = {name: group for name, group in fantasy_nerds_df.groupby("normalized_name")}
    now = datetime.now(timezone.utc).isoformat()

    for _, player in roster_players_df.fillna("").iterrows():
        player_name = str(player.get("player_name", ""))
        position = str(player.get("position", ""))
        nfl_team = str(player.get("nfl_team", ""))
        normalized = _normalize_name(player_name)
        identity = {
            "season": season,
            "player_id": str(player.get("player_id", "")),
            "player_name": player_name,
            "position": position,
            "team": nfl_team,
            "roster_id": player.get("roster_id", ""),
            "team_name": player.get("team_name", ""),
        }

        player_stats = stat_groups.get(normalized, pd.DataFrame())
        if not player_stats.empty and nfl_team:
            team_rows = player_stats[player_stats.get("team", "") == nfl_team]
            if not team_rows.empty:
                player_stats = team_rows

        nflverse_projection = _project_player(player_stats, scoring, position)
        rows.append(
            {
                **identity,
                "source": "nflverse_history",
                "projected_fantasy_points": nflverse_projection["projected_fantasy_points"],
                "projected_ppg": nflverse_projection["projected_ppg"],
                "projected_games": nflverse_projection["projected_games"],
                "source_confidence": nflverse_projection["projection_confidence"],
                "source_trace": nflverse_projection["source_trace"],
                "projection_method": nflverse_projection["projection_method"],
                "detail_stats_json": json.dumps(
                    {
                        "projected_passing_yards": nflverse_projection["projected_passing_yards"],
                        "projected_passing_tds": nflverse_projection["projected_passing_tds"],
                        "projected_interceptions": nflverse_projection["projected_interceptions"],
                        "projected_rushing_yards": nflverse_projection["projected_rushing_yards"],
                        "projected_rushing_tds": nflverse_projection["projected_rushing_tds"],
                        "projected_receptions": nflverse_projection["projected_receptions"],
                        "projected_receiving_yards": nflverse_projection["projected_receiving_yards"],
                        "projected_receiving_tds": nflverse_projection["projected_receiving_tds"],
                        "projection_note": nflverse_projection["projection_note"],
                    }
                ),
                "checked_at": now,
            }
        )

        fn_group = fn_groups.get(normalized)
        if fn_group is not None and not fn_group.empty:
            fn_row = fn_group.iloc[0]
            fn_points = _num(fn_row.get("projected_fantasy_points"))
            rows.append(
                {
                    **identity,
                    "source": "fantasy_nerds",
                    "projected_fantasy_points": fn_points,
                    "projected_ppg": round(fn_points / 17, 2) if fn_points else 0.0,
                    "projected_games": 17,
                    "source_confidence": str(fn_row.get("source_confidence", "high")),
                    "source_trace": str(fn_row.get("source_trace", "")),
                    "projection_method": "fantasy_nerds_weekly_projection",
                    "detail_stats_json": "",
                    "checked_at": now,
                }
            )
    return rows


def _build_projection_consensus(source_df: pd.DataFrame, accuracy_df: pd.DataFrame) -> pd.DataFrame:
    """Mirrors external_sources.build_market_consensus_values(): group per-source
    component rows by player, blend into one row. With exactly one component this
    degrades to returning that component's values verbatim -- byte-identical to the
    pre-multi-source behavior when Fantasy Nerds is absent."""
    rows: list[dict[str, Any]] = []
    if source_df.empty:
        return pd.DataFrame(rows, columns=_season_columns())

    for (player_id, player_name, position), group in source_df.fillna("").groupby(
        ["player_id", "player_name", "position"], dropna=False, sort=False
    ):
        first = group.iloc[0]
        components = group.to_dict("records")
        weights_by_source = _accuracy_weights_by_source(accuracy_df, str(position))
        blended = _blend_projection_components(components, weights_by_source)

        detail: dict[str, Any] = {}
        nflverse_rows = group[group["source"] == "nflverse_history"]
        if not nflverse_rows.empty:
            raw_detail = nflverse_rows.iloc[0].get("detail_stats_json", "")
            if raw_detail:
                try:
                    detail = json.loads(raw_detail)
                except (TypeError, ValueError, json.JSONDecodeError):
                    detail = {}

        rows.append(
            {
                "season": first.get("season", ""),
                "player_id": player_id,
                "player_name": player_name,
                "position": position,
                "team": first.get("team", ""),
                "roster_id": first.get("roster_id", ""),
                "team_name": first.get("team_name", ""),
                "projected_games": blended["projected_games"],
                "projected_passing_yards": detail.get("projected_passing_yards", 0.0),
                "projected_passing_tds": detail.get("projected_passing_tds", 0.0),
                "projected_interceptions": detail.get("projected_interceptions", 0.0),
                "projected_rushing_yards": detail.get("projected_rushing_yards", 0.0),
                "projected_rushing_tds": detail.get("projected_rushing_tds", 0.0),
                "projected_receptions": detail.get("projected_receptions", 0.0),
                "projected_receiving_yards": detail.get("projected_receiving_yards", 0.0),
                "projected_receiving_tds": detail.get("projected_receiving_tds", 0.0),
                "projected_fantasy_points": blended["projected_fantasy_points"],
                "projected_ppg": blended["projected_ppg"],
                "projection_method": blended["projection_method"],
                "projection_confidence": blended["projection_confidence"],
                "source_trace": blended["source_trace"],
                "projection_note": detail.get("projection_note", ""),
            }
        )
    return pd.DataFrame(rows, columns=_season_columns())


def _blend_projection_components(components: list[dict[str, Any]], weights_by_source: dict[str, float]) -> dict[str, Any]:
    source_count = len(components)
    if source_count == 1:
        only = components[0]
        return {
            "projected_fantasy_points": _num(only.get("projected_fantasy_points")),
            "projected_ppg": _num(only.get("projected_ppg")),
            "projected_games": int(only.get("projected_games") or 0),
            "projection_method": only.get("projection_method", ""),
            "projection_confidence": only.get("source_confidence", "low"),
            "source_trace": only.get("source_trace", ""),
            "source_count": 1,
            "disagreement_score": 0.0,
        }

    points_values = [_num(component.get("projected_fantasy_points")) for component in components]
    known_weights = [weights_by_source[c["source"]] for c in components if c.get("source") in weights_by_source]
    fallback_weight = (sum(known_weights) / len(known_weights)) if known_weights else (1.0 / source_count)
    weights = [weights_by_source.get(component.get("source"), fallback_weight) for component in components]
    total_weight = sum(weights) or float(source_count)
    consensus_points = round(sum(points * weight for points, weight in zip(points_values, weights)) / total_weight, 2)
    projected_games = max(int(component.get("projected_games") or 0) for component in components)
    consensus_ppg = round(consensus_points / projected_games, 2) if projected_games else 0.0
    disagreement = round(max(points_values) - min(points_values), 2)
    confidences = {str(component.get("source_confidence", "")) for component in components}
    confidence = _projection_consensus_confidence(source_count, disagreement, confidences)
    sources = sorted({str(component.get("source", "")) for component in components})
    traces = sorted({str(component.get("source_trace", "")) for component in components if component.get("source_trace")})
    return {
        "projected_fantasy_points": consensus_points,
        "projected_ppg": consensus_ppg,
        "projected_games": projected_games,
        "projection_method": f"consensus_{source_count}src_" + "_".join(sources),
        "projection_confidence": confidence,
        "source_trace": "; ".join(traces),
        # Diagnostic-only fields (not part of the player_projection_season contract --
        # _build_projection_consensus only reads the keys above when assembling season
        # rows). Exposed here so tests can assert blending behavior directly, mirroring
        # build_market_consensus_values' disagreement_score/source_count precedent.
        "source_count": source_count,
        "disagreement_score": disagreement,
    }


def _projection_consensus_confidence(source_count: int, disagreement: float, confidences: set[str]) -> str:
    if source_count <= 0:
        return "low"
    if "low" in confidences:
        return "low"
    if disagreement >= 6.0:
        return "medium"
    if source_count >= 2:
        return "high"
    return "medium"


def _accuracy_weights_by_source(accuracy_df: pd.DataFrame, position: str = "") -> dict[str, float]:
    if accuracy_df is None or accuracy_df.empty or "source" not in accuracy_df.columns:
        return {}
    frame = accuracy_df
    if position and "position" in frame.columns:
        position_rows = frame[frame["position"] == position]
        if not position_rows.empty:
            frame = position_rows
    weights: dict[str, float] = {}
    for _, row in frame.iterrows():
        mae = _num(row.get("mean_absolute_error"))
        weight = 1.0 / (1.0 + mae)
        weights[str(row.get("source", ""))] = round(min(1.0, max(0.1, weight)), 4)
    return weights


def _project_player(player_stats: pd.DataFrame, scoring: dict[str, float], position: str) -> dict[str, Any]:
    if player_stats.empty:
        return _empty_projection("missing_nflverse_history", "low", "No nflverse history matched for Sleeper player.")

    seasons = sorted(player_stats["season"].dropna().astype(int).unique())[-2:]
    recent = player_stats[player_stats["season"].astype(int).isin(seasons)].copy()
    games = int(recent[["season", "week"]].drop_duplicates().shape[0])
    if games <= 0:
        return _empty_projection("missing_nflverse_history", "low", "No weekly games available after matching.")

    projected_games = 17 if games >= 8 else 14 if games >= 4 else 10
    confidence = "high" if games >= 12 else "medium" if games >= 5 else "low"
    method = f"recent_nflverse_per_game_{len(seasons)}yr"
    components = {
        "projected_passing_yards": _per_game_project(recent, "passing_yards", projected_games),
        "projected_passing_tds": _per_game_project(recent, "passing_tds", projected_games),
        "projected_interceptions": _per_game_project(recent, "interceptions", projected_games),
        "projected_rushing_yards": _per_game_project(recent, "rushing_yards", projected_games),
        "projected_rushing_tds": _per_game_project(recent, "rushing_tds", projected_games),
        "projected_receptions": _per_game_project(recent, "receptions", projected_games),
        "projected_receiving_yards": _per_game_project(recent, "receiving_yards", projected_games),
        "projected_receiving_tds": _per_game_project(recent, "receiving_tds", projected_games),
    }
    points = calculate_fantasy_points(components, scoring, position)
    return {
        "projected_games": projected_games,
        **components,
        "projected_fantasy_points": points,
        "projected_ppg": round(points / projected_games, 2) if projected_games else 0.0,
        "projection_method": method,
        "projection_confidence": confidence,
        "source_trace": NFLVERSE_PLAYER_STATS_URL,
        "projection_note": f"Matched {games} recent regular-season games from nflverse.",
    }


def _empty_projection(method: str, confidence: str, note: str) -> dict[str, Any]:
    return {
        "projected_games": 0,
        "projected_passing_yards": 0.0,
        "projected_passing_tds": 0.0,
        "projected_interceptions": 0.0,
        "projected_rushing_yards": 0.0,
        "projected_rushing_tds": 0.0,
        "projected_receptions": 0.0,
        "projected_receiving_yards": 0.0,
        "projected_receiving_tds": 0.0,
        "projected_fantasy_points": 0.0,
        "projected_ppg": 0.0,
        "projection_method": method,
        "projection_confidence": confidence,
        "source_trace": "missing_projection_input",
        "projection_note": note,
    }


def _build_weekly_projection_rows(season_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if season_df.empty:
        return pd.DataFrame(rows, columns=_weekly_columns())
    for _, player in season_df.iterrows():
        weekly_points = _num(player.get("projected_fantasy_points")) / 17 if _num(player.get("projected_fantasy_points")) else 0.0
        for week in range(1, 18):
            rows.append(
                {
                    "season": player.get("season", ""),
                    "week": week,
                    "player_id": player.get("player_id", ""),
                    "player_name": player.get("player_name", ""),
                    "position": player.get("position", ""),
                    "team": player.get("team", ""),
                    "roster_id": player.get("roster_id", ""),
                    "team_name": player.get("team_name", ""),
                    "projected_fantasy_points": round(weekly_points, 2),
                    "projected_snap_or_usage_note": "weekly allocation from season projection",
                    "projection_method": player.get("projection_method", ""),
                    "projection_confidence": player.get("projection_confidence", ""),
                    "source_trace": player.get("source_trace", ""),
                }
            )
    return pd.DataFrame(rows, columns=_weekly_columns())


def _prepared_stats(raw_stats: pd.DataFrame, current_season: str) -> pd.DataFrame:
    if raw_stats.empty:
        return pd.DataFrame()
    frame = raw_stats.copy()
    frame["season"] = pd.to_numeric(frame.get("season"), errors="coerce")
    current = int(current_season) if str(current_season).isdigit() else int(frame["season"].max())
    frame = frame[frame["season"] < current]
    if "season_type" in frame:
        frame = frame[frame["season_type"] == "REG"]
    if frame.empty:
        return frame
    recent_cutoff = int(frame["season"].max()) - 1
    frame = frame[frame["season"] >= recent_cutoff]
    frame["normalized_name"] = frame.apply(
        lambda row: _normalize_name(row.get("player_display_name") or row.get("player_name")),
        axis=1,
    )
    frame["team"] = frame.get("recent_team", "")
    return frame


def _load_raw_stats(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _current_season_roster(roster_players_df: pd.DataFrame, season: str) -> pd.DataFrame:
    if roster_players_df.empty or "season" not in roster_players_df.columns:
        return roster_players_df
    current = roster_players_df[roster_players_df.get("season").astype(str) == str(season)]
    return current if not current.empty else roster_players_df


def _scoring_settings(leagues_df: pd.DataFrame) -> dict[str, float]:
    if leagues_df.empty or "scoring_settings" not in leagues_df:
        return {}
    raw = leagues_df.iloc[0].get("scoring_settings", "")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw else {}
        return {str(key): _num(value) for key, value in parsed.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _per_game_project(frame: pd.DataFrame, column: str, projected_games: int) -> float:
    if column not in frame:
        return 0.0
    return round(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum() / max(1, len(frame)) * projected_games, 2)


def _score(scoring: dict[str, float], key: str, default: float) -> float:
    return _num(scoring.get(key, default))


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _num(value: Any) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _season_columns() -> list[str]:
    return [
        "season",
        "player_id",
        "player_name",
        "position",
        "team",
        "roster_id",
        "team_name",
        "projected_games",
        "projected_passing_yards",
        "projected_passing_tds",
        "projected_interceptions",
        "projected_rushing_yards",
        "projected_rushing_tds",
        "projected_receptions",
        "projected_receiving_yards",
        "projected_receiving_tds",
        "projected_fantasy_points",
        "projected_ppg",
        "projection_method",
        "projection_confidence",
        "source_trace",
        "projection_note",
    ]


def _weekly_columns() -> list[str]:
    return [
        "season",
        "week",
        "player_id",
        "player_name",
        "position",
        "team",
        "roster_id",
        "team_name",
        "projected_fantasy_points",
        "projected_snap_or_usage_note",
        "projection_method",
        "projection_confidence",
        "source_trace",
    ]


def _freshness_columns() -> list[str]:
    return ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"]


def _projection_source_component_columns() -> list[str]:
    return [
        "season",
        "player_id",
        "player_name",
        "position",
        "team",
        "roster_id",
        "team_name",
        "source",
        "projected_fantasy_points",
        "projected_ppg",
        "projected_games",
        "source_confidence",
        "source_trace",
        "projection_method",
        "detail_stats_json",
        "checked_at",
    ]
