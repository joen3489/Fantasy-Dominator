from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .utils import RAW_EXTERNAL_DIR, dump_json, load_json


DYNASTYPROCESS_VALUES_URL = "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values.csv"
DYNASTYPROCESS_PICKS_URL = "https://raw.githubusercontent.com/DynastyProcess/data/master/files/picks.csv"
NFLVERSE_USAGE_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
FANTASY_NERDS_BASE_URL = "https://api.fantasynerds.com/v1/nfl"


def refresh_external_sources(config: dict[str, Any], force: bool = False) -> dict[str, pd.DataFrame]:
    sources = ((config.get("external_sources") or {}).get("enabled") or [])
    source_policy = config.get("source_policy", "open_legal_only")
    season = str(config.get("current_season", "global") or "global")
    frames = {
        "market_value_sources": pd.DataFrame(columns=_market_source_columns()),
        "market_consensus_values": pd.DataFrame(columns=_market_consensus_columns()),
        "player_market_values": pd.DataFrame(columns=_player_market_columns()),
        "pick_market_values": pd.DataFrame(columns=_pick_market_columns()),
        "player_usage_weekly": pd.DataFrame(columns=_usage_columns()),
        "fantasy_nerds_projection_source": pd.DataFrame(columns=_fantasy_nerds_projection_source_columns()),
        "source_freshness": pd.DataFrame(columns=_freshness_columns()),
    }
    freshness_rows: list[dict[str, Any]] = []

    # Fantasy Nerds is a paid, explicitly user-configured source (Source Policy: "Paid/API-key
    # sources explicitly configured by the user" are allowed independent of source_policy, which
    # only governs the open/legal free-source set below).
    if "fantasy_nerds" in sources:
        api_key = os.environ.get("FANTASY_NERDS_API_KEY", "")
        if not api_key:
            freshness_rows.append(
                _freshness(
                    "fantasy_nerds",
                    "weekly_projections",
                    "disabled:fantasy_nerds_api_key_missing",
                    f"{FANTASY_NERDS_BASE_URL}/weekly-projections",
                )
            )
        else:
            fn_df, row = _fetch_fantasy_nerds(season, api_key, force)
            frames["fantasy_nerds_projection_source"] = fn_df
            freshness_rows.append(row | {"row_count": len(fn_df)})

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
        frames["market_value_sources"] = _normalize_dynastyprocess_market_sources(values)
        frames["market_consensus_values"] = build_market_consensus_values(frames["market_value_sources"])
        frames["player_market_values"] = _legacy_player_values_from_consensus(frames["market_consensus_values"])
        freshness_rows.append(row | {"row_count": len(frames["market_value_sources"])})

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

    if frames["market_consensus_values"].empty and not frames["market_value_sources"].empty:
        frames["market_consensus_values"] = build_market_consensus_values(frames["market_value_sources"])
        frames["player_market_values"] = _legacy_player_values_from_consensus(frames["market_consensus_values"])

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


def _load_json_source(source: str, dataset: str, url: str, cache_path: Path, force: bool) -> tuple[Any, dict[str, Any]]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        try:
            return load_json(cache_path), _freshness(source, dataset, "cached", url, cache_path)
        except Exception as exc:
            return {}, _freshness(source, dataset, f"cache_error:{type(exc).__name__}", url, cache_path)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()
        dump_json(cache_path, payload)
        return payload, _freshness(source, dataset, "refreshed", url, cache_path)
    except Exception as exc:
        if cache_path.exists():
            try:
                return load_json(cache_path), _freshness(source, dataset, f"cached_after_refresh_error:{type(exc).__name__}", url, cache_path)
            except Exception:
                pass
        return {}, _freshness(source, dataset, f"unavailable:{type(exc).__name__}", url, cache_path)


def _fetch_fantasy_nerds(season: str, api_key: str, force: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache_path = RAW_EXTERNAL_DIR / "fantasy_nerds" / season / "weekly_projections.json"
    url = f"{FANTASY_NERDS_BASE_URL}/weekly-projections?apikey={api_key}"
    payload, row = _load_json_source("fantasy_nerds", "weekly_projections", url, cache_path, force)
    # Never leak the API key into an audit artifact (freshness rows are written to CSV/SQLite).
    row["source_url"] = f"{FANTASY_NERDS_BASE_URL}/weekly-projections?apikey=REDACTED"
    frame = _normalize_fantasy_nerds_projections(payload)
    return frame, row


def _extract_fantasy_nerds_players(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("players"), list):
            return [item for item in payload["players"] if isinstance(item, dict)]
        # Fantasy Nerds sometimes groups projections by position key (qb/rb/wr/te/k/def).
        flattened: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, list):
                flattened.extend(item for item in value if isinstance(item, dict))
        if flattened:
            return flattened
    return []


def _normalize_fantasy_nerds_projections(payload: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for player in _extract_fantasy_nerds_players(payload):
        name = str(player.get("name") or player.get("playerName") or "")
        if not name:
            continue
        rows.append(
            {
                "source": "fantasy_nerds",
                "fn_player_id": str(player.get("playerId") or player.get("player_id") or ""),
                "player_name": name,
                "normalized_name": _normalize_fn_name(name),
                "position": str(player.get("position", "")),
                "team": str(player.get("team", "")),
                "projected_fantasy_points": _number(
                    _first_key(player, ["projectedPts", "fanPts", "fantasyPoints", "points"])
                ),
                "source_confidence": "high",
                "source_trace": f"{FANTASY_NERDS_BASE_URL}/weekly-projections",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=_fantasy_nerds_projection_source_columns())


def _first_key(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return ""


def _normalize_fn_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _normalize_dynastyprocess_market_sources(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=_market_source_columns())

    for _, row in frame.iterrows():
        player_id = _first(row, ["sleeper_id", "player_id", "fantasypros_id", "gsis_id"])
        player_name = _first(row, ["player", "player_name", "name"])
        value = _first(row, ["value_2qb", "sf_value", "value", "ecr_2qb"])
        raw_value = _number(value)
        rows.append(
            {
                "source": "dynastyprocess",
                "source_access_type": "open_dataset",
                "source_player_id": player_id,
                "player_id": str(player_id) if player_id not in ("", None) else "",
                "player_name": player_name,
                "position": _first(row, ["pos", "position"]),
                "raw_value": raw_value,
                "normalized_value": _normalize_market_value(raw_value),
                "market_rank": _number(_first(row, ["overall_rank", "rank", "ecr_2qb"])),
                "value_format": "superflex_preferred",
                "source_confidence": "high" if player_id not in ("", None) else "medium",
                "source_trace": DYNASTYPROCESS_VALUES_URL,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=_market_source_columns())


def build_market_consensus_values(market_sources_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if market_sources_df.empty:
        return pd.DataFrame(rows, columns=_market_consensus_columns())

    for _, group in market_sources_df.fillna("").groupby(["player_id", "player_name", "position"], dropna=False):
        values = [_number(value) for value in group.get("normalized_value", pd.Series(dtype=float)).tolist() if _number(value) > 0]
        if not values:
            continue
        source_count = len(values)
        consensus = round(sum(values) / source_count, 2)
        disagreement = round(max(values) - min(values), 2) if source_count > 1 else 0.0
        access_types = {str(value) for value in group.get("source_access_type", pd.Series(dtype=str)).tolist()}
        confidences = {str(value) for value in group.get("source_confidence", pd.Series(dtype=str)).tolist()}
        confidence = _consensus_confidence(source_count, disagreement, access_types, confidences)
        sources = sorted({str(value) for value in group.get("source", pd.Series(dtype=str)).tolist() if str(value)})
        traces = sorted({str(value) for value in group.get("source_trace", pd.Series(dtype=str)).tolist() if str(value)})
        first = group.iloc[0]
        rows.append(
            {
                "player_id": first.get("player_id", ""),
                "player_name": first.get("player_name", ""),
                "position": first.get("position", ""),
                "consensus_value": consensus,
                "source_count": source_count,
                "disagreement_score": disagreement,
                "best_source": sources[0] if sources else "",
                "confidence": confidence,
                "source_trace": "; ".join(traces),
            }
        )
    return pd.DataFrame(rows, columns=_market_consensus_columns()).sort_values("consensus_value", ascending=False)


def _legacy_player_values_from_consensus(consensus_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if consensus_df.empty:
        return pd.DataFrame(rows, columns=_player_market_columns())
    ranked = consensus_df.sort_values("consensus_value", ascending=False).reset_index(drop=True)
    for index, row in ranked.iterrows():
        rows.append(
            {
                "source": "market_consensus",
                "source_player_id": row.get("player_id", ""),
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "market_value": row.get("consensus_value", 0),
                "market_rank": index + 1,
                "value_format": f"consensus_sources={row.get('source_count', 0)}",
                "source_trace": row.get("source_trace", ""),
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


def _normalize_market_value(value: float) -> float:
    if value > 100:
        return round(value / 100, 2)
    return round(value, 2)


def _consensus_confidence(source_count: int, disagreement: float, access_types: set[str], confidences: set[str]) -> str:
    if source_count <= 0:
        return "low"
    if access_types == {"user_provided"}:
        return "medium"
    if "low" in confidences:
        return "low"
    if disagreement >= 25:
        return "medium"
    if source_count == 1 and "high" in confidences:
        return "high"
    if source_count >= 2:
        return "high"
    return "medium"


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


def _market_source_columns() -> list[str]:
    return [
        "source",
        "source_access_type",
        "source_player_id",
        "player_id",
        "player_name",
        "position",
        "raw_value",
        "normalized_value",
        "market_rank",
        "value_format",
        "source_confidence",
        "source_trace",
        "checked_at",
    ]


def _market_consensus_columns() -> list[str]:
    return [
        "player_id",
        "player_name",
        "position",
        "consensus_value",
        "source_count",
        "disagreement_score",
        "best_source",
        "confidence",
        "source_trace",
    ]


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


def _fantasy_nerds_projection_source_columns() -> list[str]:
    return [
        "source",
        "fn_player_id",
        "player_name",
        "normalized_name",
        "position",
        "team",
        "projected_fantasy_points",
        "source_confidence",
        "source_trace",
        "checked_at",
    ]
