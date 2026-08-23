from __future__ import annotations

"""Discovery and persistence for the multi-league refresh orchestrator."""

from pathlib import Path
from typing import Any

from .sleeper_api import SleeperAPI
from .league_paths import USERS_ROOT, _safe_component
from .utils import DATA_DIR, dump_json, load_json


REGISTRY_PATH = DATA_DIR / "league_registry.json"


def user_registry_path(user_id: str | int) -> Path:
    return USERS_ROOT / _safe_component(str(user_id), "user") / "league_registry.json"


def classify_league(league: dict[str, Any]) -> str:
    settings = league.get("settings") if isinstance(league.get("settings"), dict) else {}
    if settings.get("best_ball") == 1:
        return "best_ball"
    if settings.get("type") in (1, 2):
        return "dynasty"
    return "redraft"


def discover_leagues(api: SleeperAPI, username: str, season: str) -> list[dict[str, Any]]:
    user = api.user(username)
    user_id = str(user.get("user_id") or username)
    leagues = api.user_leagues(user_id, str(season))
    entries: list[dict[str, Any]] = []

    for league in leagues:
        league_id = str(league.get("league_id") or "")
        if not league_id:
            continue
        rosters = api.rosters(str(season), league_id)
        roster_id = _user_roster_id(rosters, user_id)
        entries.append(
            {
                "league_id": league_id,
                "name": league.get("name", ""),
                "season": str(season),
                "league_type": classify_league(league),
                "roster_id": roster_id,
                "sleeper_user_id": user_id,
                "identity_status": "verified_roster_match" if roster_id is not None else "unverified",
                "total_rosters": league.get("total_rosters"),
            }
        )
    return entries


def save_registry(
    entries: list[dict[str, Any]],
    path: Path | None = None,
    user_id: str | int | None = None,
) -> None:
    path = path or (user_registry_path(user_id) if user_id is not None else REGISTRY_PATH)
    dump_json(path, entries)


def load_registry(path: Path | None = None, user_id: str | int | None = None) -> list[dict[str, Any]]:
    path = path or (user_registry_path(user_id) if user_id is not None else REGISTRY_PATH)
    if not path.exists():
        return []
    data = load_json(path)
    return data if isinstance(data, list) else []


def _user_roster_id(rosters: list[dict[str, Any]], user_id: str) -> int | None:
    for roster in rosters:
        if str(roster.get("owner_id") or "") == user_id:
            roster_id = roster.get("roster_id")
            return int(roster_id) if roster_id not in (None, "") else None
    return None
