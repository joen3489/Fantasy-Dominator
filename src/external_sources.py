from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .utils import RAW_EXTERNAL_DIR


DYNASTYPROCESS_VALUES_URL = "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values.csv"
DYNASTYPROCESS_PICKS_URL = "https://raw.githubusercontent.com/DynastyProcess/data/master/files/picks.csv"
NFLVERSE_USAGE_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"


def refresh_external_sources(config: dict[str, Any], force: bool = False) -> dict[str, pd.DataFrame]:
    sources = ((config.get("external_sources") or {}).get("enabled") or [])
    source_policy = config.get("source_policy", "open_legal_only")
    season = str(config.get("current_season", "global") or "global")
    frames = {
        "player_market_values": pd.DataFrame(columns=_player_market_columns()),
        "pick_market_values": pd.DataFrame(columns=_pick_market_columns()),
        "player_usage_weekly": pd.DataFrame(columns=_usage_columns()),
        "source_freshness": pd.DataFrame(columns=_freshness_columns()),
    }
    freshness_rows: list[dict[str, Any]] = []

    if source_policy != "open_legal_only":
        freshness_rows.append(_freshness("external_sources", "disabled", "source_policy_not_open_legal_only", ""))
        frames["source_freshness"] = pd.DataFrame(freshness_rows, columns=_freshness_columns())
        return frames

    if "dynastyprocess" in sources:
        values, row = _load_csv_source(
            "dynastyprocess",
            "player_values",
            DYNASTYPROCESS_VALUES_URL,
            RAW_EXTERNAL_DIR / "dynastyprocess" / season / "values.csv",
            force,
        )
        frames["player_market_values"] = _normalize_dynastyprocess_values(values)
        freshness_rows.append(row | {"row_count": len(frames["player_market_values"])})

        picks, row = _load_csv_source(
            "dynastyprocess",
            "pick_values",
            DYNASTYPROCESS_PICKS_URL,
            RAW_EXTERNAL_DIR / "dynastyprocess" / season / "picks.csv",
            force,
        )
        frames["pick_market_values"] = _normalize_pick_values(picks)
        freshness_rows.append(row | {"row_count": len(frames["pick_market_values"])})

    if "nflverse" in sources:
        usage, row = _load_csv_source(
            "nflverse",
            "player_usage_weekly",
            NFLVERSE_USAGE_URL,
            RAW_EXTERNAL_DIR / "nflverse" / season / "player_stats.csv",
            force,
        )
        frames["player_usage_weekly"] = _normalize_nflverse_usage(usage)
        freshness_rows.append(row | {"row_count": len(frames["player_usage_weekly"])})

    if not freshness_rows:
        freshness_rows.append(_freshness("external_sources", "disabled", "no_external_sources_enabled", ""))

    frames["source_freshness"] = pd.DataFrame(freshness_rows, columns=_freshness_columns())
    return frames


def _load_csv_source(source: str, dataset: str, url: str, cache_path: Path, force: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        try:
            return pd.read_csv(cache_path), _freshness(source, dataset, "cached", url, cache_path)
        except Exception as exc:
            return pd.DataFrame(), _freshness(source, dataset, f"cache_error:{type(exc).__name__}", url, cache_path)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        cache_path.write_bytes(response.content)
        return pd.read_csv(cache_path), _freshness(source, dataset, "refreshed", url, cache_path)
    except Exception as exc:
        if cache_path.exists():
            try:
                return pd.read_csv(cache_path), _freshness(source, dataset, f"cached_after_refresh_error:{type(exc).__name__}", url, cache_path)
            except Exception:
                pass
        return pd.DataFrame(), _freshness(source, dataset, f"unavailable:{type(exc).__name__}", url, cache_path)


def _normalize_dynastyprocess_values(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=_player_market_columns())

    for _, row in frame.iterrows():
        player_id = _first(row, ["sleeper_id", "player_id", "fantasypros_id", "gsis_id"])
        player_name = _first(row, ["player", "player_name", "name"])
        value = _first(row, ["value_2qb", "sf_value", "value", "ecr_2qb"])
        rows.append(
            {
                "source": "dynastyprocess",
                "source_player_id": player_id,
                "player_id": str(player_id) if player_id not in ("", None) else "",
                "player_name": player_name,
                "position": _first(row, ["pos", "position"]),
                "market_value": _number(value),
                "market_rank": _number(_first(row, ["overall_rank", "rank", "ecr_2qb"])),
                "value_format": "superflex_preferred",
                "source_trace": DYNASTYPROCESS_VALUES_URL,
            }
        )
    return pd.DataFrame(rows, columns=_player_market_columns())


def _normalize_pick_values(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=_pick_market_columns())

    for _, row in frame.iterrows():
        pick = str(_first(row, ["pick", "selection", "label", "name"]))
        rows.append(
            {
                "source": "dynastyprocess",
                "pick_label": pick,
                "pick_season": _first(row, ["season", "year"]),
                "round": _round_from_pick(pick, _first(row, ["round"])),
                "market_value": _number(_first(row, ["value_2qb", "sf_value", "value"])),
                "source_trace": DYNASTYPROCESS_PICKS_URL,
            }
        )
    return pd.DataFrame(rows, columns=_pick_market_columns())


def _normalize_nflverse_usage(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=_usage_columns())

    for _, row in frame.iterrows():
        player_id = _first(row, ["player_id", "gsis_id", "pfr_id"])
        rows.append(
            {
                "source": "nflverse",
                "season": _first(row, ["season"]),
                "week": _first(row, ["week"]),
                "player_id": str(player_id) if player_id not in ("", None) else "",
                "player_name": _first(row, ["player_display_name", "player_name", "recent_team"]),
                "position": _first(row, ["position"]),
                "team": _first(row, ["recent_team", "team"]),
                "targets": _number(_first(row, ["targets"])),
                "carries": _number(_first(row, ["carries"])),
                "receptions": _number(_first(row, ["receptions"])),
                "passing_attempts": _number(_first(row, ["attempts", "passing_attempts"])),
                "fantasy_points_ppr": _number(_first(row, ["fantasy_points_ppr", "fantasy_points"])),
                "source_trace": NFLVERSE_USAGE_URL,
            }
        )
    return pd.DataFrame(rows, columns=_usage_columns())


def _freshness(source: str, dataset: str, status: str, url: str, cache_path: Path | None = None) -> dict[str, Any]:
    return {
        "source": source,
        "dataset": dataset,
        "status": status,
        "source_url": url,
        "cache_path": str(cache_path.as_posix()) if cache_path else "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "row_count": 0,
    }


def _first(row: pd.Series, columns: list[str]) -> Any:
    for column in columns:
        if column in row and not pd.isna(row[column]) and row[column] != "":
            return row[column]
    return ""


def _number(value: Any) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return 0.0
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _round_from_pick(pick: str, fallback: Any) -> Any:
    if fallback not in ("", None) and not pd.isna(fallback):
        return fallback
    if "." in pick:
        return pick.split(".", 1)[0]
    if pick and pick[0].isdigit():
        return pick[0]
    return ""


def _player_market_columns() -> list[str]:
    return ["source", "source_player_id", "player_id", "player_name", "position", "market_value", "market_rank", "value_format", "source_trace"]


def _pick_market_columns() -> list[str]:
    return ["source", "pick_label", "pick_season", "round", "market_value", "source_trace"]


def _usage_columns() -> list[str]:
    return [
        "source",
        "season",
        "week",
        "player_id",
        "player_name",
        "position",
        "team",
        "targets",
        "carries",
        "receptions",
        "passing_attempts",
        "fantasy_points_ppr",
        "source_trace",
    ]


def _freshness_columns() -> list[str]:
    return ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"]
