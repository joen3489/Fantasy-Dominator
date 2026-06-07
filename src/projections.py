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
) -> dict[str, pd.DataFrame]:
    season = str(config.get("current_season", ""))
    scoring = _scoring_settings(leagues_df)
    source_path = RAW_EXTERNAL_DIR / "nflverse" / season / "player_stats.csv"
    raw_stats = _load_raw_stats(source_path)
    current_roster_players = _current_season_roster(roster_players_df, season)

    season_rows = _build_season_projection_rows(season, raw_stats, current_roster_players, scoring)
    season_df = pd.DataFrame(season_rows, columns=_season_columns())
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


def _build_season_projection_rows(
    season: str,
    raw_stats: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    scoring: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if roster_players_df.empty:
        return rows

    stats = _prepared_stats(raw_stats, season)
    stat_groups = {name: group for name, group in stats.groupby("normalized_name")} if not stats.empty else {}

    for _, player in roster_players_df.fillna("").iterrows():
        player_name = str(player.get("player_name", ""))
        position = str(player.get("position", ""))
        nfl_team = str(player.get("nfl_team", ""))
        player_stats = stat_groups.get(_normalize_name(player_name), pd.DataFrame())
        if not player_stats.empty and nfl_team:
            team_rows = player_stats[player_stats.get("team", "") == nfl_team]
            if not team_rows.empty:
                player_stats = team_rows

        projection = _project_player(player_stats, scoring, position)
        rows.append(
            {
                "season": season,
                "player_id": str(player.get("player_id", "")),
                "player_name": player_name,
                "position": position,
                "team": nfl_team,
                "roster_id": player.get("roster_id", ""),
                "team_name": player.get("team_name", ""),
                **projection,
            }
        )
    return rows


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
