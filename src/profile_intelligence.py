from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


TAG_COLUMNS = ["entity_id", "entity_name", "tag", "score", "confidence", "evidence", "risk", "source_trace", "generated_at"]
CYCLE_COLUMNS = [
    "owner_id",
    "roster_id",
    "team_name",
    "dynasty_cycle",
    "trade_temperature",
    "pick_posture",
    "waiver_posture",
    "likely_needs",
    "likely_sells",
    "confidence",
    "evidence",
]
PLAYER_DOSSIER_COLUMNS = [
    "player_id",
    "player_name",
    "position",
    "age",
    "roster_id",
    "team_name",
    "roster_status",
    "market_value",
    "projected_fantasy_points",
    "projected_ppg",
    "projection_confidence",
    "signal_label",
    "breakout_score",
    "sell_score",
    "news_impact",
    "transaction_count",
    "last_transaction",
    "source_trace",
]
PLAYER_HISTORY_COLUMNS = [
    "player_id",
    "player_name",
    "event_type",
    "season",
    "week",
    "created_datetime",
    "roster_id",
    "team_name",
    "counterparty",
    "direction",
    "evidence",
    "source_trace",
]


def build_profile_intelligence_tables(
    manager_profiles_df: pd.DataFrame,
    manager_event_log_df: pd.DataFrame,
    manager_valuation_profiles_df: pd.DataFrame,
    team_needs_df: pd.DataFrame,
    pick_ownership_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    waivers_df: pd.DataFrame,
    draft_picks_df: pd.DataFrame,
    market_consensus_df: pd.DataFrame,
    projections_df: pd.DataFrame,
    weekly_projections_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    player_signal_scores_df: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    generated_at = datetime.now(timezone.utc).isoformat()
    current_season = _int((config or {}).get("current_season")) or None
    # Player dossiers are built first so the manager cycle reads can name each roster's actual
    # veteran assets instead of a fixed per-cycle string.
    player_history = build_player_transaction_history(trades_df, waivers_df, draft_picks_df)
    player_dossiers = build_player_dossiers(
        roster_players_df,
        market_consensus_df,
        projections_df,
        weekly_projections_df,
        news_impact_df,
        player_signal_scores_df,
        player_history,
    )
    manager_cycles = build_manager_cycle_profiles(
        manager_profiles_df,
        manager_event_log_df,
        manager_valuation_profiles_df,
        team_needs_df,
        pick_ownership_df,
        player_dossiers,
        current_season,
    )
    manager_tags = build_manager_profile_tags(manager_cycles, manager_profiles_df, generated_at)
    player_tags = build_player_profile_tags(player_dossiers, player_signal_scores_df, news_impact_df, generated_at)
    return {
        "manager_profile_tags": manager_tags,
        "manager_cycle_profiles": manager_cycles,
        "player_dossiers": player_dossiers,
        "player_transaction_history": player_history,
        "player_profile_tags": player_tags,
    }


def build_manager_cycle_profiles(
    manager_profiles_df: pd.DataFrame,
    manager_event_log_df: pd.DataFrame,
    manager_valuation_profiles_df: pd.DataFrame,
    team_needs_df: pd.DataFrame,
    pick_ownership_df: pd.DataFrame,
    player_dossiers_df: pd.DataFrame | None = None,
    current_season: int | None = None,
) -> pd.DataFrame:
    if manager_profiles_df.empty:
        return pd.DataFrame([], columns=CYCLE_COLUMNS)
    frame = manager_profiles_df.fillna("").copy()
    frame["_seasons"] = frame["seasons_covered"].map(_season_count)
    frame["_trades_per_season"] = frame["total_trades"].map(_num) / frame["_seasons"].clip(lower=1)
    frame["_waivers_per_season"] = frame["number_of_waiver_claims"].map(_num) / frame["_seasons"].clip(lower=1)
    frame["_faab_per_season"] = frame["faab_spent_on_waivers"].map(_num) / frame["_seasons"].clip(lower=1)
    frame["_firsts_net"] = frame["future_1sts_acquired"].map(_num) - frame["future_1sts_sold"].map(_num)
    frame["_firsts_moved"] = frame["future_1sts_acquired"].map(_num) + frame["future_1sts_sold"].map(_num)
    frame["_trade_pct"] = _percentile_series(frame["_trades_per_season"])
    frame["_waiver_pct"] = _percentile_series(frame["_waivers_per_season"])
    frame["_faab_pct"] = _percentile_series(frame["_faab_per_season"])
    needs = _row_map(team_needs_df, "roster_id")
    # Only FUTURE firsts say anything about a team's current cycle. The all-time count (which
    # includes every already-drafted pick in league history) made 11 of 12 managers trip the old
    # absolute "rebuild" threshold -- median all-time count was 10 firsts.
    current_picks = _pick_counts(pick_ownership_df, current_season)
    frame["_future_firsts"] = frame["roster_id"].map(lambda rid: current_picks.get(_int(rid), 0.0))
    frame["_firsts_pct"] = _percentile_series(frame["_future_firsts"])
    frame["_net_pct"] = _percentile_series(frame["_firsts_net"])
    veterans_by_roster = _veterans_by_roster(player_dossiers_df)
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        roster_id = _int(row.get("roster_id"))
        need = needs.get(roster_id, {})
        firsts_owned = current_picks.get(roster_id, _num(need.get("future_firsts_owned")))
        dynasty_cycle = _dynasty_cycle(row, need, firsts_owned)
        trade_temperature = _temperature(_num(row.get("_trade_pct")), "trade")
        waiver_posture = _temperature(max(_num(row.get("_waiver_pct")), _num(row.get("_faab_pct"))), "waiver")
        pick_posture = _pick_posture(_num(row.get("_firsts_net")), _num(row.get("_firsts_moved")), firsts_owned)
        confidence = _manager_confidence(_num(row.get("_seasons")), _num(row.get("total_trades")), _num(row.get("number_of_waiver_claims")))
        rows.append(
            {
                "owner_id": row.get("owner_id", ""),
                "roster_id": roster_id,
                "team_name": row.get("team_name", ""),
                "dynasty_cycle": dynasty_cycle,
                "trade_temperature": trade_temperature,
                "pick_posture": pick_posture,
                "waiver_posture": waiver_posture,
                "likely_needs": _likely_needs(need),
                "likely_sells": _likely_sells(dynasty_cycle, row, need, veterans_by_roster.get(roster_id, [])),
                "confidence": confidence,
                "evidence": (
                    f"seasons={int(_num(row.get('_seasons')))}; trades_per_season={round(_num(row.get('_trades_per_season')), 2)}; "
                    f"waivers_per_season={round(_num(row.get('_waivers_per_season')), 2)}; faab_per_season={round(_num(row.get('_faab_per_season')), 2)}; "
                    f"future_1sts_net={round(_num(row.get('_firsts_net')), 2)}; current_firsts_owned={round(firsts_owned, 2)}; "
                    f"team_shape={need.get('team_shape', '')}"
                ),
            }
        )
    return pd.DataFrame(rows, columns=CYCLE_COLUMNS)


def build_manager_profile_tags(manager_cycles_df: pd.DataFrame, manager_profiles_df: pd.DataFrame, generated_at: str) -> pd.DataFrame:
    profile_map = _row_map(manager_profiles_df, "roster_id")
    rows: list[dict[str, Any]] = []
    for _, cycle in manager_cycles_df.fillna("").iterrows():
        roster_id = _int(cycle.get("roster_id"))
        profile = profile_map.get(roster_id, {})
        evidence = cycle.get("evidence", "")
        confidence = cycle.get("confidence", "low")
        base = {
            "entity_id": str(roster_id),
            "entity_name": cycle.get("team_name", ""),
            "confidence": confidence,
            "source_trace": "manager_profiles;manager_event_log;manager_valuation_profiles;team_needs_matrix;pick_ownership",
            "generated_at": generated_at,
        }
        tag_scores = {
            "rebuilder": 78 if cycle.get("dynasty_cycle") == "rebuild" else 45 if cycle.get("dynasty_cycle") == "transition" else 18,
            "contender": 80 if cycle.get("dynasty_cycle") == "contender" else 48 if cycle.get("dynasty_cycle") == "transition" else 22,
            "pick accumulator": 75 if "accumulator" in str(cycle.get("pick_posture")) else 35,
            "pick spender": 78 if "spender" in str(cycle.get("pick_posture")) else 35,
            "waiver aggressor": _score_from_label(cycle.get("waiver_posture"), "hot", 82, 28),
            "trade grinder": _score_from_label(cycle.get("trade_temperature"), "hot", 86, 30),
            "depth churner": 72 if "hot" in str(cycle.get("waiver_posture")) and _num(profile.get("number_of_waiver_claims")) >= 50 else 35,
            "veteran buyer": 68 if cycle.get("dynasty_cycle") == "contender" or _num(profile.get("future_1sts_sold")) > _num(profile.get("future_1sts_acquired")) else 32,
            "pass-catcher collector": 72 if _num(profile.get("pass_catcher_count")) >= 14 else 35,
            "low-signal manager": 82 if confidence == "low" else 10,
        }
        for tag, score in tag_scores.items():
            if score < 55:
                continue
            rows.append(
                {
                    **base,
                    "tag": tag,
                    "score": round(score, 2),
                    "evidence": evidence,
                    "risk": _tag_risk(confidence),
                }
            )
    return pd.DataFrame(rows, columns=TAG_COLUMNS).sort_values(["entity_name", "score"], ascending=[True, False])


def build_player_transaction_history(trades_df: pd.DataFrame, waivers_df: pd.DataFrame, draft_picks_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, trade in trades_df.fillna("").iterrows():
        for prefix, direction in (("team_a", "acquired"), ("team_b", "acquired")):
            for player in _split_items(trade.get(f"{prefix}_players_received", "")):
                rows.append(_player_event("", player, "trade", trade, prefix, direction, "Sleeper trade transaction"))
    for _, waiver in waivers_df.fillna("").iterrows():
        if str(waiver.get("player_added", "")):
            rows.append(_player_event("", waiver.get("player_added", ""), "waiver_add", waiver, "", "added", "Sleeper waiver transaction"))
        if str(waiver.get("player_dropped", "")):
            rows.append(_player_event("", waiver.get("player_dropped", ""), "waiver_drop", waiver, "", "dropped", "Sleeper waiver transaction"))
    for _, pick in draft_picks_df.fillna("").iterrows():
        if str(pick.get("player_name", "")):
            rows.append(
                {
                    "player_id": str(pick.get("player_id", "")),
                    "player_name": pick.get("player_name", ""),
                    "event_type": "draft_pick",
                    "season": pick.get("season", ""),
                    "week": "",
                    "created_datetime": "",
                    "roster_id": pick.get("roster_id", ""),
                    "team_name": "",
                    "counterparty": "",
                    "direction": f"drafted pick {pick.get('pick_no', '')}",
                    "evidence": "Sleeper draft pick",
                    "source_trace": "draft_picks",
                }
            )
    return pd.DataFrame(rows, columns=PLAYER_HISTORY_COLUMNS).sort_values(["player_name", "season", "created_datetime"], ascending=[True, False, False])


def build_player_dossiers(
    roster_players_df: pd.DataFrame,
    market_consensus_df: pd.DataFrame,
    projections_df: pd.DataFrame,
    weekly_projections_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    player_signal_scores_df: pd.DataFrame,
    player_history_df: pd.DataFrame,
) -> pd.DataFrame:
    current_roster = _current_season_frame(roster_players_df)
    market = _row_map(market_consensus_df, "player_id")
    projections = _row_map(projections_df, "player_id")
    signals = _row_map(player_signal_scores_df, "player_id")
    news = _news_by_player(news_impact_df)
    history = _history_by_player(player_history_df)
    rows: list[dict[str, Any]] = []
    for _, player in current_roster.fillna("").iterrows():
        player_id = str(player.get("player_id", ""))
        projection = projections.get(player_id, {})
        signal = signals.get(player_id, {})
        consensus = market.get(player_id, {})
        player_history = history.get(player_id) or history.get(str(player.get("player_name", "")).lower(), [])
        last_transaction = player_history[0].get("event_type", "") if player_history else ""
        rows.append(
            {
                "player_id": player_id,
                "player_name": player.get("player_name", ""),
                "position": player.get("position", ""),
                "age": player.get("age", ""),
                "roster_id": player.get("roster_id", ""),
                "team_name": player.get("team_name", ""),
                "roster_status": player.get("roster_status", ""),
                "market_value": round(_num(consensus.get("consensus_value") or signal.get("market_value")), 2),
                "projected_fantasy_points": round(_num(projection.get("projected_fantasy_points")), 2),
                "projected_ppg": round(_num(projection.get("projected_ppg")), 2),
                "projection_confidence": projection.get("projection_confidence", signal.get("confidence", "low")),
                "signal_label": signal.get("signal_label", ""),
                "breakout_score": signal.get("breakout_score", 0),
                "sell_score": signal.get("sell_score", 0),
                "news_impact": news.get(player_id, ""),
                "transaction_count": len(player_history),
                "last_transaction": last_transaction,
                "source_trace": _join_trace(
                    "roster_players",
                    consensus.get("source_trace", ""),
                    projection.get("source_trace", ""),
                    signal.get("source_trace", ""),
                    news.get(f"{player_id}:trace", ""),
                    "player_transaction_history" if player_history else "",
                ),
            }
        )
    return pd.DataFrame(rows, columns=PLAYER_DOSSIER_COLUMNS).sort_values(["team_name", "market_value", "projected_ppg"], ascending=[True, False, False])


def build_player_profile_tags(
    player_dossiers_df: pd.DataFrame,
    player_signal_scores_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    generated_at: str,
) -> pd.DataFrame:
    opportunity = _row_map(player_signal_scores_df, "player_id") if not player_signal_scores_df.empty else {}
    rows: list[dict[str, Any]] = []
    for _, player in player_dossiers_df.fillna("").iterrows():
        player_id = str(player.get("player_id", ""))
        age = _num(player.get("age"))
        market = _num(player.get("market_value"))
        ppg = _num(player.get("projected_ppg"))
        breakout = _num(player.get("breakout_score"))
        sell = _num(player.get("sell_score"))
        confidence = _player_confidence(player)
        opp = opportunity.get(player_id, {})
        opportunity_score = _num(opp.get("opportunity_score"))
        xfp_regression = _num(opp.get("xfp_regression_score"))
        role_trend = _num(opp.get("role_trend_score"))
        fragility = _num(opp.get("fragility_score"))
        evidence = (
            f"age={age}; market={market}; projected_ppg={ppg}; breakout={breakout}; sell={sell}; "
            f"opportunity={opportunity_score}; xfp_regression={xfp_regression}; role_trend={role_trend}; fragility={fragility}; "
            f"signal={player.get('signal_label', '')}; news={player.get('news_impact', '')}; transactions={player.get('transaction_count', 0)}"
        )
        tag_scores = {
            "franchise cornerstone": 90 if market >= 70 and ppg >= 14 and (not age or age <= 28) else 0,
            "breakout candidate": breakout,
            "post-hype sleeper": 66 if 0 < market <= 35 and breakout >= 45 and _num(player.get("transaction_count")) >= 1 else 0,
            "hype train": 72 if "market_heat" in str(player.get("news_impact")) and ppg < 10 else 0,
            "emerging role": 68 if ("role_or_value_change" in str(player.get("news_impact")) or breakout >= 55) and ppg >= 6 else 0,
            "declining asset": max(sell, 64 if age >= 29 and market >= 20 else 0),
            "liquidity chip": 76 if market >= 45 else 0,
            "roster clogger": 62 if market <= 5 and ppg <= 3 else 0,
            "injury discount": 72 if "injury" in str(player.get("news_impact")).lower() and market >= 10 else 0,
            "market overheat": 70 if market >= 45 and ppg < 8 else 0,
            # Opportunity-driven flags (Sprint 18). Our backtest showed these are value/risk/trend
            # FLAGS, not outcome rankers, so they live as tags, never as a ranking score.
            "buy-low usage": 70 if xfp_regression >= 60 and opportunity_score >= 55 else 0,
            "rising role": role_trend if role_trend >= 65 else 0,
            "fragile usage": fragility if fragility >= 65 else 0,
        }
        for tag, score in tag_scores.items():
            if score < 55:
                continue
            rows.append(
                {
                    "entity_id": player_id,
                    "entity_name": player.get("player_name", ""),
                    "tag": tag,
                    "score": round(min(100.0, score), 2),
                    "confidence": confidence,
                    "evidence": evidence,
                    "risk": _tag_risk(confidence),
                    "source_trace": player.get("source_trace", "") or "player_dossiers;player_signal_scores",
                    "generated_at": generated_at,
                }
            )
    return pd.DataFrame(rows, columns=TAG_COLUMNS).sort_values(["entity_name", "score"], ascending=[True, False])


def _player_event(player_id: str, player_name: Any, event_type: str, row: pd.Series, prefix: str, direction: str, evidence: str) -> dict[str, Any]:
    roster_id = row.get(f"{prefix}_roster_id", row.get("roster_id", ""))
    team_name = row.get(f"{prefix}_name", row.get("team_name", ""))
    other_prefix = "team_b" if prefix == "team_a" else "team_a"
    return {
        "player_id": player_id,
        "player_name": str(player_name),
        "event_type": event_type,
        "season": row.get("season", ""),
        "week": row.get("week", ""),
        "created_datetime": row.get("created_datetime", ""),
        "roster_id": roster_id,
        "team_name": team_name,
        "counterparty": row.get(f"{other_prefix}_name", row.get("counterparty", "")),
        "direction": direction,
        "evidence": evidence,
        "source_trace": "trades" if event_type == "trade" else "waivers",
    }


def _dynasty_cycle(row: pd.Series, need: dict[str, Any], firsts_owned: float) -> str:
    # League-relative classification (same fix class as Sprint 14's manager scores): a cycle is
    # a POSITION in this league's pick-capital distribution, not an absolute count. Absolute
    # thresholds classified 11 of 12 managers as "rebuild" -- impossible in a real league.
    # NOTE: _percentile_series returns a 0-100 scale (see _temperature's 75/45 thresholds).
    firsts_pct = _num(row.get("_firsts_pct"))
    net_pct = _num(row.get("_net_pct"))
    team_shape = str(need.get("team_shape", "")).lower()
    if "rebuild" in team_shape and firsts_pct >= 50:
        return "rebuild"
    if "contender" in team_shape and firsts_pct <= 50:
        return "contender"
    if firsts_pct >= 70 and net_pct >= 50:
        return "rebuild"
    # Zero future firsts is a meaningful absolute anchor at any league size: a team that has
    # spent all its future capital is contending by definition (rank percentiles alone can miss
    # the lowest team in small pools).
    if (firsts_pct <= 30 or _num(row.get("_future_firsts")) == 0) and net_pct <= 50:
        return "contender"
    if _num(row.get("_trade_pct")) >= 60:
        return "transition"
    return "balanced_or_unclear"


def _pick_posture(firsts_net: float, firsts_moved: float, firsts_owned: float) -> str:
    if firsts_moved < 3 and firsts_owned < 3:
        return "quiet pick market"
    if firsts_net >= 3 or firsts_owned >= 5:
        return "pick accumulator"
    if firsts_net <= -3:
        return "pick spender"
    return "two-way pick trader"


def _temperature(percentile: float, kind: str) -> str:
    if percentile >= 75:
        return f"hot {kind} market"
    if percentile >= 45:
        return f"active {kind} market"
    return f"quiet {kind} market"


def _likely_needs(need: dict[str, Any]) -> str:
    needs = []
    for label, column in (("QB", "need_qb"), ("RB", "need_rb"), ("pass catcher", "need_pass_catcher"), ("picks", "need_picks")):
        if str(need.get(column, "")).lower() == "high":
            needs.append(label)
    return "; ".join(needs) if needs else "no glaring need"


def _likely_sells(cycle: str, row: pd.Series, need: dict[str, Any], veterans: list[str] | None = None) -> str:
    # Ground the sell read in the manager's ACTUAL roster where possible -- a fixed string per
    # cycle made 11 managers read identically, which the user correctly flagged as wrong-looking.
    named = "; ".join((veterans or [])[:3])
    if cycle == "rebuild":
        return f"win-now veterans: {named}" if named else "veteran producers with short windows"
    if cycle == "contender":
        return "future picks only at premium; excess depth"
    if named:
        return f"aging depth: {named}"
    if _num(row.get("pass_catcher_count")) >= 16:
        return "pass-catcher depth"
    return "unclear; start with price discovery"


def _veterans_by_roster(player_dossiers_df: pd.DataFrame | None) -> dict[int, list[str]]:
    """Each roster's most-valuable veteran assets (age >= 28, real market value), best first --
    the concrete names a rebuilder would actually shop."""
    if player_dossiers_df is None or player_dossiers_df.empty:
        return {}
    veterans: dict[int, list[tuple[float, str]]] = {}
    for _, player in player_dossiers_df.fillna("").iterrows():
        age = _num(player.get("age"))
        market = _num(player.get("market_value"))
        if age < 28 or market < 20:
            continue
        roster_id = _int(player.get("roster_id"))
        label = f"{player.get('player_name', '')} ({player.get('position', '')}, {int(age)})"
        veterans.setdefault(roster_id, []).append((market, label))
    return {
        roster_id: [label for _, label in sorted(entries, reverse=True)]
        for roster_id, entries in veterans.items()
    }


def _manager_confidence(seasons: float, trades: float, waivers: float) -> str:
    if seasons >= 4 and (trades >= 30 or waivers >= 60):
        return "high"
    if seasons >= 2 and (trades >= 10 or waivers >= 20):
        return "medium"
    return "low"


def _player_confidence(row: pd.Series) -> str:
    if str(row.get("projection_confidence", "")).lower() == "high" and _num(row.get("market_value")) > 0:
        return "high"
    if _num(row.get("projected_ppg")) > 0 or _num(row.get("market_value")) > 0:
        return "medium"
    return "low"


def _tag_risk(confidence: str) -> str:
    if confidence == "low":
        return "high: sparse or low-confidence evidence"
    return "medium: deterministic tag, not a guarantee"


def _score_from_label(value: Any, needle: str, hit: float, miss: float) -> float:
    return hit if needle in str(value) else miss


def _season_count(value: Any) -> int:
    return max(1, len([part for part in str(value).split(";") if part.strip()]))


def _percentile_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    return series.rank(pct=True, method="average").fillna(0) * 100


def _pick_counts(frame: pd.DataFrame, current_season: int | None = None) -> dict[int, float]:
    """First-round picks owned per roster. When current_season is given, only FUTURE picks count
    (pick_season >= current season) -- all-time counts include every already-drafted pick in league
    history and say nothing about a team's current cycle."""
    counts: dict[int, float] = {}
    if frame.empty:
        return counts
    for _, row in frame.fillna("").iterrows():
        if str(row.get("round", "")) != "1":
            continue
        if current_season is not None and _int(row.get("pick_season")) < current_season:
            continue
        owner = _int(row.get("current_owner_roster_id"))
        counts[owner] = counts.get(owner, 0) + 1
    return counts


def _current_season_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "season" not in frame:
        return frame
    seasons = pd.to_numeric(frame["season"], errors="coerce").dropna()
    if seasons.empty:
        return frame
    return frame[frame["season"].astype(str) == str(int(seasons.max()))]


def _news_by_player(frame: pd.DataFrame) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    traces: dict[str, list[str]] = {}
    if frame.empty:
        return {}
    for _, row in frame.fillna("").iterrows():
        player_id = str(row.get("player_id", ""))
        if not player_id:
            continue
        values.setdefault(player_id, []).append(str(row.get("impact_type", "")))
        traces.setdefault(player_id, []).append(str(row.get("source_trace", "")))
    result = {player_id: "; ".join(sorted(set(items))) for player_id, items in values.items()}
    result.update({f"{player_id}:trace": "; ".join(sorted(set(items))) for player_id, items in traces.items()})
    return result


def _history_by_player(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {}
    if frame.empty:
        return history
    for row in frame.fillna("").to_dict(orient="records"):
        if str(row.get("player_id", "")):
            history.setdefault(str(row.get("player_id")), []).append(row)
        if str(row.get("player_name", "")):
            history.setdefault(str(row.get("player_name")).lower(), []).append(row)
    return history


def _row_map(frame: pd.DataFrame, key: str) -> dict[Any, dict[str, Any]]:
    if frame.empty or key not in frame:
        return {}
    rows: dict[Any, dict[str, Any]] = {}
    for _, row in frame.fillna("").iterrows():
        raw_key = row.get(key)
        keys = [raw_key]
        if key == "roster_id":
            keys.append(_int(raw_key))
        if key == "player_id":
            keys.append(str(raw_key))
        for item in keys:
            if item not in ("", None):
                rows[item] = row.to_dict()
    return rows


def _split_items(value: Any) -> list[str]:
    if value is None or pd.isna(value) or value == "":
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _join_trace(*parts: Any) -> str:
    return "; ".join(str(part) for part in parts if part not in ("", None))


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
