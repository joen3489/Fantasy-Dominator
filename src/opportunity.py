from __future__ import annotations

import re
from typing import Any

import pandas as pd


ELIGIBLE_POSITIONS = {"QB", "RB", "WR", "TE"}
PASS_CATCHERS = {"WR", "TE"}
SOURCE_TRACE = "https://github.com/nflverse/nflverse-data"


def build_opportunity_scores(
    weekly_stats_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    if weekly_stats_df.empty or roster_players_df.empty:
        return _empty_output()

    season_stats = _current_or_latest_reg_season(weekly_stats_df, config.get("current_season"))
    if season_stats.empty:
        return _empty_output()

    scored = score_players_from_weekly(season_stats)
    if scored.empty:
        return _empty_output()
    # nflverse uses GSIS player ids and Sleeper (our rosters) uses its own ids -- they do not
    # overlap, so the whole app joins nflverse <-> roster by normalized player name (see
    # projections.py). Downstream tables all key on the Sleeper player_id, so the output carries
    # the roster's id, not nflverse's.
    scored = scored.sort_values("games_sample", ascending=False).drop_duplicates("normalized_name")

    roster = _prepare_roster(roster_players_df)
    if roster.empty:
        return _empty_output()

    joined = scored.merge(roster, on="normalized_name", how="inner", suffixes=("_stats", "_roster"))
    if joined.empty:
        return _empty_output()

    joined["player_id"] = joined["player_id_roster"]
    joined["player_name"] = joined.apply(
        lambda row: _first_non_empty(row.get("player_name_roster"), row.get("player_name_stats")), axis=1
    )
    joined["position"] = joined.apply(
        lambda row: _first_non_empty(row.get("position_roster"), row.get("position_stats")), axis=1
    )
    joined["source_trace"] = SOURCE_TRACE
    joined["opportunity_evidence"] = joined.apply(_opportunity_evidence, axis=1)

    for column in _score_columns():
        joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(50.0).round(1)
    joined["games_sample"] = pd.to_numeric(joined["games_sample"], errors="coerce").fillna(0).astype(int)

    return (
        joined[_output_columns()]
        .sort_values("opportunity_score", ascending=False)
        .reset_index(drop=True)
    )


def score_players_from_weekly(weekly_scoped_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate + score one already-scoped weekly frame (a single season, or a season truncated
    to weeks<=W for backtesting) into per-nflverse-player opportunity scores, WITHOUT the roster
    join. Shared by the live table builder and the verification backtest so both score identically."""
    if weekly_scoped_df.empty:
        return pd.DataFrame(columns=_scored_columns())
    prepared = _prepare_weekly_stats(weekly_scoped_df)
    prepared = prepared[prepared["position"].isin(ELIGIBLE_POSITIONS)]
    if prepared.empty:
        return pd.DataFrame(columns=_scored_columns())
    player_rows = _aggregate_player_opportunity(prepared)
    if player_rows.empty:
        return pd.DataFrame(columns=_scored_columns())
    scored = _score_player_rows(player_rows)
    scored["normalized_name"] = scored["player_name"].map(_normalize_name)
    scored["opportunity_evidence"] = scored.apply(_opportunity_evidence, axis=1)
    scored["source_trace"] = SOURCE_TRACE
    for column in _score_columns():
        scored[column] = pd.to_numeric(scored[column], errors="coerce").fillna(50.0).round(1)
    return scored


def _scored_columns() -> list[str]:
    return [
        "player_id",
        "player_name",
        "position",
        "normalized_name",
        "games_sample",
        *_score_columns(),
        "opportunity_evidence",
        "source_trace",
    ]


def _current_or_latest_reg_season(frame: pd.DataFrame, current_season: Any) -> pd.DataFrame:
    stats = frame.copy()
    stats["season"] = pd.to_numeric(stats.get("season"), errors="coerce")
    if "season_type" in stats:
        stats = stats[stats["season_type"].fillna("").astype(str) == "REG"]
    if stats.empty:
        return stats

    current = _int(current_season)
    if current:
        current_rows = stats[stats["season"] == current]
        if not current_rows.empty:
            return current_rows.copy()

    latest = stats["season"].dropna().max()
    if pd.isna(latest):
        return pd.DataFrame()
    return stats[stats["season"] == latest].copy()


def _prepare_weekly_stats(frame: pd.DataFrame) -> pd.DataFrame:
    stats = frame.copy()
    stats["player_id"] = stats.get("player_id", "").fillna("").astype(str)
    stats["player_name"] = stats.apply(
        lambda row: _first_non_empty(row.get("player_display_name"), row.get("player_name")), axis=1
    )
    stats["position"] = stats.get("position", "").fillna("").astype(str)
    stats["week"] = pd.to_numeric(stats.get("week"), errors="coerce").fillna(0).astype(int)
    for column in _numeric_input_columns():
        stats[column] = pd.to_numeric(stats.get(column), errors="coerce").fillna(0.0)
    stats["activity"] = (stats["attempts"] > 0) | (stats["carries"] > 0) | (stats["targets"] > 0)
    stats["weekly_proxy"] = stats.apply(_weekly_opportunity_proxy, axis=1)
    return stats


def _aggregate_player_opportunity(stats: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    max_games = int(stats.loc[stats["activity"], ["player_id", "week"]].drop_duplicates().groupby("player_id").size().max() or 0)

    for player_id, group in stats.groupby("player_id", sort=False):
        if not str(player_id):
            continue
        active_weeks = group.loc[group["activity"], "week"].drop_duplicates()
        games = int(active_weeks.shape[0])
        position = _first_non_empty(group["position"].iloc[0])
        attempts = float(group["attempts"].sum())
        carries = float(group["carries"].sum())
        targets = float(group["targets"].sum())
        ppr_points = float(group["fantasy_points_ppr"].sum())
        target_share = _mean(group["target_share"])
        air_yards_share = _mean(group["air_yards_share"])
        wopr = _mean(group["wopr"])
        trend = _role_trend_raw(group)
        usage_cv = _usage_cv(group["weekly_proxy"])
        games_missed_rate = 1.0 - games / max(1, max_games)

        rows.append(
            {
                "player_id": str(player_id),
                "player_name": _first_non_empty(group["player_name"].iloc[0]),
                "position": position,
                "games_sample": games,
                "attempts_pg": _per_game(attempts, games),
                "carries_pg": _per_game(carries, games),
                "targets_pg": _per_game(targets, games),
                "target_share": target_share,
                "air_yards_share": air_yards_share,
                "wopr": wopr,
                "ppr_pg": _per_game(ppr_points, games),
                "role_trend_raw": trend if games >= 2 else pd.NA,
                "usage_cv": usage_cv,
                # nflverse player_stats has TD columns, but this table may not be
                # guaranteed to expose a single TD-points field. Keep this as a small
                # proxy: pass catchers with weaker target share are treated as more
                # TD-dependent; QB/RB get a neutral constant.
                "td_reliance_proxy": 1.0 - target_share if position in PASS_CATCHERS else 0.5,
                "games_missed_rate": max(0.0, min(1.0, games_missed_rate)),
            }
        )

    return pd.DataFrame(rows)


def _score_player_rows(frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    for column in [
        "attempts_pg",
        "carries_pg",
        "targets_pg",
        "target_share",
        "air_yards_share",
        "wopr",
        "ppr_pg",
        "role_trend_raw",
        "usage_cv",
        "td_reliance_proxy",
        "games_missed_rate",
    ]:
        scored[f"{column}_pct"] = _position_percentile(scored, column)

    scored["opportunity_score"] = scored.apply(_opportunity_score, axis=1).round(1)
    scored["production_score"] = (scored["ppr_pg_pct"] * 100).round(1)
    scored["xfp_regression_score"] = (
        50.0 + 50.0 * ((scored["opportunity_score"] / 100.0) - (scored["production_score"] / 100.0))
    ).clip(0.0, 100.0).round(1)
    scored["role_trend_score"] = (scored["role_trend_raw_pct"] * 100).round(1)
    scored.loc[scored["role_trend_raw"].isna(), "role_trend_score"] = 50.0
    scored["fragility_score"] = (
        (
            0.45 * scored["usage_cv_pct"]
            + 0.30 * scored["td_reliance_proxy_pct"]
            + 0.25 * scored["games_missed_rate_pct"]
        )
        * 100
    ).round(1)
    return scored


def _position_percentile(frame: pd.DataFrame, column: str) -> pd.Series:
    result = pd.Series(50.0, index=frame.index, dtype=float)
    for _, index in frame.groupby("position", dropna=False).groups.items():
        values = pd.to_numeric(frame.loc[index, column], errors="coerce")
        if len(values) <= 1 or values.notna().sum() == 0:
            result.loc[index] = 0.5
        else:
            result.loc[index] = values.rank(pct=True, method="average")
    return result.fillna(0.5)


def _opportunity_score(row: pd.Series) -> float:
    position = str(row.get("position", ""))
    if position == "QB":
        score = 0.6 * _num(row.get("attempts_pg_pct")) + 0.4 * _num(row.get("carries_pg_pct"))
    elif position == "RB":
        score = (
            0.5 * _num(row.get("targets_pg_pct"))
            + 0.3 * _num(row.get("carries_pg_pct"))
            + 0.2 * _num(row.get("target_share_pct"))
        )
    else:
        score = (
            0.5 * _num(row.get("target_share_pct"))
            + 0.2 * _num(row.get("targets_pg_pct"))
            + 0.2 * _num(row.get("air_yards_share_pct"))
            + 0.1 * _num(row.get("wopr_pct"))
        )
    return max(0.0, min(100.0, score * 100.0))


def _weekly_opportunity_proxy(row: pd.Series) -> float:
    position = str(row.get("position", ""))
    if position in PASS_CATCHERS:
        target_share = _num(row.get("target_share"))
        return target_share if target_share else _num(row.get("targets"))
    if position == "RB":
        return _num(row.get("carries")) + _num(row.get("targets"))
    if position == "QB":
        return _num(row.get("attempts")) + _num(row.get("carries"))
    return 0.0


def _role_trend_raw(group: pd.DataFrame) -> float:
    weekly = group.sort_values("week")["weekly_proxy"]
    if weekly.shape[0] < 2:
        return 0.0
    recent = float(weekly.tail(3).mean())
    baseline = float(weekly.mean())
    return recent - baseline


def _usage_cv(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if numeric.shape[0] < 2:
        return 0.0
    mean = float(numeric.mean())
    if mean <= 0:
        return 0.0
    return float(numeric.std() / mean)


def _opportunity_evidence(row: pd.Series) -> str:
    position = str(row.get("position", ""))
    parts: list[str] = []
    if position == "QB":
        parts.extend([f"attempts_pg={_num(row.get('attempts_pg')):.1f}", f"carries_pg={_num(row.get('carries_pg')):.1f}"])
    elif position == "RB":
        parts.extend(
            [
                f"targets_pg={_num(row.get('targets_pg')):.1f}",
                f"carries_pg={_num(row.get('carries_pg')):.1f}",
                f"target_share={_num(row.get('target_share')):.2f}",
            ]
        )
    else:
        parts.extend(
            [
                f"target_share={_num(row.get('target_share')):.2f}",
                f"air_yards_share={_num(row.get('air_yards_share')):.2f}",
                f"targets_pg={_num(row.get('targets_pg')):.1f}",
                f"wopr={_num(row.get('wopr')):.2f}",
            ]
        )
    parts.append(f"ppr_pg={_num(row.get('ppr_pg')):.1f}")
    return "; ".join(parts)


def _prepare_roster(frame: pd.DataFrame) -> pd.DataFrame:
    roster = frame.copy()
    if "player_id" not in roster:
        return pd.DataFrame()
    roster["player_id"] = roster["player_id"].fillna("").astype(str)
    roster["player_name"] = roster.get("player_name", "").fillna("").astype(str)
    roster["position"] = roster.get("position", "").fillna("").astype(str)
    roster["roster_id"] = pd.to_numeric(roster.get("roster_id"), errors="coerce").fillna(0).astype(int)
    roster["team_name"] = roster.get("team_name", "").fillna("").astype(str)
    roster["normalized_name"] = roster["player_name"].map(_normalize_name)
    roster = roster[roster["normalized_name"] != ""].drop_duplicates("normalized_name")
    return roster[["player_id", "player_name", "position", "roster_id", "team_name", "normalized_name"]]


def _normalize_name(value: Any) -> str:
    # Matches src/projections.py::_normalize_name -- the shared nflverse <-> roster join key.
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _mean(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() == 0:
        return 0.0
    return float(numeric.mean())


def _per_game(total: float, games: int) -> float:
    return float(total) / max(1, games)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value not in ("", None) and not pd.isna(value):
            return str(value)
    return ""


def _num(value: Any) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        if value in ("", None) or pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _numeric_input_columns() -> list[str]:
    return [
        "attempts",
        "carries",
        "targets",
        "receptions",
        "target_share",
        "air_yards_share",
        "wopr",
        "fantasy_points",
        "fantasy_points_ppr",
    ]


def _score_columns() -> list[str]:
    return [
        "opportunity_score",
        "production_score",
        "xfp_regression_score",
        "role_trend_score",
        "fragility_score",
    ]


def _output_columns() -> list[str]:
    return [
        "player_id",
        "player_name",
        "position",
        "roster_id",
        "team_name",
        "games_sample",
        "opportunity_score",
        "production_score",
        "xfp_regression_score",
        "role_trend_score",
        "fragility_score",
        "opportunity_evidence",
        "source_trace",
    ]


def _empty_output() -> pd.DataFrame:
    return pd.DataFrame([], columns=_output_columns())
