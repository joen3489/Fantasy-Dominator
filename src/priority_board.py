from __future__ import annotations

from typing import Any

import pandas as pd


def build_today_priority_board(
    action_recommendations_df: pd.DataFrame,
    league_news_impact_df: pd.DataFrame,
    pick_ownership_df: pd.DataFrame,
    manager_behavior_signals_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Merges the four sources that used to render as separate Today's Board
    sub-sections (Action Board, Sell Windows, My/Trade Target News, Pick Alerts,
    Manager Angles) into one deduplicated, ranked list. action_recommendations
    already includes sell_window-labeled rows, so Sell Windows previously showed
    the same players a second time by re-filtering the same table -- this
    dedupes by (entity_type, entity_id), processing the highest-signal source
    (action recommendations) first so it wins any collision."""
    current_roster = _int((config.get("current_team") or {}).get("roster_id"))
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if action_recommendations_df is not None and not action_recommendations_df.empty:
        for _, row in action_recommendations_df.fillna("").iterrows():
            entity_id = str(row.get("player_id", ""))
            key = ("player", entity_id)
            if not entity_id or key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "item_type": row.get("action_label", "monitor"),
                    "item_type_label": row.get("consumer_label", "Monitor"),
                    "entity_type": "player",
                    "entity_id": entity_id,
                    "entity_name": row.get("player_name", ""),
                    "roster_id": row.get("roster_id", ""),
                    "team_name": row.get("team_name", ""),
                    "raw_priority": _num(row.get("action_score")),
                    "why": row.get("why", ""),
                    "evidence": row.get("evidence", ""),
                    "risk": row.get("risk", ""),
                    "confidence": row.get("confidence", ""),
                    "source_trace": row.get("source_trace", ""),
                }
            )

    if league_news_impact_df is not None and not league_news_impact_df.empty:
        for _, row in league_news_impact_df.fillna("").iterrows():
            entity_id = str(row.get("player_id", ""))
            key = ("player", entity_id)
            if not entity_id or key in seen:
                continue
            seen.add(key)
            own_roster = bool(current_roster and _int(row.get("roster_id")) == current_roster)
            items.append(
                {
                    "item_type": "news",
                    "item_type_label": "My Roster News" if own_roster else "Trade Target News",
                    "entity_type": "player",
                    "entity_id": entity_id,
                    "entity_name": row.get("player_name", ""),
                    "roster_id": row.get("roster_id", ""),
                    "team_name": row.get("team_name", ""),
                    "raw_priority": _news_priority(row, own_roster),
                    "why": row.get("impact_type", ""),
                    "evidence": row.get("evidence", ""),
                    "risk": row.get("risk", ""),
                    "confidence": row.get("confidence", ""),
                    "source_trace": row.get("source_trace", ""),
                }
            )

    if pick_ownership_df is not None and not pick_ownership_df.empty:
        for _, row in pick_ownership_df.fillna("").iterrows():
            if not (_truthy(row.get("is_my_original_pick")) and not _truthy(row.get("i_currently_own_it"))):
                continue
            entity_id = f"{row.get('pick_season', '')}-{row.get('round', '')}-{row.get('original_roster_id', '')}"
            key = ("pick", entity_id)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "item_type": "pick_alert",
                    "item_type_label": "Pick Alert",
                    "entity_type": "pick",
                    "entity_id": entity_id,
                    "entity_name": f"{row.get('pick_season', '')} Round {row.get('round', '')}",
                    "roster_id": row.get("current_owner_roster_id", ""),
                    "team_name": row.get("current_owner", ""),
                    "raw_priority": 55.0,
                    "why": f"Your original {row.get('pick_season', '')} round {row.get('round', '')} pick is now owned by {row.get('current_owner', '')}.",
                    "evidence": f"original_owner={row.get('original_team', '')}; current_owner={row.get('current_owner', '')}",
                    "risk": "",
                    "confidence": "high",
                    "source_trace": "pick_ownership",
                }
            )

    if manager_behavior_signals_df is not None and not manager_behavior_signals_df.empty:
        for _, row in manager_behavior_signals_df.fillna("").iterrows():
            roster_id = _int(row.get("roster_id"))
            if current_roster and roster_id == current_roster:
                continue
            entity_id = str(roster_id)
            key = ("manager", entity_id)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "item_type": "manager_angle",
                    "item_type_label": "Manager Angle",
                    "entity_type": "manager",
                    "entity_id": entity_id,
                    "entity_name": row.get("team_name", ""),
                    "roster_id": roster_id,
                    "team_name": row.get("team_name", ""),
                    "raw_priority": _num(row.get("trade_activity_score")) * 0.4,
                    "why": f"{row.get('team_name', '')} profiles as {row.get('plain_language_label', '')}.",
                    "evidence": row.get("evidence", ""),
                    "risk": "",
                    "confidence": "medium",
                    "source_trace": "manager_behavior_signals",
                }
            )

    board = pd.DataFrame(items, columns=_priority_board_columns())
    if board.empty:
        return board
    # Percentile-rank the raw priority values across the WHOLE combined pool rather than
    # hand-tuning cross-type weights (action_score, trade_activity_score, and the flat
    # pick-alert constant all live on different natural scales) -- same self-calibrating
    # approach as the manager behavior score fix, so priority is always relative to this
    # week's actual candidate pool instead of magic numbers tuned for one snapshot.
    board["priority_score"] = _percentile(board["raw_priority"])
    board = board[_priority_board_output_columns()]
    return board.sort_values("priority_score", ascending=False).reset_index(drop=True)


def _news_priority(row: pd.Series, own_roster: bool) -> float:
    base = 40.0 if own_roster else 25.0
    impact_type = str(row.get("impact_type", ""))
    if impact_type in {"injury_risk", "market_heat"}:
        base += 20.0
    elif impact_type in {"role_or_value_change", "sell_pressure"}:
        base += 10.0
    return base


def _percentile(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    return (series.rank(pct=True, method="average").fillna(0) * 100).round().astype(int)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


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


def _priority_board_columns() -> list[str]:
    return [
        "item_type",
        "item_type_label",
        "entity_type",
        "entity_id",
        "entity_name",
        "roster_id",
        "team_name",
        "why",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
        "raw_priority",
    ]


def _priority_board_output_columns() -> list[str]:
    return [
        "item_type",
        "item_type_label",
        "entity_type",
        "entity_id",
        "entity_name",
        "roster_id",
        "team_name",
        "priority_score",
        "why",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    ]
