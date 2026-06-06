from __future__ import annotations

from typing import Any

from .sleeper_api import SleeperAPI
from .utils import CACHE_DIR


PLAYER_CACHE = CACHE_DIR / "players_nfl.json"


def load_players(api: SleeperAPI, force: bool = False) -> dict[str, dict[str, Any]]:
    return api.players_nfl(PLAYER_CACHE, force=force)


def player_name(players: dict[str, dict[str, Any]], player_id: str | int | None) -> str:
    if player_id is None:
        return ""
    player = players.get(str(player_id), {})
    return player.get("full_name") or " ".join(
        part for part in [player.get("first_name"), player.get("last_name")] if part
    )


def player_field(players: dict[str, dict[str, Any]], player_id: str | int | None, field: str) -> Any:
    if player_id is None:
        return ""
    return players.get(str(player_id), {}).get(field, "")


def player_row(players: dict[str, dict[str, Any]], player_id: str | int | None) -> dict[str, Any]:
    player = players.get(str(player_id), {}) if player_id is not None else {}
    return {
        "player_id": str(player_id or ""),
        "full_name": player_name(players, player_id),
        "position": player.get("position", ""),
        "team": player.get("team", ""),
        "age": player.get("age", ""),
        "years_exp": player.get("years_exp", ""),
        "fantasy_positions": ";".join(player.get("fantasy_positions") or []),
        "status": player.get("status", ""),
    }


def players_table(players: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        player_row(players, player_id)
        for player_id in sorted(players.keys(), key=lambda value: (not str(value).isdigit(), str(value)))
    ]
