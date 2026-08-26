"""Deterministic manager transaction lanes.

The manager dossier needs more than an all-time activity counter.  This module
keeps the historical transaction grain separate from the current market model,
then joins only identity-resolved players to the current horizon table.  The
result is an observed transaction lane, not a forecast of willingness or a
historical price reconstruction.
"""

from collections import defaultdict
from typing import Any

import pandas as pd


HORIZON_FIELDS = (
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
    "contender_fit_score",
    "rebuilder_fit_score",
)

HORIZON_FIELD_LABELS = {
    "next_game_market_score": "next_game",
    "rest_of_season_market_score": "rest_of_season",
    "dynasty_market_score": "dynasty",
    "career_projection_score": "career_window",
    "contender_fit_score": "contender_fit",
    "rebuilder_fit_score": "rebuilder_fit",
}

HORIZON_COVERAGE_COLUMNS = tuple(
    f"horizon_{direction}_{HORIZON_FIELD_LABELS[field]}_matches"
    for direction in ("acquired", "sold")
    for field in HORIZON_FIELDS
)


MANAGER_TRANSACTION_PREFERENCE_COLUMNS = [
    "owner_id",
    "roster_id",
    "team_name",
    "position_group",
    "trade_acquired_count",
    "waiver_acquired_count",
    "draft_acquired_count",
    "trade_sold_count",
    "waiver_sold_count",
    "acquired_count",
    "sold_count",
    "net_acquired_count",
    "unique_acquired_players",
    "unique_sold_players",
    "current_roster_acquired_count",
    "current_roster_sold_count",
    "seasons_observed",
    "last_observed_season",
    "last_observed_week",
    "acquired_next_game_market_score",
    "sold_next_game_market_score",
    "acquired_rest_of_season_market_score",
    "sold_rest_of_season_market_score",
    "acquired_dynasty_market_score",
    "sold_dynasty_market_score",
    "acquired_career_projection_score",
    "sold_career_projection_score",
    "acquired_contender_fit_score",
    "sold_contender_fit_score",
    "acquired_rebuilder_fit_score",
    "sold_rebuilder_fit_score",
    "acquired_minus_sold_next_game_delta",
    "acquired_minus_sold_rest_of_season_delta",
    "acquired_minus_sold_dynasty_delta",
    "acquired_minus_sold_career_delta",
    "acquired_minus_sold_contender_fit_delta",
    "acquired_minus_sold_rebuilder_fit_delta",
    "horizon_acquired_matches",
    "horizon_sold_matches",
    *HORIZON_COVERAGE_COLUMNS,
    "horizon_coverage_detail",
    "horizon_coverage",
    "transaction_read",
    "history_status",
    "confidence",
    "evidence",
    "source_trace",
]


def build_manager_transaction_preferences(
    manager_profiles_df: pd.DataFrame,
    player_history_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    players_df: pd.DataFrame | None = None,
    horizon_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build observed manager lanes from exact player transaction history.

    ``player_history_df`` is produced by the canonical Sleeper transaction
    normalizer and carries the resolved player identity method.  Historical
    rows are assigned to a manager through ``season + roster_id`` lineage from
    ``manager_profiles``.  A missing lineage or unresolved player identity is
    not guessed into another manager or position lane.

    Horizon values are explicitly current context: they describe the present
    market profile of identity-resolved players that appear in the historical
    acquired/sold set.  They are never presented as the value at the time of
    the original transaction.
    """

    empty = pd.DataFrame(columns=MANAGER_TRANSACTION_PREFERENCE_COLUMNS)
    if manager_profiles_df is None or manager_profiles_df.empty:
        return empty

    owner_lineage, current_managers = _manager_lineage(manager_profiles_df)
    positions = _player_positions(players_df, roster_players_df)
    current_players = _current_roster_players(roster_players_df)
    horizon_by_player = _horizon_map(horizon_df)
    states: dict[tuple[str, int, str], dict[str, Any]] = {}

    if player_history_df is None or player_history_df.empty:
        return empty

    for _, event in player_history_df.fillna("").iterrows():
        season = _text(event.get("season"))
        source_roster_id = _int(event.get("roster_id"))
        manager = owner_lineage.get((season, source_roster_id))
        if manager is None:
            # Current-roster fallback is safe only for rows with the same
            # roster ID; it does not use a display name as identity.
            manager = current_managers.get(source_roster_id)
        if manager is None:
            continue

        direction = _transaction_direction(event)
        if not direction:
            continue
        player_id = _text(event.get("player_id"))
        position = positions.get(player_id, "UNKNOWN") if player_id else "UNKNOWN"
        position_group = _position_group(position)
        key = (manager["owner_id"], manager["roster_id"], position_group)
        state = states.setdefault(key, _new_state(manager, position_group))
        state["seasons"].add(season) if season else None
        state["last_event"] = max(
            state["last_event"],
            (_int(season), _int(event.get("week"))),
        )
        if direction == "acquired":
            state["acquired_count"] += 1
            state["acquired_ids"].add(player_id) if player_id else None
            state["acquired_names"].add(_text(event.get("player_name"))) if _text(event.get("player_name")) else None
            _count_event(state, event, "acquired")
            if player_id in current_players.get(manager["roster_id"], set()):
                state["current_acquired_ids"].add(player_id)
            _append_horizon(state, "acquired", horizon_by_player.get(player_id))
        else:
            state["sold_count"] += 1
            state["sold_ids"].add(player_id) if player_id else None
            state["sold_names"].add(_text(event.get("player_name"))) if _text(event.get("player_name")) else None
            _count_event(state, event, "sold")
            if player_id in current_players.get(manager["roster_id"], set()):
                state["current_sold_ids"].add(player_id)
            _append_horizon(state, "sold", horizon_by_player.get(player_id))

    rows = [_finalize_state(state) for state in states.values()]
    if not rows:
        return empty
    return pd.DataFrame(rows, columns=MANAGER_TRANSACTION_PREFERENCE_COLUMNS).sort_values(
        ["roster_id", "position_group"],
        ascending=[True, True],
    ).reset_index(drop=True)


def _manager_lineage(manager_profiles_df: pd.DataFrame) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[int, dict[str, Any]]]:
    lineage: dict[tuple[str, int], dict[str, Any]] = {}
    current: dict[int, dict[str, Any]] = {}
    for _, row in manager_profiles_df.fillna("").iterrows():
        manager = {
            "owner_id": _text(row.get("owner_id")) or f"roster:{_int(row.get('roster_id'))}",
            "roster_id": _int(row.get("roster_id")),
            "team_name": _text(row.get("team_name")),
        }
        if not manager["roster_id"]:
            continue
        current[manager["roster_id"]] = manager
        for value in _split(row.get("roster_ids_by_season")):
            if ":" not in value:
                continue
            season, roster_id = value.split(":", 1)
            roster = _int(roster_id)
            if season.strip() and roster:
                lineage[(season.strip(), roster)] = manager
        seasons = _split(row.get("seasons_covered"))
        if seasons:
            for season in seasons:
                lineage.setdefault((season, manager["roster_id"]), manager)
    return lineage, current


def _player_positions(players_df: pd.DataFrame | None, roster_players_df: pd.DataFrame) -> dict[str, str]:
    positions: dict[str, str] = {}
    for frame in (players_df, roster_players_df):
        if frame is None or frame.empty:
            continue
        for _, row in frame.fillna("").iterrows():
            player_id = _text(row.get("player_id"))
            position = _text(row.get("position")).upper()
            if player_id and position and player_id not in positions:
                positions[player_id] = position
    return positions


def _current_roster_players(roster_players_df: pd.DataFrame) -> dict[int, set[str]]:
    if roster_players_df is None or roster_players_df.empty:
        return {}
    frame = roster_players_df.fillna("").copy()
    if "season" in frame.columns:
        seasons = pd.to_numeric(frame["season"], errors="coerce").dropna()
        if not seasons.empty:
            frame = frame[frame["season"].astype(str) == str(int(seasons.max()))]
    result: dict[int, set[str]] = defaultdict(set)
    for _, row in frame.iterrows():
        roster_id = _int(row.get("roster_id"))
        player_id = _text(row.get("player_id"))
        if roster_id and player_id:
            result[roster_id].add(player_id)
    return dict(result)


def _horizon_map(horizon_df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if horizon_df is None or horizon_df.empty:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for _, row in horizon_df.fillna("").iterrows():
        player_id = _text(row.get("player_id"))
        if player_id and player_id not in result:
            result[player_id] = row.to_dict()
    return result


def _new_state(manager: dict[str, Any], position_group: str) -> dict[str, Any]:
    return {
        **manager,
        "position_group": position_group,
        "trade_acquired_count": 0,
        "waiver_acquired_count": 0,
        "draft_acquired_count": 0,
        "trade_sold_count": 0,
        "waiver_sold_count": 0,
        "acquired_count": 0,
        "sold_count": 0,
        "acquired_ids": set(),
        "sold_ids": set(),
        "acquired_names": set(),
        "sold_names": set(),
        "current_acquired_ids": set(),
        "current_sold_ids": set(),
        "seasons": set(),
        "last_event": (0, 0),
        "horizon": {"acquired": defaultdict(list), "sold": defaultdict(list)},
        "horizon_counts": {"acquired": defaultdict(int), "sold": defaultdict(int)},
    }


def _count_event(state: dict[str, Any], event: pd.Series, direction: str) -> None:
    event_type = _text(event.get("event_type"))
    if event_type == "trade":
        state[f"trade_{direction}_count"] += 1
    elif event_type == "waiver_add" and direction == "acquired":
        state["waiver_acquired_count"] += 1
    elif event_type == "waiver_drop" and direction == "sold":
        state["waiver_sold_count"] += 1
    elif event_type == "draft_pick" and direction == "acquired":
        state["draft_acquired_count"] += 1


def _append_horizon(state: dict[str, Any], direction: str, horizon: dict[str, Any] | None) -> None:
    if not horizon:
        return
    for field in HORIZON_FIELDS:
        value = _number_or_none(horizon.get(field))
        if value is not None:
            state["horizon"][direction][field].append(value)
            state["horizon_counts"][direction][field] += 1


def _finalize_state(state: dict[str, Any]) -> dict[str, Any]:
    acquired = state["acquired_count"]
    sold = state["sold_count"]
    total = acquired + sold
    horizon_acquired = {field: _average(state["horizon"]["acquired"][field]) for field in HORIZON_FIELDS}
    horizon_sold = {field: _average(state["horizon"]["sold"][field]) for field in HORIZON_FIELDS}
    row: dict[str, Any] = {
        "owner_id": state["owner_id"],
        "roster_id": state["roster_id"],
        "team_name": state["team_name"],
        "position_group": state["position_group"],
        "trade_acquired_count": state["trade_acquired_count"],
        "waiver_acquired_count": state["waiver_acquired_count"],
        "draft_acquired_count": state["draft_acquired_count"],
        "trade_sold_count": state["trade_sold_count"],
        "waiver_sold_count": state["waiver_sold_count"],
        "acquired_count": acquired,
        "sold_count": sold,
        "net_acquired_count": acquired - sold,
        "unique_acquired_players": "; ".join(sorted(state["acquired_names"])),
        "unique_sold_players": "; ".join(sorted(state["sold_names"])),
        "current_roster_acquired_count": len(state["current_acquired_ids"]),
        "current_roster_sold_count": len(state["current_sold_ids"]),
        "seasons_observed": "; ".join(sorted(state["seasons"])),
        "last_observed_season": state["last_event"][0] or "",
        "last_observed_week": state["last_event"][1] or "",
    }
    for field in HORIZON_FIELDS:
        row[f"acquired_{field}"] = horizon_acquired[field]
        row[f"sold_{field}"] = horizon_sold[field]
    for field in HORIZON_FIELDS:
        short = field.removesuffix("_market_score").removesuffix("_score")
        row[f"acquired_minus_sold_{short}_delta"] = _delta(horizon_acquired[field], horizon_sold[field])
    acquired_matches = max((len(values) for values in state["horizon"]["acquired"].values()), default=0)
    sold_matches = max((len(values) for values in state["horizon"]["sold"].values()), default=0)
    coverage_counts = {
        direction: {
            HORIZON_FIELD_LABELS[field]: int(state["horizon_counts"][direction].get(field, 0))
            for field in HORIZON_FIELDS
        }
        for direction in ("acquired", "sold")
    }
    coverage_detail = "; ".join(
        f"{label}: acquired {coverage_counts['acquired'][label]}/{acquired}; sold {coverage_counts['sold'][label]}/{sold}"
        for label in HORIZON_FIELD_LABELS.values()
    )
    row.update(
        {
            "horizon_acquired_matches": acquired_matches,
            "horizon_sold_matches": sold_matches,
            **{
                f"horizon_{direction}_{label}_matches": count
                for direction, counts in coverage_counts.items()
                for label, count in counts.items()
            },
            "horizon_coverage_detail": coverage_detail,
            "horizon_coverage": f"acquired {acquired_matches}/{acquired}; sold {sold_matches}/{sold}",
            "transaction_read": _transaction_read(acquired, sold),
            "history_status": "supported" if total >= 4 else "sparse",
            "confidence": "high" if total >= 8 else "medium" if total >= 3 else "low",
            "evidence": (
                f"position_group={state['position_group']}; acquired={acquired}; sold={sold}; "
                f"unique_acquired={len(state['acquired_ids'])}; unique_sold={len(state['sold_ids'])}; "
                f"seasons={';'.join(sorted(state['seasons'])) or 'unknown'}; "
                f"current_roster_acquired={len(state['current_acquired_ids'])}; "
                f"current_roster_sold={len(state['current_sold_ids'])}; "
                "horizon values are current context for historically transacted players, not historical prices"
            ),
            "source_trace": "manager_profiles;player_transaction_history;players;roster_players"
            + (";player_horizon_market_scores" if acquired_matches or sold_matches else ""),
        }
    )
    return row


def _transaction_direction(event: pd.Series) -> str:
    event_type = _text(event.get("event_type"))
    direction = _text(event.get("direction")).lower()
    if event_type == "draft_pick" or direction.startswith("drafted pick"):
        return "acquired"
    if direction in {"acquired", "added"}:
        return "acquired"
    if direction in {"sold", "dropped"}:
        return "sold"
    return ""


def _position_group(position: str) -> str:
    if position in {"WR", "TE"}:
        return "PASS_CATCHER"
    if position in {"QB", "RB"}:
        return position
    return "UNKNOWN"


def _transaction_read(acquired: int, sold: int) -> str:
    if acquired > sold:
        return "observed acquisition lane"
    if sold > acquired:
        return "observed disposal lane"
    return "two-way observed lane"


def _average(values: list[float]) -> float | str:
    return round(sum(values) / len(values), 2) if values else ""


def _delta(left: float | str, right: float | str) -> float | str:
    if left in ("", None) or right in ("", None):
        return ""
    return round(float(left) - float(right), 2)


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _int(value: Any) -> int:
    try:
        if value in (None, "") or pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _number_or_none(value: Any) -> float | None:
    try:
        if value in (None, "") or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _split(value: Any) -> list[str]:
    return [part.strip() for part in _text(value).split(";") if part.strip()]
