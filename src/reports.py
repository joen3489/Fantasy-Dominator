from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_weekly_report(
    output_path: Path,
    teams_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    manager_profiles_df: pd.DataFrame,
    pick_ownership_df: pd.DataFrame,
    my_roster_id: int | None,
    strategy_profile: dict | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    my_team = ""
    if my_roster_id is not None and not teams_df.empty:
        match = teams_df[teams_df["roster_id"] == my_roster_id]
        if not match.empty:
            my_team = str(match.iloc[0].get("team_name", ""))

    my_roster = roster_players_df[roster_players_df["roster_id"] == my_roster_id] if my_roster_id else pd.DataFrame()
    qb = _players_by_position(my_roster, ["QB"])
    rb = _players_by_position(my_roster, ["RB"])
    pass_catchers = _players_by_position(my_roster, ["WR", "TE"])
    churn = _churn_candidates(my_roster)
    recent_trades = trades_df.sort_values("created_datetime", ascending=False).head(8) if not trades_df.empty else pd.DataFrame()
    recent_waivers = waivers_df.sort_values(["week", "transaction_id"], ascending=False).head(12) if not waivers_df.empty else pd.DataFrame()

    likely_traders = manager_profiles_df.sort_values("total_trades", ascending=False).head(5) if not manager_profiles_df.empty else pd.DataFrame()
    pick_hoarders = manager_profiles_df.sort_values("future_1sts_acquired", ascending=False).head(5) if not manager_profiles_df.empty else pd.DataFrame()
    veteran_buyers = manager_profiles_df.sort_values("future_1sts_sold", ascending=False).head(5) if not manager_profiles_df.empty else pd.DataFrame()
    my_picks_elsewhere = pick_ownership_df[
        (pick_ownership_df["is_my_original_pick"] == True) & (pick_ownership_df["i_currently_own_it"] == False)
    ] if not pick_ownership_df.empty else pd.DataFrame()

    lines = [
        "# Weekly Hinkie Report",
        "",
        f"Team: {my_team or my_roster_id or 'Unknown'}",
        f"Strategy: {(strategy_profile or {}).get('name', 'Generic Sleeper team analysis')}",
        f"Direction: {(strategy_profile or {}).get('team_direction', 'not configured')}",
        f"Contention window: {(strategy_profile or {}).get('contention_window', 'not configured')}",
        "",
        "## My Roster Summary",
        "",
        f"- QB: {_join(qb)}",
        f"- RB: {_join(rb)}",
        f"- Pass catchers: {_join(pass_catchers)}",
        "",
        "## Churn / Drop Candidates",
        "",
        _bullet_list(churn),
        "",
        "## Shop Candidates",
        "",
        _configured_list((strategy_profile or {}).get("shop_quietly"))
        or "Review veteran or fragile bench players once external market values are added. Current first pass is structural, not value-ranked.",
        "",
        "## Recent Waiver Behavior",
        "",
        _waiver_lines(recent_waivers),
        "",
        "## Recent Trades",
        "",
        _trade_lines(recent_trades),
        "",
        "## Managers Most Likely To Trade",
        "",
        _profile_lines(likely_traders, "total_trades"),
        "",
        "## Managers Hoarding Picks",
        "",
        _profile_lines(pick_hoarders, "future_1sts_acquired"),
        "",
        "## Managers Buying Veterans / Spending Picks",
        "",
        _profile_lines(veteran_buyers, "future_1sts_sold"),
        "",
        "## Teams With Positional Needs",
        "",
        _needs_lines(manager_profiles_df),
        "",
        "## Suggested Trade Targets",
        "",
        "Add market values/projections next. First target pool should be teams with positional surplus and low trade friction from manager profile history.",
        "",
        "## Suggested Trade Partners",
        "",
        _partner_lines(manager_profiles_df),
        "",
        "## My Original Picks Held Elsewhere",
        "",
        _pick_lines(my_picks_elsewhere),
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _players_by_position(roster: pd.DataFrame, positions: list[str]) -> list[str]:
    if roster.empty:
        return []
    rows = roster[roster["position"].isin(positions)].sort_values(["position", "player_name"])
    return [f"{row.player_name} ({row.position}, {row.roster_status})" for row in rows.itertuples()]


def _churn_candidates(roster: pd.DataFrame) -> list[str]:
    if roster.empty:
        return []
    bench = roster[roster["roster_status"].isin(["bench", "reserve"])].copy()
    if bench.empty:
        return []
    position_order = {"K": 0, "DEF": 1, "TE": 2, "WR": 3, "RB": 4, "QB": 5}
    bench["pos_rank"] = bench["position"].map(position_order).fillna(9)
    rows = bench.sort_values(["pos_rank", "player_name"]).head(10)
    return [f"{row.player_name} ({row.position}, {row.roster_status})" for row in rows.itertuples()]


def _join(items: list[str]) -> str:
    return "; ".join(items) if items else "None found"


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None found"


def _waiver_lines(df: pd.DataFrame) -> str:
    if df.empty:
        return "- None found"
    return "\n".join(
        f"- Week {row.week}: {row.team_name} bid {row.waiver_bid} for {row.player_added or 'no add'} ({row.status})"
        for row in df.itertuples()
    )


def _trade_lines(df: pd.DataFrame) -> str:
    if df.empty:
        return "- None found"
    lines = []
    for row in df.itertuples():
        lines.append(
            f"- Week {row.week}: {row.team_a_name} received [{row.team_a_players_received or row.team_a_picks_received or 'nothing mapped'}]; "
            f"{row.team_b_name} received [{row.team_b_players_received or row.team_b_picks_received or 'nothing mapped'}]"
        )
    return "\n".join(lines)


def _profile_lines(df: pd.DataFrame, metric: str) -> str:
    if df.empty:
        return "- None found"
    return "\n".join(f"- {row.team_name}: {getattr(row, metric)}" for row in df.itertuples())


def _needs_lines(df: pd.DataFrame) -> str:
    if df.empty:
        return "- None found"
    lines = []
    for row in df.itertuples():
        needs = []
        if row.qb_count < 3:
            needs.append("QB")
        if row.rb_count < 6:
            needs.append("RB")
        if row.pass_catcher_count < 12:
            needs.append("pass catcher")
        if needs:
            lines.append(f"- {row.team_name}: {', '.join(needs)}")
    return "\n".join(lines) if lines else "- None obvious from roster counts"


def _partner_lines(df: pd.DataFrame) -> str:
    if df.empty:
        return "- None found"
    ranked = df.sort_values(["total_trades", "future_1sts_acquired"], ascending=False).head(5)
    return "\n".join(f"- {row.team_name}: {row.contender_rebuilder_indicator}" for row in ranked.itertuples())


def _pick_lines(df: pd.DataFrame) -> str:
    if df.empty:
        return "- None found"
    return "\n".join(
        f"- {row.pick_season} round {row.round}: currently owned by {row.current_owner}"
        for row in df.itertuples()
    )


def _configured_list(items: list[str] | None) -> str:
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items)
