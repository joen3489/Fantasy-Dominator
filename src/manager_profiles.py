from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from .utils import join_items


MANAGER_SEASON_HISTORY_COLUMNS = [
    "owner_id",
    "season",
    "roster_id",
    "team_name",
    "trades",
    "waiver_claims",
    "faab_spent",
    "transaction_count",
    "players_acquired",
    "players_sold",
    "picks_acquired",
    "picks_sold",
    "trade_partners",
    "roster_player_count",
    "qb_count",
    "rb_count",
    "pass_catcher_count",
    "source_trace",
    "evidence",
]


def build_manager_season_history(
    teams_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build an auditable manager-by-season activity ledger.

    ``manager_profiles`` is intentionally a cross-season summary. This table
    preserves the per-season grain needed to tell whether a tendency is recent
    or merely accumulated over a long league history. It uses Sleeper roster
    IDs for identity and keeps team names as labels only.
    """

    states: dict[tuple[str, int], dict[str, Any]] = {}

    def ensure_state(season: Any, roster_id: Any, team_name: Any = "", owner_id: Any = "") -> dict[str, Any] | None:
        season_key = str(season or "").strip()
        roster_key = _int(roster_id)
        if not season_key or not roster_key:
            return None
        key = (season_key, roster_key)
        if key not in states:
            states[key] = {
                "owner_id": str(owner_id or ""),
                "season": season_key,
                "roster_id": roster_key,
                "team_name": str(team_name or ""),
                "trades": 0,
                "waiver_claims": 0,
                "faab_spent": 0.0,
                "transaction_count": 0,
                "players_acquired": [],
                "players_sold": [],
                "picks_acquired": [],
                "picks_sold": [],
                "trade_partners": Counter(),
                "roster_player_count": 0,
                "qb_count": 0,
                "rb_count": 0,
                "pass_catcher_count": 0,
            }
        state = states[key]
        if not state["team_name"] and str(team_name or ""):
            state["team_name"] = str(team_name)
        if not state["owner_id"] and str(owner_id or ""):
            state["owner_id"] = str(owner_id)
        return state

    # Seed every historical roster identity, including quiet seasons with no
    # transactions. This prevents absence of activity from looking like absent
    # history and gives the dossier a complete denominator.
    for _, team in teams_df.fillna("").iterrows():
        ensure_state(team.get("season"), team.get("roster_id"), team.get("team_name"), team.get("owner_id"))

    for _, trade in trades_df.fillna("").iterrows():
        season = trade.get("season")
        for side, other_side in (("a", "b"), ("b", "a")):
            state = ensure_state(
                season,
                trade.get(f"team_{side}_roster_id"),
                trade.get(f"team_{side}_name"),
            )
            if state is None:
                continue
            state["trades"] += 1
            state["transaction_count"] += 1
            partner = str(trade.get(f"team_{other_side}_name") or "").strip()
            if partner:
                state["trade_partners"][partner] += 1
            state["players_acquired"].extend(_split_items(trade.get(f"team_{side}_players_received")))
            state["players_sold"].extend(_split_items(trade.get(f"team_{other_side}_players_received")))
            state["picks_acquired"].extend(_split_items(trade.get(f"team_{side}_picks_received")))
            state["picks_sold"].extend(_split_items(trade.get(f"team_{other_side}_picks_received")))

    for _, waiver in waivers_df.fillna("").iterrows():
        state = ensure_state(waiver.get("season"), waiver.get("roster_id"), waiver.get("team_name"))
        if state is None:
            continue
        state["waiver_claims"] += 1
        state["transaction_count"] += 1
        state["faab_spent"] += _numeric(waiver.get("waiver_bid"))
        added = str(waiver.get("player_added") or "").strip()
        dropped = str(waiver.get("player_dropped") or "").strip()
        if added:
            state["players_acquired"].append(added)
        if dropped:
            state["players_sold"].append(dropped)

    for _, player in roster_players_df.fillna("").iterrows():
        state = ensure_state(player.get("season"), player.get("roster_id"), player.get("team_name"), player.get("owner_id"))
        if state is None:
            continue
        state["roster_player_count"] += 1
        position = str(player.get("position") or "").upper()
        if position == "QB":
            state["qb_count"] += 1
        elif position == "RB":
            state["rb_count"] += 1
        elif position in {"WR", "TE"}:
            state["pass_catcher_count"] += 1

    rows: list[dict[str, Any]] = []
    for state in sorted(states.values(), key=lambda value: (_numeric(value["season"]), value["roster_id"])):
        partners = "; ".join(
            f"{name}:{count}" for name, count in state["trade_partners"].most_common(8)
        )
        evidence = (
            f"season={state['season']}; roster_id={state['roster_id']}; trades={state['trades']}; "
            f"waiver_claims={state['waiver_claims']}; faab_spent={round(state['faab_spent'], 2)}; "
            f"roster_players={state['roster_player_count']}"
        )
        rows.append(
            {
                "owner_id": _identifier_value(state["owner_id"]),
                "season": _identifier_value(state["season"]),
                "roster_id": state["roster_id"],
                "team_name": state["team_name"],
                "trades": state["trades"],
                "waiver_claims": state["waiver_claims"],
                "faab_spent": round(state["faab_spent"], 2),
                "transaction_count": state["transaction_count"],
                "players_acquired": join_items(dict.fromkeys(state["players_acquired"])),
                "players_sold": join_items(dict.fromkeys(state["players_sold"])),
                "picks_acquired": join_items(dict.fromkeys(state["picks_acquired"])),
                "picks_sold": join_items(dict.fromkeys(state["picks_sold"])),
                "trade_partners": partners,
                "roster_player_count": state["roster_player_count"],
                "qb_count": state["qb_count"],
                "rb_count": state["rb_count"],
                "pass_catcher_count": state["pass_catcher_count"],
                "source_trace": "teams;trades;waivers;roster_players",
                "evidence": evidence,
            }
        )
    return pd.DataFrame(rows, columns=MANAGER_SEASON_HISTORY_COLUMNS)


def build_manager_profiles(
    teams_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if teams_df.empty:
        return pd.DataFrame(rows)

    latest_teams = _latest_teams(teams_df)
    history = _manager_history(teams_df)

    for _, team in latest_teams.iterrows():
        roster_id = int(team["roster_id"])
        owner_id = str(team.get("owner_id", "")) or f"roster:{roster_id}"
        team_name = team.get("team_name", "")
        display_name = team.get("display_name", "")
        manager_rows = history.get(owner_id, pd.DataFrame([team]))
        roster_pairs = {
            (str(row.get("season", "")), int(row.get("roster_id")))
            for _, row in manager_rows.iterrows()
            if row.get("roster_id", "") != ""
        }

        trade_rows = _trade_rows_for_roster_history(trades_df, roster_pairs)

        seasons = Counter()
        partners = Counter()
        players_acquired: list[str] = []
        players_sold: list[str] = []
        picks_acquired: list[str] = []
        picks_sold: list[str] = []
        future_1sts_acquired = future_1sts_sold = 0
        future_2nds_acquired = future_2nds_sold = 0

        for _, trade in trade_rows.iterrows():
            seasons[str(trade.get("season", ""))] += 1
            is_a = int(trade.get("team_a_roster_id")) == roster_id
            own_prefix = "team_a" if is_a else "team_b"
            other_prefix = "team_b" if is_a else "team_a"
            partners[str(trade.get(f"{other_prefix}_name", ""))] += 1
            players_acquired.extend(_split_items(trade.get(f"{own_prefix}_players_received", "")))
            players_sold.extend(_split_items(trade.get(f"{other_prefix}_players_received", "")))
            own_picks = _split_items(trade.get(f"{own_prefix}_picks_received", ""))
            other_picks = _split_items(trade.get(f"{other_prefix}_picks_received", ""))
            picks_acquired.extend(own_picks)
            picks_sold.extend(other_picks)
            future_1sts_acquired += sum(" R1 " in f" {pick} " for pick in own_picks)
            future_1sts_sold += sum(" R1 " in f" {pick} " for pick in other_picks)
            future_2nds_acquired += sum(" R2 " in f" {pick} " for pick in own_picks)
            future_2nds_sold += sum(" R2 " in f" {pick} " for pick in other_picks)

        waiver_rows = _waiver_rows_for_roster_history(waivers_df, roster_pairs)
        bids = pd.to_numeric(waiver_rows.get("waiver_bid", pd.Series(dtype=float)), errors="coerce").fillna(0)
        roster = roster_players_df[
            (roster_players_df.get("roster_id") == roster_id)
            & (roster_players_df.get("season").astype(str) == str(team.get("season", "")))
        ] if not roster_players_df.empty and "season" in roster_players_df else roster_players_df[roster_players_df.get("roster_id") == roster_id] if not roster_players_df.empty else pd.DataFrame()
        qb_count = int((roster.get("position") == "QB").sum()) if not roster.empty else 0
        rb_count = int((roster.get("position") == "RB").sum()) if not roster.empty else 0
        pass_catcher_count = int(roster.get("position").isin(["WR", "TE"]).sum()) if not roster.empty else 0

        rows.append(
            {
                "owner_id": owner_id,
                "roster_id": roster_id,
                "display_name": display_name,
                "team_name": team_name,
                "seasons_covered": join_items(sorted({str(row.get("season", "")) for _, row in manager_rows.iterrows() if str(row.get("season", ""))})),
                "roster_ids_by_season": join_items(
                    f"{row.get('season')}:{row.get('roster_id')}" for _, row in manager_rows.iterrows()
                ),
                "team_names_by_season": join_items(
                    f"{row.get('season')}:{row.get('team_name')}" for _, row in manager_rows.iterrows()
                ),
                "total_trades": len(trade_rows),
                "trades_by_season": "; ".join(f"{season}:{count}" for season, count in seasons.items()),
                "players_acquired": join_items(players_acquired),
                "players_sold": join_items(players_sold),
                "picks_acquired": join_items(picks_acquired),
                "picks_sold": join_items(picks_sold),
                "future_1sts_acquired": future_1sts_acquired,
                "future_1sts_sold": future_1sts_sold,
                "future_2nds_acquired": future_2nds_acquired,
                "future_2nds_sold": future_2nds_sold,
                "faab_spent_on_waivers": int(bids.sum()) if not bids.empty else 0,
                "number_of_waiver_claims": len(waiver_rows),
                "average_waiver_bid": round(float(bids.mean()), 2) if not bids.empty else 0,
                "max_waiver_bid": int(bids.max()) if not bids.empty else 0,
                "most_common_transaction_partners": "; ".join(
                    f"{name}:{count}" for name, count in partners.most_common(3) if name
                ),
                "qb_count": qb_count,
                "rb_count": rb_count,
                "pass_catcher_count": pass_catcher_count,
                "contender_rebuilder_indicator": _indicator(qb_count, rb_count, pass_catcher_count, future_1sts_acquired, future_1sts_sold),
                "notes": "",
            }
        )

    return pd.DataFrame(rows)


def _latest_teams(teams_df: pd.DataFrame) -> pd.DataFrame:
    frame = teams_df.fillna("").copy()
    frame["_season_sort"] = pd.to_numeric(frame.get("season", pd.Series(dtype=str)), errors="coerce").fillna(0)
    frame["_owner_key"] = frame.get("owner_id", pd.Series(dtype=str)).astype(str)
    frame.loc[frame["_owner_key"] == "", "_owner_key"] = frame["roster_id"].astype(str).map(lambda value: f"roster:{value}")
    return frame.sort_values("_season_sort").drop_duplicates("_owner_key", keep="last").drop(columns=["_season_sort", "_owner_key"])


def _manager_history(teams_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frame = teams_df.fillna("").copy()
    frame["_owner_key"] = frame.get("owner_id", pd.Series(dtype=str)).astype(str)
    frame.loc[frame["_owner_key"] == "", "_owner_key"] = frame["roster_id"].astype(str).map(lambda value: f"roster:{value}")
    return {str(owner_id): group.drop(columns=["_owner_key"]) for owner_id, group in frame.groupby("_owner_key")}


def _trade_rows_for_roster_history(trades_df: pd.DataFrame, roster_pairs: set[tuple[str, int]]) -> pd.DataFrame:
    if trades_df.empty or not roster_pairs:
        return pd.DataFrame()
    mask = []
    for _, trade in trades_df.fillna("").iterrows():
        season = str(trade.get("season", ""))
        mask.append(
            (season, _int(trade.get("team_a_roster_id"))) in roster_pairs
            or (season, _int(trade.get("team_b_roster_id"))) in roster_pairs
        )
    return trades_df[mask]


def _waiver_rows_for_roster_history(waivers_df: pd.DataFrame, roster_pairs: set[tuple[str, int]]) -> pd.DataFrame:
    if waivers_df.empty or not roster_pairs:
        return pd.DataFrame()
    mask = []
    for _, waiver in waivers_df.fillna("").iterrows():
        mask.append((str(waiver.get("season", "")), _int(waiver.get("roster_id"))) in roster_pairs)
    return waivers_df[mask]


def _split_items(value: Any) -> list[str]:
    if value is None or pd.isna(value) or value == "":
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _numeric(value: Any) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _identifier_value(value: Any) -> Any:
    """Keep numeric Sleeper IDs stable across CSV, JSON, and shell rebuilds."""

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = int(text)
    except (TypeError, ValueError):
        return text
    return number if str(number) == text else text


def _indicator(qb_count: int, rb_count: int, pass_catcher_count: int, firsts_in: int, firsts_out: int) -> str:
    if firsts_in > firsts_out and rb_count < 6:
        return "possible rebuilder"
    if firsts_out > firsts_in and qb_count >= 3:
        return "possible contender"
    if pass_catcher_count >= 14:
        return "pass-catcher depth"
    return "neutral"


def _int(value: Any) -> int:
    try:
        if value in ("", None) or pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0
