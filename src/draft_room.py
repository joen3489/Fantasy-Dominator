from __future__ import annotations

"""Build the reader-facing, league-scoped Draft Room contract.

The Draft Room deliberately composes existing canonical tables instead of
creating a second recommendation model.  Its job is to turn those facts into
one usable draft-season workflow while keeping every read traceable to a
source, a model table, or an explicitly named internal curve.
"""

from typing import Any, Iterable


TARGET_LABELS = {"true_buy_low", "deep_watch"}
FADE_LABELS = {"sell_window"}
NEED_FIELDS = {
    "QB": "need_qb",
    "RB": "need_rb",
    "WR": "need_pass_catcher",
    "TE": "need_pass_catcher",
}
NEED_PRIORITY = {"high": 3, "medium": 2, "low": 1}


def build_draft_room(
    tables: dict[str, list[dict[str, Any]]],
    config: dict[str, Any] | None,
    league_id: str = "",
    my_roster_id: int | None = None,
    my_team_name: str = "",
) -> dict[str, Any]:
    """Return a stable Draft Room payload for one current league/team scope."""

    config = config or {}
    season = str(config.get("current_season") or _latest_season(tables.get("roster_players", [])))
    roster = _current_rows(tables.get("roster_players", []), season, "roster_id")
    my_roster_id = _int(my_roster_id)
    if not my_team_name:
        my_team_name = _team_name(tables.get("teams", []), my_roster_id, season)

    needs_row = _first_matching(tables.get("team_needs_matrix", []), "roster_id", my_roster_id)
    strategy = config.get("strategy_profile") or {}
    needs = {
        "QB": str(needs_row.get("need_qb", "unknown")),
        "RB": str(needs_row.get("need_rb", "unknown")),
        "WR": str(needs_row.get("need_pass_catcher", "unknown")),
        "TE": str(needs_row.get("need_pass_catcher", "unknown")),
        "PICK": str(needs_row.get("need_picks", "unknown")),
    }

    draft_board = _build_draft_board(tables, roster, needs)
    trade_targets = _build_trade_targets(tables.get("action_recommendations", []), my_roster_id, my_team_name)
    fades = _build_fades(tables.get("action_recommendations", []), my_roster_id, my_team_name)
    pick_leverage = _build_pick_leverage(
        tables.get("pick_ownership", []),
        tables.get("pick_market_values", []),
        config.get("tracked_picks") or [],
        season,
        my_roster_id,
        tables.get("draft_picks", []),
    )

    pick_value_rows = [row for row in tables.get("pick_market_values", []) if _number(row.get("market_value")) > 0]
    market_rows = [row for row in tables.get("player_market_values", []) if _number(row.get("market_value")) > 0]
    source_health = _source_health(tables.get("source_freshness", []))
    return {
        "schema_version": "draft_room_v1",
        "league_id": str(league_id or ""),
        "season": season,
        "team": {
            "roster_id": my_roster_id,
            "team_name": my_team_name or "Unknown team",
            "team_shape": needs_row.get("team_shape", "unknown"),
            "strategy_name": strategy.get("name", "").strip() if isinstance(strategy.get("name", ""), str) else "",
            "team_direction": strategy.get("team_direction", ""),
            "contention_window": strategy.get("contention_window", ""),
            "needs": needs,
        },
        "summary": {
            "available_player_count": len(draft_board),
            "trade_target_count": len(trade_targets),
            "fade_count": len(fades),
            "future_pick_count": len(pick_leverage),
            "owned_pick_count": sum(row["ownership_status"] == "owned_by_you" for row in pick_leverage),
            "original_picks_away": sum(row["ownership_status"] == "your_original_pick_away" for row in pick_leverage),
        },
        "draft_board": draft_board,
        "trade_targets": trade_targets,
        "fades": fades,
        "pick_leverage": pick_leverage,
        "data_quality": {
            "market_player_rows": len(market_rows),
            "market_player_source": "DynastyProcess values.csv; availability matched by current league roster names when Sleeper IDs are unavailable",
            "pick_value_rows": len(pick_value_rows),
            "pick_value_source": (
                "DynastyProcess pick values"
                if pick_value_rows
                else "Internal round curve; DynastyProcess values-picks.csv supplies ECR ranks, not trade values"
            ),
            "source_health": source_health,
        },
    }


def _build_draft_board(
    tables: dict[str, list[dict[str, Any]]],
    roster: list[dict[str, Any]],
    needs: dict[str, str],
) -> list[dict[str, Any]]:
    roster_ids = {str(row.get("player_id", "")) for row in roster if str(row.get("player_id", ""))}
    roster_names = {_name_key(row.get("player_name")) for row in roster if _name_key(row.get("player_name"))}
    unique: dict[str, dict[str, Any]] = {}
    for row in tables.get("player_market_values", []):
        value = _number(row.get("market_value"))
        name = str(row.get("player_name", "")).strip()
        if value <= 0 or not name:
            continue
        player_id = str(row.get("player_id", "")).strip()
        name_key = _name_key(name)
        if player_id and player_id in roster_ids or name_key in roster_names:
            continue
        identity = player_id or name_key
        existing = unique.get(identity)
        if existing and _number(existing.get("market_value")) >= value:
            continue
        position = str(row.get("position", "")).strip()
        need_field = NEED_FIELDS.get(position, "")
        need = needs.get(position, "unknown")
        need_priority = NEED_PRIORITY.get(need.lower(), 0)
        source_trace = str(row.get("source_trace", "")).strip()
        identity_note = "Sleeper-linked" if player_id else "name-match availability"
        unique[identity] = {
            "player_id": player_id,
            "player_name": name,
            "position": position,
            "market_value": value,
            "market_rank": row.get("market_rank", ""),
            "fit": "need" if need_priority >= 3 else "market_watch",
            "need": need,
            "availability": "available_in_current_league_roster_data",
            "why": (
                f"Available market value at {position}, a {need} team need."
                if need_field
                else "Available market value; positional fit is not configured."
            ),
            "evidence": (
                f"market_value={value}; market_rank={row.get('market_rank', 'unknown')}; "
                f"{need_field or 'position_fit'}={need}; identity={identity_note}"
            ),
            "risk": "Market board only; confirm draft eligibility and current news before acting.",
            "confidence": "medium",
            "source_trace": source_trace or "DynastyProcess values.csv",
        }
    return sorted(
        unique.values(),
        key=lambda row: (-NEED_PRIORITY.get(str(row.get("need", "")).lower(), 0), -_number(row.get("market_value")), _int(row.get("market_rank")) or 9999),
    )[:24]


def _build_trade_targets(
    rows: list[dict[str, Any]],
    my_roster_id: int,
    my_team_name: str,
) -> list[dict[str, Any]]:
    targets = []
    for row in rows:
        if str(row.get("action_label", "")) not in TARGET_LABELS:
            continue
        if _int(row.get("roster_id")) == my_roster_id or str(row.get("team_name", "")) == my_team_name:
            continue
        targets.append(
            {
                "player_id": str(row.get("player_id", "")),
                "player_name": row.get("player_name", "Unknown player"),
                "position": row.get("position", ""),
                "owner_team": row.get("team_name", ""),
                "action_label": row.get("action_label", ""),
                "consumer_label": row.get("consumer_label", "Target"),
                "action_score": row.get("action_score", ""),
                "why": row.get("why", "The action model identified a price/value mismatch."),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", "medium"),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return sorted(targets, key=lambda row: -_number(row.get("action_score")))[:12]


def _build_fades(
    rows: list[dict[str, Any]],
    my_roster_id: int,
    my_team_name: str,
) -> list[dict[str, Any]]:
    fades = []
    for row in rows:
        if str(row.get("action_label", "")) not in FADE_LABELS:
            continue
        owned = _int(row.get("roster_id")) == my_roster_id or str(row.get("team_name", "")) == my_team_name
        if not owned:
            continue
        fades.append(
            {
                "player_id": str(row.get("player_id", "")),
                "player_name": row.get("player_name", "Unknown player"),
                "position": row.get("position", ""),
                "market_value": row.get("market_value", ""),
                "projected_ppg": row.get("projected_ppg", ""),
                "why": row.get("why", "The action model identified timing or value risk."),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", "medium"),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return sorted(fades, key=lambda row: -_number(row.get("market_value")))[:12]


def _build_pick_leverage(
    rows: list[dict[str, Any]],
    value_rows: list[dict[str, Any]],
    tracked: list[dict[str, Any]],
    season: str,
    my_roster_id: int,
    drafted_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    value_map = {
        (str(row.get("pick_season", "")), str(row.get("round", ""))): _number(row.get("market_value"))
        for row in value_rows
        if _number(row.get("market_value")) > 0
    }
    tracked_map = {
        (str(row.get("pick_season", "")), str(row.get("round", ""))): row
        for row in tracked
    }
    season_number = _int(season)
    current_draft_has_picks = any(str(row.get("season", "")) == season for row in drafted_rows)
    minimum_pick_season = season_number + 1 if current_draft_has_picks and season_number else season_number
    output = []
    for row in rows:
        pick_season = str(row.get("pick_season", ""))
        if not pick_season.isdigit() or int(pick_season) < minimum_pick_season:
            continue
        round_no = str(row.get("round", ""))
        current_owner = _int(row.get("current_owner_roster_id"))
        original_owner = _int(row.get("original_roster_id"))
        if current_owner == my_roster_id:
            ownership_status = "owned_by_you"
        elif original_owner == my_roster_id:
            ownership_status = "your_original_pick_away"
        else:
            ownership_status = "other_pick"
        tracked_row = tracked_map.get((pick_season, round_no), {})
        external_value = value_map.get((pick_season, round_no), 0.0)
        market_value = external_value or _pick_curve(_int(round_no))
        value_source = "external_pick_value" if external_value else "internal_round_curve"
        evidence = (
            f"pick_season={pick_season}; round={round_no}; ownership={ownership_status}; "
            f"value_source={value_source}"
        )
        if tracked_row:
            evidence += f"; tracked_priority={tracked_row.get('priority', 'monitor')}"
        output.append(
            {
                "pick_season": pick_season,
                "round": round_no,
                "original_team": row.get("original_team", ""),
                "current_owner": row.get("current_owner", ""),
                "ownership_status": ownership_status,
                "priority": tracked_row.get("priority", "") if tracked_row else "",
                "note": tracked_row.get("note", "") if tracked_row else "",
                "market_value": round(market_value, 2),
                "value_source": value_source,
                "why": _pick_why(ownership_status, tracked_row),
                "evidence": evidence,
                "risk": "Pick range is unknown until the league draft order is set." if _int(round_no) <= 2 else "Later-round value is volatile.",
                "confidence": "medium" if external_value else "low",
                "source_trace": str(row.get("source_trace", "")) or "Sleeper traded-pick history; internal round curve",
            }
        )
    return sorted(
        output,
        key=lambda row: (0 if row["ownership_status"] != "other_pick" else 1, _int(row["pick_season"]), _int(row["round"])),
    )[:48]


def _pick_why(status: str, tracked: dict[str, Any]) -> str:
    if tracked:
        return str(tracked.get("note") or f"Tracked as {tracked.get('priority', 'monitor')}.")
    if status == "owned_by_you":
        return "Draft capital currently available to your team."
    if status == "your_original_pick_away":
        return "Your original pick is elsewhere; treat it as a reacquisition or leverage question."
    return "League pick context for trade valuation."


def _source_health(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": row.get("source", ""),
            "dataset": row.get("dataset", ""),
            "status": row.get("status", ""),
            "checked_at": row.get("checked_at", ""),
        }
        for row in rows
        if row.get("source")
    ]


def _current_rows(rows: list[dict[str, Any]], season: str, key: str) -> list[dict[str, Any]]:
    current = [row for row in rows if str(row.get("season", "")) == season]
    if current:
        return current
    latest = _latest_season(rows)
    if not latest:
        return rows
    return [row for row in rows if str(row.get("season", "")) == latest]


def _latest_season(rows: Iterable[dict[str, Any]]) -> str:
    seasons = [str(row.get("season", "")) for row in rows if str(row.get("season", "")).isdigit()]
    return str(max((int(value) for value in seasons), default=0)) if seasons else ""


def _team_name(rows: list[dict[str, Any]], roster_id: int, season: str) -> str:
    candidates = [row for row in rows if _int(row.get("roster_id")) == roster_id and str(row.get("season", "")) == season]
    if not candidates:
        candidates = [row for row in rows if _int(row.get("roster_id")) == roster_id]
    return str((candidates[0] if candidates else {}).get("team_name", ""))


def _first_matching(rows: list[dict[str, Any]], key: str, value: int) -> dict[str, Any]:
    return next((row for row in rows if _int(row.get(key)) == value), {})


def _name_key(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _int(value: Any) -> int:
    try:
        return int(float(value)) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _pick_curve(round_no: int) -> float:
    return {1: 55.0, 2: 28.0, 3: 14.0, 4: 7.0, 5: 3.0}.get(round_no, 2.0)
