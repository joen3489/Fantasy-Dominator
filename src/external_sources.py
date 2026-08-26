from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .utils import DATA_DIR, RAW_EXTERNAL_DIR, cache_is_fresh, dump_json, load_json


DYNASTYPROCESS_VALUES_URL = "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values.csv"
DYNASTYPROCESS_PICKS_URL = "https://raw.githubusercontent.com/DynastyProcess/data/master/files/values-picks.csv"
NFLVERSE_USAGE_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
NFLVERSE_SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
FANTASY_NERDS_BASE_URL = "https://api.fantasynerds.com/v1/nfl"
DEFAULT_EXTERNAL_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60


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
        "nfl_schedule": pd.DataFrame(columns=_schedule_columns()),
        "fantasy_nerds_projection_source": pd.DataFrame(columns=_fantasy_nerds_projection_source_columns()),
        "source_freshness": pd.DataFrame(columns=_freshness_columns()),
    }
    freshness_rows: list[dict[str, Any]] = []

    manual_market_sources, manual_market_freshness = _load_user_market_files(config, season)
    if not manual_market_sources.empty:
        frames["market_value_sources"] = manual_market_sources
    freshness_rows.extend(manual_market_freshness)

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
        if not frames["market_value_sources"].empty:
            frames["market_consensus_values"] = build_market_consensus_values(frames["market_value_sources"])
            frames["player_market_values"] = _legacy_player_values_from_consensus(frames["market_consensus_values"])
        frames["source_freshness"] = pd.DataFrame(freshness_rows, columns=_freshness_columns())
        return frames

    if "dynastyprocess" in sources:
        values, row = _load_csv_source(
            "dynastyprocess",
            "player_values",
            DYNASTYPROCESS_VALUES_URL,
            RAW_EXTERNAL_DIR / "dynastyprocess" / season / "values.csv",
            force,
            _external_cache_max_age_seconds(),
        )
        dynastyprocess_sources = _normalize_dynastyprocess_market_sources(values)
        if frames["market_value_sources"].empty:
            frames["market_value_sources"] = dynastyprocess_sources
        else:
            frames["market_value_sources"] = pd.concat(
                [frames["market_value_sources"], dynastyprocess_sources],
                ignore_index=True,
                sort=False,
            )
        frames["market_consensus_values"] = build_market_consensus_values(frames["market_value_sources"])
        frames["player_market_values"] = _legacy_player_values_from_consensus(frames["market_consensus_values"])
        freshness_rows.append(row | {"row_count": len(frames["market_value_sources"])})

        picks, row = _load_csv_source(
            "dynastyprocess",
            "pick_values",
            DYNASTYPROCESS_PICKS_URL,
            RAW_EXTERNAL_DIR / "dynastyprocess" / season / "values-picks.csv",
            force,
            _external_cache_max_age_seconds(),
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
            _external_cache_max_age_seconds(),
        )
        frames["player_usage_weekly"] = _normalize_nflverse_usage(usage)
        freshness_rows.append(row | {"row_count": len(frames["player_usage_weekly"])})
        schedule, row = _load_csv_source(
            "nflverse",
            "nfl_schedule",
            NFLVERSE_SCHEDULE_URL,
            RAW_EXTERNAL_DIR / "nflverse" / season / "games.csv",
            force,
            _external_cache_max_age_seconds(),
        )
        frames["nfl_schedule"] = _normalize_nflverse_schedule(schedule)
        freshness_rows.append(row | {"row_count": len(frames["nfl_schedule"])})

    if not freshness_rows:
        freshness_rows.append(_freshness("external_sources", "disabled", "no_external_sources_enabled", ""))

    if frames["market_consensus_values"].empty and not frames["market_value_sources"].empty:
        frames["market_consensus_values"] = build_market_consensus_values(frames["market_value_sources"])
        frames["player_market_values"] = _legacy_player_values_from_consensus(frames["market_consensus_values"])

    frames["source_freshness"] = pd.DataFrame(freshness_rows, columns=_freshness_columns())
    return frames


def _load_csv_source(
    source: str,
    dataset: str,
    url: str,
    cache_path: Path,
    force: bool,
    max_age_seconds: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_fresh = cache_path.exists() and (
        max_age_seconds is None or cache_is_fresh(cache_path, max_age_seconds)
    )
    if cache_fresh and not force:
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
                return pd.read_csv(cache_path), _freshness(source, dataset, f"stale_after_refresh_error:{type(exc).__name__}", url, cache_path)
            except Exception:
                pass
        return pd.DataFrame(), _freshness(source, dataset, f"unavailable:{type(exc).__name__}", url, cache_path)


def _load_user_market_files(
    config: dict[str, Any], season: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Load optional user-provided canonical market exports.

    User files are an explicit input seam, not a scraped provider. Relative
    paths are resolved under the durable data root and values must already be
    in the canonical market scale; no magnitude-based rescaling is attempted.
    """

    external = config.get("external_sources") or {}
    configured = external.get("market_value_files") or []
    if isinstance(configured, (str, Path)):
        configured = [configured]
    if not isinstance(configured, list):
        configured = []

    frames: list[pd.DataFrame] = []
    freshness: list[dict[str, Any]] = []
    for entry in configured:
        spec = entry if isinstance(entry, dict) else {"path": entry}
        raw_path = str(spec.get("path") or "").strip()
        if not raw_path:
            freshness.append(
                _freshness(
                    "user_market_file",
                    "player_values",
                    "disabled:user_file_path_missing",
                    "manual_file:unconfigured",
                )
            )
            continue
        try:
            rendered_path = raw_path.format(season=season)
        except (KeyError, ValueError):
            rendered_path = raw_path
        path = Path(rendered_path).expanduser()
        if not path.is_absolute():
            path = DATA_DIR / path
        trace = _manual_file_trace(path)
        source = _manual_market_source_name(spec.get("source"), path)
        source_url = f"manual_file:{trace}"
        if not path.is_file():
            freshness.append(
                _freshness(source, "player_values", "disabled:user_file_missing", source_url, path)
            )
            continue
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            freshness.append(
                _freshness(source, "player_values", f"unavailable:{type(exc).__name__}", source_url, path)
            )
            continue
        normalized = _normalize_user_market_sources(raw, path, spec)
        frames.append(normalized)
        freshness.append(
            _freshness(source, "player_values", "cached", source_url, path)
            | {"row_count": len(normalized)}
        )

    if not frames:
        return pd.DataFrame(columns=_market_source_columns()), freshness
    return pd.concat(frames, ignore_index=True, sort=False)[_market_source_columns()], freshness


def _normalize_user_market_sources(
    frame: pd.DataFrame, path: Path, spec: dict[str, Any]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    source = _manual_market_source_name(spec.get("source"), path)
    file_trace = f"manual_file:{_manual_file_trace(path)}"
    default_confidence = str(spec.get("confidence") or "medium").strip().lower()
    if default_confidence not in {"high", "medium", "low"}:
        default_confidence = "low"
    default_format = str(spec.get("value_format") or "user_provided_canonical_0_100").strip()
    for _, row in frame.fillna("").iterrows():
        name = str(_first(row, ["player_name", "player", "name"])).strip()
        position = str(_first(row, ["position", "pos"])).strip().upper()
        value = _first(row, ["market_value", "consensus_value", "normalized_value"])
        normalized_value = _number(value)
        if not name or position not in {"QB", "RB", "WR", "TE"} or normalized_value <= 0:
            continue
        source_id = str(_first(row, ["sleeper_id", "player_id", "source_player_id"])).strip()
        confidence = str(_first(row, ["source_confidence", "confidence"])).strip().lower() or default_confidence
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        row_trace = str(row.get("source_trace") or "").strip()
        trace = "; ".join(value for value in (file_trace, row_trace) if value)
        rows.append(
            {
                "source": source,
                "source_access_type": "user_provided",
                "source_player_id": source_id,
                "player_id": source_id,
                "player_name": name,
                "position": position,
                "raw_value": normalized_value,
                "normalized_value": normalized_value,
                "market_rank": _number(_first(row, ["market_rank", "rank"])),
                "value_format": str(row.get("value_format") or default_format),
                "source_confidence": confidence,
                "source_trace": trace,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=_market_source_columns())


def _manual_market_source_name(value: Any, path: Path) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        candidate = path.stem.lower()
    candidate = re.sub(r"[^a-z0-9]+", "_", candidate).strip("_")
    return f"user_provided_{candidate or 'market_file'}"


def _manual_file_trace(path: Path) -> str:
    try:
        return path.relative_to(DATA_DIR).as_posix()
    except ValueError:
        return path.name


def _load_json_source(
    source: str,
    dataset: str,
    url: str,
    cache_path: Path,
    force: bool,
    max_age_seconds: int | None = None,
) -> tuple[Any, dict[str, Any]]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_fresh = cache_path.exists() and (
        max_age_seconds is None or cache_is_fresh(cache_path, max_age_seconds)
    )
    if cache_fresh and not force:
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
                return load_json(cache_path), _freshness(source, dataset, f"stale_after_refresh_error:{type(exc).__name__}", url, cache_path)
            except Exception:
                pass
        return {}, _freshness(source, dataset, f"unavailable:{type(exc).__name__}", url, cache_path)


def _fetch_fantasy_nerds(season: str, api_key: str, force: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache_path = RAW_EXTERNAL_DIR / "fantasy_nerds" / season / "weekly_projections.json"
    url = f"{FANTASY_NERDS_BASE_URL}/weekly-projections?apikey={api_key}"
    payload, row = _load_json_source(
        "fantasy_nerds",
        "weekly_projections",
        url,
        cache_path,
        force,
        _external_cache_max_age_seconds(),
    )
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
                "value_format": "superflex_preferred_value_2qb_x100",
                "source_confidence": "high" if player_id not in ("", None) else "medium",
                "source_trace": f"{DYNASTYPROCESS_VALUES_URL};value_2qb/100",
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
        # DynastyProcess values-picks.csv is an ECR/rank file.  It does not
        # expose the same value_2qb field as values.csv, so do not silently
        # turn its rank into a trade value or emit a misleading 0.0 value.
        pick = str(_first(row, ["player", "pick", "selection", "label", "name"]))
        raw_value = _first(row, ["value_2qb", "sf_value", "value"])
        ranking_value = _first(row, ["ecr_2qb", "ecr_1qb"])
        rows.append(
            {
                "source": "dynastyprocess",
                "pick_label": pick,
                "pick_season": _first(row, ["season", "year"]) or _pick_season_from_label(pick),
                "round": _round_from_pick(pick, _first(row, ["round"])),
                "market_value": _number(raw_value) if raw_value not in ("", None) else "",
                "ranking_value": _number(ranking_value) if ranking_value not in ("", None) else "",
                "value_status": "external_value" if raw_value not in ("", None) else "rank_only",
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
        season = _first(row, ["season"])
        week = _first(row, ["week"])
        team = _first(row, ["recent_team", "team"])
        opponent_team = _first(row, ["opponent_team"])
        game_id = _first(row, ["game_id"])
        if game_id in ("", None) and season not in ("", None) and week not in ("", None) and team and opponent_team:
            game_id = f"{season}_{week}_{team}_{opponent_team}"
        rows.append(
            {
                "source": "nflverse",
                "season": season,
                "week": week,
                "player_id": str(player_id) if player_id not in ("", None) else "",
                "player_name": _first(row, ["player_display_name", "player_name", "recent_team"]),
                "position": _first(row, ["position"]),
                "team": team,
                "opponent_team": opponent_team,
                "game_id": game_id,
                "targets": _number(_first(row, ["targets"])),
                "carries": _number(_first(row, ["carries"])),
                "receptions": _number(_first(row, ["receptions"])),
                "passing_attempts": _number(_first(row, ["attempts", "passing_attempts"])),
                "fantasy_points_ppr": _number(_first(row, ["fantasy_points_ppr", "fantasy_points"])),
                "source_trace": NFLVERSE_USAGE_URL,
            }
        )
    return pd.DataFrame(rows, columns=_usage_columns())


def _normalize_nflverse_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the schedule seam small and explicit.

    The raw games file is preserved by ``_load_csv_source``.  This normalized
    table carries only regular-season identity and the fields needed to join a
    player/team to the next opponent and to count future bye weeks.
    """

    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=_schedule_columns())
    for _, row in frame.iterrows():
        game_type = str(_first(row, ["game_type"])).upper()
        if game_type and game_type != "REG":
            continue
        season = _first(row, ["season"])
        week = _first(row, ["week"])
        away_team = str(_first(row, ["away_team"])).upper()
        home_team = str(_first(row, ["home_team"])).upper()
        if season in ("", None) or week in ("", None) or not away_team or not home_team:
            continue
        away_score = _first(row, ["away_score"])
        home_score = _first(row, ["home_score"])
        played = away_score not in ("", None) and home_score not in ("", None)
        rows.append(
            {
                "season": season,
                "week": week,
                "game_id": _first(row, ["game_id"]),
                "game_type": game_type or "REG",
                "gameday": _first(row, ["gameday"]),
                "away_team": away_team,
                "home_team": home_team,
                "schedule_status": "played" if played else "scheduled",
                "source_trace": NFLVERSE_SCHEDULE_URL,
            }
        )
    return pd.DataFrame(rows, columns=_schedule_columns())


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


def _external_cache_max_age_seconds() -> int:
    try:
        return max(
            0,
            int(
                os.environ.get(
                    "FRONT_OFFICE_EXTERNAL_CACHE_MAX_AGE_SECONDS",
                    str(DEFAULT_EXTERNAL_CACHE_MAX_AGE_SECONDS),
                )
            ),
        )
    except (TypeError, ValueError):
        return DEFAULT_EXTERNAL_CACHE_MAX_AGE_SECONDS


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
    # DynastyProcess values.csv stores value_2qb in centipoints/x100 units.
    # Dividing only values above 100 made a raw 93 look more valuable than a
    # raw 7592 player after normalization. Keep the source scale explicit and
    # normalize every non-negative source value consistently.
    return round(value / 100, 2)


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
    dotted = re.search(r"\bPick\s+([0-9]+)\.", pick, flags=re.IGNORECASE)
    if dotted:
        return dotted.group(1)
    ordinal = re.search(r"\b(?:Early|Mid|Late)\s+([0-9]+)(?:st|nd|rd|th)\b", pick, flags=re.IGNORECASE)
    if ordinal:
        return ordinal.group(1)
    plain_ordinal = re.search(r"\b([0-9]+)(?:st|nd|rd|th)\b", pick, flags=re.IGNORECASE)
    if plain_ordinal:
        return plain_ordinal.group(1)
    return ""


def _pick_season_from_label(pick: str) -> str:
    match = re.search(r"\b(20[0-9]{2})\b", pick)
    return match.group(1) if match else ""


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
    return [
        "source",
        "pick_label",
        "pick_season",
        "round",
        "market_value",
        "ranking_value",
        "value_status",
        "source_trace",
    ]


def _usage_columns() -> list[str]:
    return [
        "source",
        "season",
        "week",
        "player_id",
        "player_name",
        "position",
        "team",
        "opponent_team",
        "game_id",
        "targets",
        "carries",
        "receptions",
        "passing_attempts",
        "fantasy_points_ppr",
        "source_trace",
    ]


def _schedule_columns() -> list[str]:
    return [
        "season",
        "week",
        "game_id",
        "game_type",
        "gameday",
        "away_team",
        "home_team",
        "schedule_status",
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
