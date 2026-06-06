from __future__ import annotations

from typing import Any

import pandas as pd

from .players import player_field, player_name
from .utils import epoch_ms_to_datetime, join_items, json_dumps, listify, safe_get


def build_user_maps(users: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    users_by_id = {str(user.get("user_id")): user for user in users}
    team_names = {}
    for user in users:
        user_id = str(user.get("user_id"))
        team_names[user_id] = safe_get(user.get("metadata"), "team_name") or user.get("display_name", "")
    return users_by_id, team_names


def build_roster_maps(
    rosters: list[dict[str, Any]],
    users: list[dict[str, Any]],
    my_display_name: str,
    my_team_name: str,
    configured_roster_id: int | None = None,
) -> tuple[dict[int, dict[str, Any]], int | None]:
    users_by_id, _ = build_user_maps(users)
    roster_map: dict[int, dict[str, Any]] = {}
    my_roster_id = None

    for roster in rosters:
        roster_id = int(roster.get("roster_id"))
        owner_id = str(roster.get("owner_id") or "")
        user = users_by_id.get(owner_id, {})
        display_name = user.get("display_name", "")
        team_name = safe_get(user.get("metadata"), "team_name") or display_name
        record = {
            "roster_id": roster_id,
            "owner_id": owner_id,
            "display_name": display_name,
            "team_name": team_name,
        }
        roster_map[roster_id] = record
        if configured_roster_id is not None and roster_id == configured_roster_id:
            my_roster_id = roster_id
        elif display_name.lower() == my_display_name.lower() or team_name.lower() == my_team_name.lower():
            my_roster_id = roster_id

    return roster_map, my_roster_id


def normalize_league(season: str, league: dict[str, Any]) -> list[dict[str, Any]]:
    settings = league.get("settings") or {}
    return [
        {
            "season": season,
            "league_id": league.get("league_id", ""),
            "name": league.get("name", ""),
            "status": league.get("status", ""),
            "scoring_settings": json_dumps(league.get("scoring_settings")),
            "roster_positions": json_dumps(league.get("roster_positions")),
            "playoff_week_start": settings.get("playoff_week_start", ""),
            "settings": json_dumps(settings),
        }
    ]


def normalize_teams(
    season: str,
    league_id: str,
    users: list[dict[str, Any]],
    rosters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    users_by_id, _ = build_user_maps(users)
    rows = []
    for roster in rosters:
        owner_id = str(roster.get("owner_id") or "")
        user = users_by_id.get(owner_id, {})
        settings = roster.get("settings") or {}
        rows.append(
            {
                "season": season,
                "league_id": league_id,
                "roster_id": roster.get("roster_id"),
                "owner_id": owner_id,
                "display_name": user.get("display_name", ""),
                "team_name": safe_get(user.get("metadata"), "team_name") or user.get("display_name", ""),
                "waiver_position": settings.get("waiver_position", ""),
                "waiver_budget_used": settings.get("waiver_budget_used", ""),
                "total_moves": settings.get("total_moves", ""),
            }
        )
    return rows


def normalize_roster_players(
    season: str,
    league_id: str,
    rosters: list[dict[str, Any]],
    roster_map: dict[int, dict[str, Any]],
    my_roster_id: int | None,
    players: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for roster in rosters:
        roster_id = int(roster.get("roster_id"))
        owner_id = str(roster.get("owner_id") or "")
        starters = set(str(pid) for pid in listify(roster.get("starters")))
        taxi = set(str(pid) for pid in listify(roster.get("taxi")))
        reserve = set(str(pid) for pid in listify(roster.get("reserve")))
        for pid in listify(roster.get("players")):
            player_id = str(pid)
            if player_id in starters:
                roster_status = "starter"
            elif player_id in taxi:
                roster_status = "taxi"
            elif player_id in reserve:
                roster_status = "reserve"
            else:
                roster_status = "bench"
            rows.append(
                {
                    "season": season,
                    "league_id": league_id,
                    "roster_id": roster_id,
                    "owner_id": owner_id,
                    "player_id": player_id,
                    "player_name": player_name(players, player_id),
                    "position": player_field(players, player_id, "position"),
                    "nfl_team": player_field(players, player_id, "team"),
                    "age": player_field(players, player_id, "age"),
                    "years_exp": player_field(players, player_id, "years_exp"),
                    "roster_status": roster_status,
                    "is_my_team": roster_id == my_roster_id,
                    "team_name": roster_map.get(roster_id, {}).get("team_name", ""),
                }
            )
    return rows


def normalize_drafts(season: str, league_id: str, drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "season": season,
            "league_id": league_id,
            "draft_id": draft.get("draft_id", ""),
            "status": draft.get("status", ""),
            "type": draft.get("type", ""),
            "settings": json_dumps(draft.get("settings")),
        }
        for draft in drafts
    ]


def normalize_draft_picks(
    season: str,
    league_id: str,
    draft_picks_by_draft: dict[str, list[dict[str, Any]]],
    players: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for draft_id, picks in draft_picks_by_draft.items():
        for pick in picks:
            player_id = str(pick.get("player_id") or "")
            rows.append(
                {
                    "season": season,
                    "league_id": league_id,
                    "draft_id": draft_id,
                    "pick_no": pick.get("pick_no", ""),
                    "round": pick.get("round", ""),
                    "roster_id": pick.get("roster_id", ""),
                    "picked_by": pick.get("picked_by", ""),
                    "player_id": player_id,
                    "player_name": player_name(players, player_id),
                    "position": player_field(players, player_id, "position") or safe_get(pick.get("metadata"), "position", ""),
                    "nfl_team": player_field(players, player_id, "team") or safe_get(pick.get("metadata"), "team", ""),
                }
            )
    return rows


def normalize_traded_picks(
    season: str,
    league_id: str,
    traded_picks: list[dict[str, Any]],
    roster_map: dict[int, dict[str, Any]],
    my_roster_id: int | None,
) -> list[dict[str, Any]]:
    rows = []
    for pick in traded_picks:
        original = _int_or_none(pick.get("roster_id"))
        current = _int_or_none(pick.get("owner_id"))
        previous = _int_or_none(pick.get("previous_owner_id"))
        rows.append(
            {
                "season": season,
                "league_id": league_id,
                "original_roster_id": original or "",
                "original_team_name": _team_name(roster_map, original),
                "round": pick.get("round", ""),
                "pick_season": pick.get("season", ""),
                "current_owner_roster_id": current or "",
                "current_owner_team_name": _team_name(roster_map, current),
                "previous_owner_roster_id": previous or "",
                "previous_owner_team_name": _team_name(roster_map, previous),
                "is_my_original_pick": original == my_roster_id,
                "is_currently_owned_by_me": current == my_roster_id,
            }
        )
    return rows


def normalize_transactions_raw(
    season: str,
    league_id: str,
    transactions_by_week: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows = []
    for week, transactions in transactions_by_week.items():
        for tx in transactions:
            rows.append(
                {
                    "season": season,
                    "league_id": league_id,
                    "week": week,
                    "transaction_id": tx.get("transaction_id", ""),
                    "type": tx.get("type", ""),
                    "status": tx.get("status", ""),
                    "created": tx.get("created", ""),
                    "raw": json_dumps(tx),
                }
            )
    return rows


def _name_rosters(roster_ids: list[int], roster_map: dict[int, dict[str, Any]]) -> str:
    return join_items([roster_map.get(int(rid), {}).get("team_name", str(rid)) for rid in roster_ids])


def _named_player_moves(moves: dict[str, Any] | None, players: dict[str, dict[str, Any]]) -> str:
    if not isinstance(moves, dict):
        return ""
    return join_items([f"{player_name(players, pid)} -> roster {rid}" for pid, rid in moves.items()])


def _named_picks(picks: list[dict[str, Any]] | None) -> str:
    if not picks:
        return ""
    return join_items(
        [
            f"{pick.get('season')} R{pick.get('round')} original roster {pick.get('roster_id')} to roster {pick.get('owner_id')}"
            for pick in picks
        ]
    )


def normalize_transactions(
    season: str,
    league_id: str,
    transactions_by_week: dict[int, list[dict[str, Any]]],
    roster_map: dict[int, dict[str, Any]],
    players: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for week, transactions in transactions_by_week.items():
        for tx in transactions:
            roster_ids = [int(rid) for rid in listify(tx.get("roster_ids"))]
            waiver_bid = safe_get(tx.get("settings"), "waiver_bid", "")
            rows.append(
                {
                    "season": season,
                    "league_id": league_id,
                    "week": week,
                    "transaction_id": tx.get("transaction_id", ""),
                    "type": tx.get("type", ""),
                    "status": tx.get("status", ""),
                    "created_datetime": epoch_ms_to_datetime(tx.get("created")),
                    "roster_ids_involved": join_items(roster_ids),
                    "manager_team_names_involved": _name_rosters(roster_ids, roster_map),
                    "adds": _named_player_moves(tx.get("adds"), players),
                    "drops": _named_player_moves(tx.get("drops"), players),
                    "draft_picks_moved": _named_picks(tx.get("draft_picks")),
                    "waiver_bid": waiver_bid,
                    "faab_moved": json_dumps(tx.get("waiver_budget") or []),
                    "failure_reason": safe_get(tx.get("metadata"), "notes", ""),
                }
            )
    return rows


def normalize_trades(
    season: str,
    league_id: str,
    transactions_by_week: dict[int, list[dict[str, Any]]],
    roster_map: dict[int, dict[str, Any]],
    players: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for week, transactions in transactions_by_week.items():
        for tx in transactions:
            if tx.get("type") != "trade":
                continue
            roster_ids = [int(rid) for rid in listify(tx.get("roster_ids"))]
            if len(roster_ids) != 2:
                continue
            a, b = roster_ids
            adds = tx.get("adds") or {}
            picks = tx.get("draft_picks") or []
            faab = tx.get("waiver_budget") or []

            def players_received(roster_id: int) -> str:
                return join_items([player_name(players, pid) for pid, rid in adds.items() if int(rid) == roster_id])

            def picks_received(roster_id: int) -> str:
                return join_items(
                    [
                        f"{pick.get('season')} R{pick.get('round')} original roster {pick.get('roster_id')}"
                        for pick in picks
                        if int(pick.get("owner_id")) == roster_id
                    ]
                )

            def faab_received(roster_id: int) -> int:
                return sum(int(item.get("amount", 0)) for item in faab if int(item.get("receiver", -1)) == roster_id)

            rows.append(
                {
                    "season": season,
                    "league_id": league_id,
                    "week": week,
                    "transaction_id": tx.get("transaction_id", ""),
                    "created_datetime": epoch_ms_to_datetime(tx.get("created")),
                    "team_a_roster_id": a,
                    "team_a_name": roster_map.get(a, {}).get("team_name", ""),
                    "team_a_players_received": players_received(a),
                    "team_a_picks_received": picks_received(a),
                    "team_a_faab_received": faab_received(a),
                    "team_b_roster_id": b,
                    "team_b_name": roster_map.get(b, {}).get("team_name", ""),
                    "team_b_players_received": players_received(b),
                    "team_b_picks_received": picks_received(b),
                    "team_b_faab_received": faab_received(b),
                    "raw": json_dumps(tx),
                }
            )
    return rows


def normalize_waivers(
    season: str,
    league_id: str,
    transactions_by_week: dict[int, list[dict[str, Any]]],
    roster_map: dict[int, dict[str, Any]],
    players: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for week, transactions in transactions_by_week.items():
        for tx in transactions:
            if tx.get("type") != "waiver":
                continue
            adds = tx.get("adds") or {}
            drops = tx.get("drops") or {}
            roster_ids = [int(rid) for rid in listify(tx.get("roster_ids"))] or list({int(rid) for rid in adds.values()})
            for roster_id in roster_ids:
                added = [player_name(players, pid) for pid, rid in adds.items() if int(rid) == roster_id]
                dropped = [player_name(players, pid) for pid, rid in drops.items() if int(rid) == roster_id]
                rows.append(
                    {
                        "season": season,
                        "league_id": league_id,
                        "week": week,
                        "transaction_id": tx.get("transaction_id", ""),
                        "roster_id": roster_id,
                        "team_name": roster_map.get(roster_id, {}).get("team_name", ""),
                        "player_added": join_items(added),
                        "player_dropped": join_items(dropped),
                        "waiver_bid": safe_get(tx.get("settings"), "waiver_bid", ""),
                        "status": tx.get("status", ""),
                        "failure_reason": safe_get(tx.get("metadata"), "notes", ""),
                    }
                )
    return rows


def to_dataframes(tables: dict[str, list[dict[str, Any]]]) -> dict[str, pd.DataFrame]:
    return {name: pd.DataFrame(rows) for name, rows in tables.items()}


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _team_name(roster_map: dict[int, dict[str, Any]], roster_id: int | None) -> str:
    if roster_id is None:
        return ""
    return roster_map.get(roster_id, {}).get("team_name", "")
