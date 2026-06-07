from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd


PASS_CATCHERS = {"WR", "TE"}


def build_economic_tables(
    teams_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    pick_ownership_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    manager_profiles_df: pd.DataFrame,
    player_market_values_df: pd.DataFrame,
    pick_market_values_df: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    inventory = build_team_asset_inventory(roster_players_df, pick_ownership_df, player_market_values_df, pick_market_values_df, config)
    event_log = build_manager_event_log(teams_df, trades_df, waivers_df)
    needs = build_team_needs_matrix(teams_df, roster_players_df, pick_ownership_df)
    behavior = build_manager_behavior_signals(teams_df, trades_df, waivers_df, manager_profiles_df, roster_players_df)
    valuation_profiles = build_manager_valuation_profiles(teams_df, manager_profiles_df, roster_players_df)
    liquidity = build_liquidity_scores(inventory, needs)
    gaps = build_asset_market_gaps(inventory, needs, behavior, config)
    opportunities = build_opportunity_board(gaps, behavior, config)
    return {
        "team_asset_inventory": inventory,
        "manager_event_log": event_log,
        "team_needs_matrix": needs,
        "manager_behavior_signals": behavior,
        "manager_valuation_profiles": valuation_profiles,
        "liquidity_scores": liquidity,
        "asset_market_gaps": gaps,
        "opportunity_board": opportunities,
    }


def build_manager_event_log(teams_df: pd.DataFrame, trades_df: pd.DataFrame, waivers_df: pd.DataFrame) -> pd.DataFrame:
    team_names = {int(row["roster_id"]): row.get("team_name", "") for _, row in teams_df.iterrows() if not pd.isna(row.get("roster_id"))}
    rows: list[dict[str, Any]] = []

    for _, trade in trades_df.iterrows():
        for side in ("a", "b"):
            roster_id = _int(trade.get(f"team_{side}_roster_id"))
            other_side = "b" if side == "a" else "a"
            rows.append(
                {
                    "event_type": "trade",
                    "week": trade.get("week", ""),
                    "created_datetime": trade.get("created_datetime", ""),
                    "transaction_id": trade.get("transaction_id", ""),
                    "roster_id": roster_id,
                    "team_name": trade.get(f"team_{side}_name", "") or team_names.get(roster_id, ""),
                    "counterparty": trade.get(f"team_{other_side}_name", ""),
                    "players_in": trade.get(f"team_{side}_players_received", ""),
                    "picks_in": trade.get(f"team_{side}_picks_received", ""),
                    "faab_in": trade.get(f"team_{side}_faab_received", ""),
                    "players_out": trade.get(f"team_{other_side}_players_received", ""),
                    "picks_out": trade.get(f"team_{other_side}_picks_received", ""),
                    "faab_out": trade.get(f"team_{other_side}_faab_received", ""),
                    "evidence": "Sleeper trade transaction",
                }
            )

    for _, waiver in waivers_df.iterrows():
        roster_id = _int(waiver.get("roster_id"))
        rows.append(
            {
                "event_type": "waiver",
                "week": waiver.get("week", ""),
                "created_datetime": "",
                "transaction_id": waiver.get("transaction_id", ""),
                "roster_id": roster_id,
                "team_name": waiver.get("team_name", "") or team_names.get(roster_id, ""),
                "counterparty": "league waiver market",
                "players_in": waiver.get("player_added", ""),
                "picks_in": "",
                "faab_in": "",
                "players_out": waiver.get("player_dropped", ""),
                "picks_out": "",
                "faab_out": waiver.get("waiver_bid", ""),
                "evidence": waiver.get("failure_reason", "") or "Sleeper waiver transaction",
            }
        )

    return pd.DataFrame(rows, columns=_manager_event_columns()).sort_values(["week", "event_type", "team_name"])


def build_team_asset_inventory(
    roster_players_df: pd.DataFrame,
    pick_ownership_df: pd.DataFrame,
    player_market_values_df: pd.DataFrame,
    pick_market_values_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    player_values = _player_value_map(player_market_values_df)
    pick_values = _pick_value_map(pick_market_values_df)
    rows: list[dict[str, Any]] = []

    for _, player in roster_players_df.iterrows():
        position = str(player.get("position", ""))
        age = _num(player.get("age"))
        market = player_values.get(str(player.get("player_id", ""))) or player_values.get(str(player.get("player_name", "")).lower())
        market_value = _num(market.get("market_value")) if market else _proxy_player_value(position, age, str(player.get("roster_status", "")))
        source_trace = market.get("source_trace", "internal_proxy_player_value") if market else "internal_proxy_player_value"
        rows.append(
            {
                "roster_id": player.get("roster_id", ""),
                "team_name": player.get("team_name", ""),
                "asset_type": "player",
                "asset_id": player.get("player_id", ""),
                "asset_name": player.get("player_name", ""),
                "position": position,
                "age": age,
                "market_value": round(market_value, 2),
                "liquidity_tier": _liquidity_tier(position, age, market_value, "player"),
                "timeline_fit": _timeline_fit(position, age, config),
                "source_trace": source_trace,
            }
        )

    for _, pick in pick_ownership_df.iterrows():
        round_no = _int(pick.get("round"))
        label = f"{pick.get('pick_season', '')} R{round_no} {pick.get('original_team', '')}"
        market_value = pick_values.get((str(pick.get("pick_season", "")), str(round_no))) or _proxy_pick_value(round_no)
        rows.append(
            {
                "roster_id": pick.get("current_owner_roster_id", ""),
                "team_name": pick.get("current_owner", ""),
                "asset_type": "pick",
                "asset_id": f"{pick.get('pick_season', '')}-{round_no}-{pick.get('original_roster_id', '')}",
                "asset_name": label,
                "position": "PICK",
                "age": "",
                "market_value": round(_num(market_value), 2),
                "liquidity_tier": _liquidity_tier("PICK", 0, _num(market_value), "pick"),
                "timeline_fit": "strong_rebuild_fit",
                "source_trace": "dynastyprocess_pick_value_or_internal_curve",
            }
        )

    return pd.DataFrame(rows, columns=_inventory_columns()).sort_values(["roster_id", "asset_type", "market_value"], ascending=[True, True, False])


def build_team_needs_matrix(teams_df: pd.DataFrame, roster_players_df: pd.DataFrame, pick_ownership_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, team in teams_df.iterrows():
        roster_id = int(team.get("roster_id"))
        roster = roster_players_df[roster_players_df.get("roster_id") == roster_id] if not roster_players_df.empty else pd.DataFrame()
        positions = roster.get("position", pd.Series(dtype=str))
        qb = int((positions == "QB").sum())
        rb = int((positions == "RB").sum())
        wr = int((positions == "WR").sum())
        te = int((positions == "TE").sum())
        picks = pick_ownership_df[pick_ownership_df.get("current_owner_roster_id") == roster_id] if not pick_ownership_df.empty else pd.DataFrame()
        firsts = int((picks.get("round", pd.Series(dtype=int)).astype(str) == "1").sum()) if not picks.empty else 0
        rows.append(
            {
                "roster_id": roster_id,
                "team_name": team.get("team_name", ""),
                "qb_count": qb,
                "rb_count": rb,
                "wr_count": wr,
                "te_count": te,
                "pass_catcher_count": wr + te,
                "future_firsts_owned": firsts,
                "need_qb": _need(qb, 3),
                "need_rb": _need(rb, 7),
                "need_pass_catcher": _need(wr + te, 13),
                "need_picks": _need(firsts, 2),
                "team_shape": _team_shape(qb, rb, wr + te, firsts),
            }
        )
    return pd.DataFrame(rows)


def build_manager_behavior_signals(
    teams_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    manager_profiles_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, team in teams_df.iterrows():
        roster_id = int(team.get("roster_id"))
        profile = _row_for(manager_profiles_df, "roster_id", roster_id)
        trade_count = _int(profile.get("total_trades", 0))
        firsts_in = _int(profile.get("future_1sts_acquired", 0))
        firsts_out = _int(profile.get("future_1sts_sold", 0))
        faab = _int(profile.get("faab_spent_on_waivers", 0))
        claims = _int(profile.get("number_of_waiver_claims", 0))
        roster = roster_players_df[roster_players_df.get("roster_id") == roster_id] if not roster_players_df.empty else pd.DataFrame()
        pos_counts = Counter(roster.get("position", pd.Series(dtype=str)))
        rows.append(
            {
                "roster_id": roster_id,
                "team_name": team.get("team_name", ""),
                "trade_activity_score": min(100, trade_count * 18),
                "pick_buyer_score": min(100, firsts_in * 35),
                "pick_seller_score": min(100, firsts_out * 35),
                "faab_aggression_score": min(100, faab + claims * 8),
                "waiver_activity_score": min(100, claims * 12),
                "rb_appetite_score": min(100, int(pos_counts.get("RB", 0)) * 9),
                "pass_catcher_appetite_score": min(100, int(pos_counts.get("WR", 0) + pos_counts.get("TE", 0)) * 6),
                "plain_language_label": _behavior_label(trade_count, firsts_in, firsts_out, faab, claims),
                "evidence": _behavior_evidence(trade_count, firsts_in, firsts_out, faab, claims),
            }
        )
    return pd.DataFrame(rows)


def build_manager_valuation_profiles(
    teams_df: pd.DataFrame,
    manager_profiles_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    current_teams = _latest_teams(teams_df)
    for _, team in current_teams.iterrows():
        roster_id = int(team.get("roster_id"))
        profile = _row_for(manager_profiles_df, "roster_id", roster_id)
        roster = roster_players_df[roster_players_df.get("roster_id") == roster_id] if not roster_players_df.empty else pd.DataFrame()
        pos_counts = Counter(roster.get("position", pd.Series(dtype=str)))
        trade_count = _int(profile.get("total_trades", 0))
        firsts_in = _int(profile.get("future_1sts_acquired", 0))
        firsts_out = _int(profile.get("future_1sts_sold", 0))
        faab = _int(profile.get("faab_spent_on_waivers", 0))
        claims = _int(profile.get("number_of_waiver_claims", 0))
        base_evidence = _behavior_evidence(trade_count, firsts_in, firsts_out, faab, claims)
        rows.extend(
            [
                _valuation_row(team, "pick", "PICK", firsts_in * 28 - firsts_out * 18, trade_count + firsts_in + firsts_out, "pick accumulator", base_evidence),
                _valuation_row(team, "pick", "PICK", firsts_out * 42 - firsts_in * 12, trade_count + firsts_in + firsts_out, "pick seller", base_evidence),
                _valuation_row(team, "player", "PASS_CATCHER", int(pos_counts.get("WR", 0) + pos_counts.get("TE", 0)) * 5 + trade_count * 4, int(pos_counts.get("WR", 0) + pos_counts.get("TE", 0)) + trade_count, "pass-catcher collector", f"{base_evidence}; pass_catchers={int(pos_counts.get('WR', 0) + pos_counts.get('TE', 0))}"),
                _valuation_row(team, "player", "RB", int(pos_counts.get("RB", 0)) * 7 + firsts_out * 9, int(pos_counts.get("RB", 0)) + firsts_out, "RB production buyer", f"{base_evidence}; rb_count={int(pos_counts.get('RB', 0))}"),
                _valuation_row(team, "waiver", "DEPTH", claims * 18 + faab * 0.6, claims, "waiver aggressor", base_evidence),
                _valuation_row(team, "roster", "DEPTH", trade_count * 10 + claims * 6, trade_count + claims, "depth churner", base_evidence),
            ]
        )
    return pd.DataFrame(rows, columns=_manager_valuation_columns()).sort_values(
        ["roster_id", "preference_score"],
        ascending=[True, False],
    )


def build_liquidity_scores(inventory_df: pd.DataFrame, needs_df: pd.DataFrame) -> pd.DataFrame:
    demand_by_position = _demand_by_position(needs_df)
    rows: list[dict[str, Any]] = []
    for _, asset in inventory_df.iterrows():
        position = str(asset.get("position", ""))
        market_value = _num(asset.get("market_value"))
        model_value = _model_value(market_value)
        score = min(100, model_value / 2 + demand_by_position.get(position, 5) * 7)
        if asset.get("asset_type") == "pick":
            score += 20
        rows.append(
            {
                "roster_id": asset.get("roster_id", ""),
                "team_name": asset.get("team_name", ""),
                "asset_type": asset.get("asset_type", ""),
                "asset_name": asset.get("asset_name", ""),
                "position": position,
                "market_value": round(market_value, 2),
                "liquidity_score": round(min(100, score), 2),
                "liquidity_tier": _score_tier(score),
                "demand_signal": demand_by_position.get(position, 0),
                "source_trace": asset.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows).sort_values("liquidity_score", ascending=False)


def build_asset_market_gaps(
    inventory_df: pd.DataFrame,
    needs_df: pd.DataFrame,
    behavior_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    current_team = (config.get("current_team") or {}).get("roster_id")
    current_team = _int(current_team) if current_team not in ("", None) else None
    rows: list[dict[str, Any]] = []
    for _, asset in inventory_df.iterrows():
        roster_id = _int(asset.get("roster_id"))
        needs = _row_for(needs_df, "roster_id", roster_id)
        behavior = _row_for(behavior_df, "roster_id", roster_id)
        value = _num(asset.get("market_value"))
        model_value = _model_value(value)
        position = str(asset.get("position", ""))
        scarcity = _scarcity_bonus(position, needs)
        behavior_gap = (_num(behavior.get("pick_seller_score")) if asset.get("asset_type") == "pick" else _num(behavior.get("trade_activity_score"))) / 10
        gap_score = round(model_value * 0.45 + scarcity + behavior_gap, 2)
        opportunity_type = "sell_candidate" if current_team == roster_id and model_value >= 35 else "buy_low_target"
        if asset.get("asset_type") == "pick" and current_team != roster_id:
            opportunity_type = "pick_reacquisition_target"
        rows.append(
            {
                "target_roster_id": roster_id,
                "target_team": asset.get("team_name", ""),
                "asset_type": asset.get("asset_type", ""),
                "asset_name": asset.get("asset_name", ""),
                "position": position,
                "market_value": value,
                "market_gap_score": gap_score,
                "opportunity_type": opportunity_type,
                "timeline_fit": asset.get("timeline_fit", ""),
                "evidence": _gap_evidence(asset, needs, behavior),
                "risk": _risk(asset, opportunity_type),
                "confidence": _confidence(asset),
                "source_trace": asset.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows).sort_values("market_gap_score", ascending=False)


def build_opportunity_board(asset_market_gaps_df: pd.DataFrame, behavior_df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    current_team = _int((config.get("current_team") or {}).get("roster_id"))
    rows: list[dict[str, Any]] = []
    gaps = asset_market_gaps_df[asset_market_gaps_df.get("target_roster_id") != current_team] if current_team else asset_market_gaps_df
    for _, gap in gaps.head(40).iterrows():
        behavior = _row_for(behavior_df, "roster_id", _int(gap.get("target_roster_id")))
        rows.append(
            {
                "action_type": gap.get("opportunity_type", ""),
                "target_team": gap.get("target_team", ""),
                "asset_in": gap.get("asset_name", ""),
                "asset_out": "future offer packet only",
                "manager_signal": behavior.get("plain_language_label", ""),
                "evidence": gap.get("evidence", ""),
                "risk": gap.get("risk", ""),
                "confidence": gap.get("confidence", ""),
                "source_trace": gap.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows)


def _player_value_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    if frame.empty:
        return values
    for _, row in frame.iterrows():
        record = row.to_dict()
        if str(record.get("player_id", "")):
            values[str(record.get("player_id"))] = record
        if str(record.get("player_name", "")):
            values[str(record.get("player_name")).lower()] = record
    return values


def _pick_value_map(frame: pd.DataFrame) -> dict[tuple[str, str], float]:
    values: dict[tuple[str, str], float] = {}
    if frame.empty:
        return values
    for _, row in frame.iterrows():
        values[(str(row.get("pick_season", "")), str(row.get("round", "")))] = _num(row.get("market_value"))
    return values


def _inventory_columns() -> list[str]:
    return ["roster_id", "team_name", "asset_type", "asset_id", "asset_name", "position", "age", "market_value", "liquidity_tier", "timeline_fit", "source_trace"]


def _manager_event_columns() -> list[str]:
    return [
        "event_type",
        "week",
        "created_datetime",
        "transaction_id",
        "roster_id",
        "team_name",
        "counterparty",
        "players_in",
        "picks_in",
        "faab_in",
        "players_out",
        "picks_out",
        "faab_out",
        "evidence",
    ]


def _manager_valuation_columns() -> list[str]:
    return [
        "owner_id",
        "roster_id",
        "team_name",
        "asset_type",
        "position_group",
        "preference_score",
        "evidence_count",
        "recency_weighted_score",
        "confidence",
        "label",
        "evidence",
    ]


def _valuation_row(
    team: pd.Series,
    asset_type: str,
    position_group: str,
    raw_score: float,
    evidence_count: int,
    positive_label: str,
    evidence: str,
) -> dict[str, Any]:
    score = round(max(0.0, min(100.0, raw_score)), 2)
    confidence = _evidence_confidence(evidence_count)
    label = positive_label if score >= 35 and confidence != "low" else "low-signal manager"
    return {
        "owner_id": team.get("owner_id", ""),
        "roster_id": team.get("roster_id", ""),
        "team_name": team.get("team_name", "") or team.get("display_name", ""),
        "asset_type": asset_type,
        "position_group": position_group,
        "preference_score": score,
        "evidence_count": evidence_count,
        "recency_weighted_score": score,
        "confidence": confidence,
        "label": label,
        "evidence": evidence,
    }


def _evidence_confidence(evidence_count: int) -> str:
    if evidence_count >= 8:
        return "high"
    if evidence_count >= 2:
        return "medium"
    return "low"


def _latest_teams(teams_df: pd.DataFrame) -> pd.DataFrame:
    if teams_df.empty:
        return pd.DataFrame(columns=["roster_id", "team_name", "owner_id"])
    frame = teams_df.fillna("").copy()
    if "season" in frame.columns:
        frame["_season_sort"] = frame["season"].astype(str)
        frame = frame.sort_values("_season_sort").drop_duplicates("roster_id", keep="last")
        frame = frame.drop(columns=["_season_sort"])
    return frame


def _proxy_player_value(position: str, age: float, roster_status: str) -> float:
    base = {"QB": 45, "WR": 28, "TE": 24, "RB": 18}.get(position, 8)
    if age and age <= 24:
        base += 10
    elif age and age >= 29 and position in {"RB", "WR", "TE"}:
        base -= 9
    if roster_status == "starter":
        base += 8
    if roster_status == "taxi":
        base += 5
    return max(1, base)


def _proxy_pick_value(round_no: int) -> float:
    return {1: 55, 2: 28, 3: 14, 4: 7, 5: 3}.get(round_no, 2)


def _liquidity_tier(position: str, age: float, market_value: float, asset_type: str) -> str:
    if asset_type == "pick":
        return "high"
    if position in {"QB", "WR", "TE"} and (not age or age <= 26) and market_value >= 25:
        return "high"
    if position == "RB" and age >= 28:
        return "thin"
    return "medium"


def _timeline_fit(position: str, age: float, config: dict[str, Any]) -> str:
    direction = (config.get("strategy_profile") or {}).get("team_direction", "")
    if direction != "deep_rebuild":
        return "generic_fit"
    if position in PASS_CATCHERS and (not age or age <= 26):
        return "strong_rebuild_fit"
    if position == "QB" and (not age or age <= 28):
        return "core_or_rebuild_fit"
    if position == "RB" and age and age >= 27:
        return "sell_or_churn_fit"
    return "neutral_fit"


def _need(count: int, target: int) -> str:
    if count < target:
        return "high"
    if count == target:
        return "medium"
    return "low"


def _team_shape(qb: int, rb: int, pass_catchers: int, firsts: int) -> str:
    if firsts >= 3 and rb < 7:
        return "rebuild_asset_bank"
    if rb >= 8 and qb >= 3:
        return "contender_shape"
    if pass_catchers >= 14:
        return "pass_catcher_depth"
    return "balanced_or_unclear"


def _behavior_label(trades: int, firsts_in: int, firsts_out: int, faab: int, claims: int) -> str:
    if firsts_in > firsts_out:
        return "pick buyer / patient builder"
    if firsts_out > firsts_in:
        return "pick seller / win-now buyer"
    if faab >= 50 or claims >= 5:
        return "waiver aggressive"
    if trades >= 3:
        return "trade active"
    return "quiet market participant"


def _behavior_evidence(trades: int, firsts_in: int, firsts_out: int, faab: int, claims: int) -> str:
    return f"trades={trades}; future_1sts_in={firsts_in}; future_1sts_out={firsts_out}; faab={faab}; waiver_claims={claims}"


def _demand_by_position(needs_df: pd.DataFrame) -> dict[str, int]:
    if needs_df.empty:
        return {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "PICK": 0}
    return {
        "QB": int((needs_df["need_qb"] == "high").sum()),
        "RB": int((needs_df["need_rb"] == "high").sum()),
        "WR": int((needs_df["need_pass_catcher"] == "high").sum()),
        "TE": int((needs_df["need_pass_catcher"] == "high").sum()),
        "PICK": int((needs_df["need_picks"] == "high").sum()),
    }


def _score_tier(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "thin"


def _scarcity_bonus(position: str, needs: dict[str, Any]) -> float:
    if position == "QB" and needs.get("need_qb") == "high":
        return 18
    if position == "RB" and needs.get("need_rb") == "high":
        return 10
    if position in PASS_CATCHERS and needs.get("need_pass_catcher") == "high":
        return 14
    if position == "PICK" and needs.get("need_picks") == "high":
        return 16
    return 4


def _gap_evidence(asset: pd.Series, needs: dict[str, Any], behavior: dict[str, Any]) -> str:
    return (
        f"value={asset.get('market_value')}; liquidity={asset.get('liquidity_tier')}; "
        f"timeline={asset.get('timeline_fit')}; team_shape={needs.get('team_shape', '')}; "
        f"manager={behavior.get('plain_language_label', '')}"
    )


def _risk(asset: pd.Series, opportunity_type: str) -> str:
    if asset.get("source_trace") == "internal_proxy_player_value":
        return "medium: external market value unavailable"
    if opportunity_type == "pick_reacquisition_target":
        return "low-to-medium: pick price changes with standings"
    return "medium: verify price before acting"


def _confidence(asset: pd.Series) -> str:
    return "medium" if str(asset.get("source_trace", "")).startswith("internal_proxy") else "high"


def _row_for(frame: pd.DataFrame, column: str, value: Any) -> dict[str, Any]:
    if frame.empty or column not in frame:
        return {}
    rows = frame[frame[column] == value]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _num(value: Any) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _model_value(value: float) -> float:
    if value > 100:
        return value / 100
    return value


def _int(value: Any) -> int:
    try:
        if value in ("", None) or pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0
