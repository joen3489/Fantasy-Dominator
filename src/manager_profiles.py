from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from .utils import join_items


def build_manager_profiles(
    teams_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for _, team in teams_df.iterrows():
        roster_id = int(team["roster_id"])
        team_name = team.get("team_name", "")
        display_name = team.get("display_name", "")

        trade_rows = trades_df[
            (trades_df.get("team_a_roster_id") == roster_id) | (trades_df.get("team_b_roster_id") == roster_id)
        ] if not trades_df.empty else pd.DataFrame()

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

        waiver_rows = waivers_df[waivers_df.get("roster_id") == roster_id] if not waivers_df.empty else pd.DataFrame()
        bids = pd.to_numeric(waiver_rows.get("waiver_bid", pd.Series(dtype=float)), errors="coerce").fillna(0)
        roster = roster_players_df[roster_players_df.get("roster_id") == roster_id] if not roster_players_df.empty else pd.DataFrame()
        qb_count = int((roster.get("position") == "QB").sum()) if not roster.empty else 0
        rb_count = int((roster.get("position") == "RB").sum()) if not roster.empty else 0
        pass_catcher_count = int(roster.get("position").isin(["WR", "TE"]).sum()) if not roster.empty else 0

        rows.append(
            {
                "roster_id": roster_id,
                "display_name": display_name,
                "team_name": team_name,
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


def _split_items(value: Any) -> list[str]:
    if value is None or pd.isna(value) or value == "":
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _indicator(qb_count: int, rb_count: int, pass_catcher_count: int, firsts_in: int, firsts_out: int) -> str:
    if firsts_in > firsts_out and rb_count < 6:
        return "possible rebuilder"
    if firsts_out > firsts_in and qb_count >= 3:
        return "possible contender"
    if pass_catcher_count >= 14:
        return "pass-catcher depth"
    return "neutral"
