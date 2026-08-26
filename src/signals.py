from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from .availability import availability_note as shared_availability_note
from .availability import current_availability_status


PASS_CATCHERS = {"WR", "TE"}


# These fields are copied from the canonical horizon table into counterparty
# artifacts.  They are evidence context, not another trade-price formula.
HORIZON_CONTEXT_COLUMNS = [
    "horizon_market_percentile",
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
    "next_game_minus_market_delta",
    "rest_of_season_minus_market_delta",
    "dynasty_minus_market_delta",
    "career_minus_market_delta",
    "rest_of_season_minus_next_game_delta",
    "dynasty_minus_rest_of_season_delta",
    "career_minus_dynasty_delta",
    "horizon_market_disagreement_window",
    "horizon_market_disagreement_delta",
    "horizon_market_disagreement_magnitude",
    "horizon_market_disagreement_read",
]

_HORIZON_MARKET_WINDOWS = (
    ("this_week", "next_game_minus_market_delta"),
    ("rest_of_season", "rest_of_season_minus_market_delta"),
    ("dynasty", "dynasty_minus_market_delta"),
    ("career_window", "career_minus_market_delta"),
)


def build_signal_tables(
    projections_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    player_market_values_df: pd.DataFrame,
    team_needs_df: pd.DataFrame,
    manager_behavior_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    config: dict[str, Any],
    manager_valuation_profiles_df: pd.DataFrame | None = None,
    opportunity_scores_df: pd.DataFrame | None = None,
    team_asset_inventory_df: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    scoped_news = _scope_news_impact(news_impact_df, config)
    scores = build_player_signal_scores(
        projections_df,
        roster_players_df,
        player_market_values_df,
        team_needs_df,
        manager_behavior_df,
        scoped_news,
        config,
        opportunity_scores_df,
        team_asset_inventory_df,
    )
    news_market_edges = build_news_market_edges(scores, scoped_news, config)
    gaps = build_projection_market_gaps(scores)
    breakouts = build_breakout_candidates(scores)
    sells = build_sell_candidates(scores, config)
    fits = build_team_fit_scores(scores, team_needs_df, config)
    actions = build_action_recommendations(scores, config)
    counterparty_edges = build_counterparty_trade_edges(scores, manager_valuation_profiles_df, team_needs_df, config)
    return {
        "player_signal_scores": scores,
        "breakout_candidates": breakouts,
        "sell_candidates": sells,
        "projection_market_gaps": gaps,
        "news_market_edges": news_market_edges,
        "team_fit_scores": fits,
        "action_recommendations": actions,
        "counterparty_trade_edges": counterparty_edges,
    }


def build_player_signal_scores(
    projections_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    player_market_values_df: pd.DataFrame,
    team_needs_df: pd.DataFrame,
    manager_behavior_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    config: dict[str, Any],
    opportunity_scores_df: pd.DataFrame | None = None,
    team_asset_inventory_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if projections_df.empty:
        return pd.DataFrame([], columns=_signal_columns())

    market = _market_value_map(player_market_values_df, team_asset_inventory_df)
    market_values_by_position = _market_values_by_position(player_market_values_df)
    projection_values_by_position = _values_by_position(projections_df, "projected_ppg")
    ages = _age_map(roster_players_df)
    availability = _availability_map(roster_players_df)
    needs = _row_map(team_needs_df, "roster_id")
    behavior = _row_map(manager_behavior_df, "roster_id")
    news = _news_map(news_impact_df)
    opportunity = _opportunity_map(opportunity_scores_df)
    rows: list[dict[str, Any]] = []

    for _, projection in projections_df.fillna("").iterrows():
        player_id = str(projection.get("player_id", ""))
        player_name = str(projection.get("player_name", ""))
        roster_id = _int(projection.get("roster_id"))
        position = str(projection.get("position", ""))
        age = ages.get(player_id, 0.0)
        availability_record = availability.get(player_id, {})
        availability_status = current_availability_status(availability_record)
        availability_note = shared_availability_note(availability_record)
        market_record = market.get(player_id) or market.get(player_name.lower()) or {}
        market_value = _num(market_record.get("market_value"))
        normalized_market = _normalize_market(market_value)
        projection_percentile = _percentile(_num(projection.get("projected_ppg")), projection_values_by_position.get(position, []))
        external_market = bool(market_record) and not _is_proxy_market(market_record)
        market_percentile = (
            _percentile(normalized_market, market_values_by_position.get(position, []))
            if external_market
            else None
        )
        ppg = _num(projection.get("projected_ppg"))
        points = _num(projection.get("projected_fantasy_points"))
        projection_confidence = str(projection.get("projection_confidence", "low")) or "low"
        team_need = needs.get(roster_id, {})
        manager = behavior.get(roster_id, {})
        news_signal = news.get(player_id, "")
        opp = opportunity.get(player_id, {})
        opportunity_score = _num(opp.get("opportunity_score"))
        xfp_regression_score = _num(opp.get("xfp_regression_score"))
        role_trend_score = _num(opp.get("role_trend_score"))
        fragility_score = _num(opp.get("fragility_score"))

        projection_edge = _projection_edge_score(ppg, projection_confidence, availability_status)
        role_uncertainty = _role_uncertainty(position, age, market_value, availability_status)
        market_gap = _market_gap_score(
            projection_edge,
            normalized_market,
            market_record,
            role_uncertainty,
            projection_percentile,
            market_percentile,
        )
        market_gap_status = _market_gap_status(market_record, market_percentile, market_gap)
        timeline_fit = _timeline_fit_score(position, age, config)
        breakout = _breakout_score(position, age, ppg, market_gap, projection_confidence, news_signal, opportunity_score, role_uncertainty)
        sell = _sell_score(position, age, ppg, normalized_market, roster_id, config, projection_confidence, news_signal)
        label = _signal_label(breakout, sell, market_gap, ppg, projection_confidence, role_uncertainty)
        confidence = _signal_confidence(projection_confidence, market_record, availability_status)
        source_trace = _join_trace(projection.get("source_trace", ""), market_record.get("source_trace", ""), news_signal)

        rows.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "position": position,
                "age": age,
                "roster_id": roster_id,
                "team_name": projection.get("team_name", ""),
                "current_availability_status": availability_status,
                "projected_fantasy_points": round(points, 2),
                "projected_ppg": round(ppg, 2),
                "market_value": round(market_value, 2),
                "projection_edge_score": projection_edge,
                "market_gap_score": market_gap,
                "timeline_fit_score": timeline_fit,
                "breakout_score": breakout,
                "sell_score": sell,
                "opportunity_score": round(opportunity_score, 1),
                "xfp_regression_score": round(xfp_regression_score, 1),
                "role_trend_score": round(role_trend_score, 1),
                "fragility_score": round(fragility_score, 1),
                "signal_label": label,
                "projection_percentile": projection_percentile,
                "market_percentile": market_percentile if market_percentile is not None else "",
                "market_gap_status": market_gap_status,
                "evidence": _evidence(
                    projection,
                    market_value,
                    team_need,
                    manager,
                    news_signal,
                    availability_note,
                    role_uncertainty,
                    projection_percentile,
                    market_percentile,
                    market_gap_status,
                ),
                "risk": _risk(projection_confidence, market_record, sell, availability_note, role_uncertainty),
                "confidence": confidence,
                "source_trace": source_trace,
            }
        )

    return pd.DataFrame(rows, columns=_signal_columns()).sort_values(
        ["breakout_score", "market_gap_score", "projected_ppg"],
        ascending=[False, False, False],
    )


def build_projection_market_gaps(scores_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in scores_df.fillna("").iterrows():
        availability_status = str(row.get("current_availability_status") or "").strip()
        unavailable_for_current_action = availability_status == "no_current_nfl_team"
        gap_score = 0.0 if unavailable_for_current_action else _num(row.get("market_gap_score"))
        rows.append(
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "current_availability_status": availability_status,
                "projected_fantasy_points": row.get("projected_fantasy_points", 0),
                "projected_ppg": row.get("projected_ppg", 0),
                "market_value": row.get("market_value", 0),
                "projection_percentile": row.get("projection_percentile", ""),
                "market_percentile": row.get("market_percentile", ""),
                "market_gap_status": row.get("market_gap_status", ""),
                "gap_score": gap_score,
                "gap_label": (
                    "availability_conditioned_gap"
                    if unavailable_for_current_action
                    else "role_uncertain_gap"
                    if str(row.get("signal_label", "")) == "role_uncertain_watch"
                    else _gap_label(gap_score)
                ),
                "evidence": (
                    f"{row.get('evidence', '')}; current-action gate: no current NFL team; "
                    "historical gap is retained as conditional context, not an actionable market gap."
                    if unavailable_for_current_action
                    else row.get("evidence", "")
                ),
                "risk": (
                    f"{row.get('risk', '')}; no current NFL team; do not treat the historical gap as a current action."
                    if unavailable_for_current_action
                    else row.get("risk", "")
                ),
                "confidence": "low" if unavailable_for_current_action else row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_gap_columns()).sort_values("gap_score", ascending=False)


def build_news_market_edges(
    scores_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Find scoped news catalysts that have not obviously cleared the market.

    This is deliberately narrower than ``player_signal_scores``. A player only
    enters when a directional news event and a meaningful deterministic market
    or sell score agree on a review queue. The result is a research lead, not a
    claim that the market is wrong.
    """

    columns = _news_market_columns()
    if scores_df.empty or news_impact_df.empty:
        return pd.DataFrame([], columns=columns)

    scoped_news = _scope_news_impact(news_impact_df, config or {})
    if scoped_news.empty:
        return pd.DataFrame([], columns=columns)

    news_by_player: dict[str, list[dict[str, Any]]] = {}
    for _, news_row in scoped_news.fillna("").iterrows():
        player_id = str(news_row.get("player_id", "")).strip()
        if player_id:
            news_by_player.setdefault(player_id, []).append(news_row.to_dict())
    context = (config or {}).get("context") if isinstance(config, Mapping) else {}
    context = context if isinstance(context, Mapping) else {}
    scope_season = context.get("season") or (config or {}).get("current_season", "")
    configured_leagues = (config or {}).get("leagues") if isinstance(config, Mapping) else {}
    scope_league_id = (
        context.get("league_id")
        or (config or {}).get("league_id", "")
        or (configured_leagues.get(str(scope_season), "") if isinstance(configured_leagues, Mapping) else "")
    )

    positive_types = {"market_heat", "waiver_watch", "role_or_value_change"}
    negative_types = {"sell_pressure", "market_cooling", "injury_risk"}
    rows: list[dict[str, Any]] = []
    for _, score_row in scores_df.fillna("").iterrows():
        player_id = str(score_row.get("player_id", "")).strip()
        if str(score_row.get("current_availability_status") or "").strip() == "no_current_nfl_team":
            # A current news signal can still be shown in the News Desk, but it
            # cannot become a market edge or a recommendation while the player
            # has no current NFL role.
            continue
        events = news_by_player.get(player_id, [])
        if not player_id or not events:
            continue
        impact_types = sorted({
            str(row.get("impact_type", "monitor"))
            for row in events
            if str(row.get("impact_type", "")).strip()
        })
        positive = [impact for impact in impact_types if impact in positive_types]
        negative = [impact for impact in impact_types if impact in negative_types]
        market_gap = _num(score_row.get("market_gap_score"))
        sell_score = _num(score_row.get("sell_score"))
        if positive and negative and max(market_gap, sell_score) >= 18:
            direction = "mixed"
            edge_type = "mixed_news_signal"
            base_score = max(market_gap, sell_score)
            risk = "Directional news conflicts; reconcile the underlying events and current role before treating this as an opportunity."
        elif positive and market_gap >= 18:
            direction = "upside"
            edge_type = "news_lag_upside"
            base_score = market_gap
            risk = "The catalyst may be early, transient, or already reflected outside this market snapshot; verify role and price before acting."
        elif negative and sell_score >= 20:
            direction = "pressure"
            edge_type = "news_lag_pressure"
            base_score = sell_score
            risk = "The news may be temporary or the market may have already adjusted; do not force a sale without a live price check."
        else:
            continue

        event_evidence = "; ".join(
            f"{row.get('impact_type', 'monitor')}: {row.get('evidence', 'event recorded')}"
            for row in events[:4]
        )
        news_confidences = {str(row.get("confidence", "low")).lower() for row in events}
        score_confidence = str(score_row.get("confidence", "low")).lower() or "low"
        confidence = _edge_confidence(score_confidence, news_confidences)
        event_bonus = min(15.0, max(0.0, (len(events) - 1) * 4.0))
        confidence_bonus = 5.0 if confidence == "high" else 2.0 if confidence == "medium" else 0.0
        edge_score = round(min(100.0, base_score + event_bonus + confidence_bonus), 2)
        news_sources = _join_trace(*(str(row.get("source_trace", "")) for row in events))
        source_trace = _join_trace(str(score_row.get("source_trace", "")), news_sources, "news_market_edges")
        rows.append(
            {
                "player_id": player_id,
                "player_name": score_row.get("player_name", ""),
                "position": score_row.get("position", ""),
                "roster_id": score_row.get("roster_id", ""),
                "league_id": scope_league_id,
                "season": scope_season,
                "team_name": score_row.get("team_name", ""),
                "news_direction": direction,
                "edge_type": edge_type,
                "news_impact": ",".join(impact_types),
                "news_event_count": len(events),
                "market_value": round(_num(score_row.get("market_value")), 2),
                "projected_ppg": round(_num(score_row.get("projected_ppg")), 2),
                "market_gap_score": round(market_gap, 2),
                "sell_score": round(sell_score, 2),
                "news_market_edge_score": edge_score,
                "evidence": (
                    f"news={','.join(impact_types)}; events={len(events)}; market={_num_text(score_row.get('market_value'))}; "
                    f"baseline_ppg={_num_text(score_row.get('projected_ppg'))}; market_gap={_num_text(market_gap)}; "
                    f"sell_score={_num_text(sell_score)}; {event_evidence}"
                ),
                "risk": risk,
                "confidence": confidence,
                "source_trace": source_trace,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["news_market_edge_score", "market_gap_score", "sell_score"],
        ascending=[False, False, False],
    )


def build_breakout_candidates(scores_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    candidates = (
        scores_df[
            (scores_df.get("breakout_score", pd.Series(dtype=float)) >= 45)
            & (scores_df.get("current_availability_status", "") != "no_current_nfl_team")
        ]
        if not scores_df.empty
        else pd.DataFrame()
    )
    for _, row in candidates.fillna("").iterrows():
        rows.append(
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "current_availability_status": row.get("current_availability_status", ""),
                "current_team_name": row.get("team_name", ""),
                "breakout_score": row.get("breakout_score", 0),
                "projection_edge": row.get("projection_edge_score", 0),
                "market_value": row.get("market_value", 0),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_breakout_columns()).sort_values("breakout_score", ascending=False)


def build_sell_candidates(scores_df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    current_roster = _int((config.get("current_team") or {}).get("roster_id"))
    candidates = scores_df.copy()
    if current_roster:
        candidates = candidates[candidates.get("roster_id") == current_roster]
    if not candidates.empty:
        candidates = candidates[
            (candidates.get("sell_score", pd.Series(dtype=float)) >= 35)
            & (candidates.get("current_availability_status", "") != "no_current_nfl_team")
        ]
    rows: list[dict[str, Any]] = []
    for _, row in candidates.fillna("").iterrows():
        rows.append(
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "current_availability_status": row.get("current_availability_status", ""),
                "current_team_name": row.get("team_name", ""),
                "sell_score": row.get("sell_score", 0),
                "projection_risk": row.get("risk", ""),
                "market_value": row.get("market_value", 0),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_sell_columns()).sort_values("sell_score", ascending=False)


def build_team_fit_scores(scores_df: pd.DataFrame, team_needs_df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if scores_df.empty or team_needs_df.empty:
        return pd.DataFrame(rows, columns=_fit_columns())
    for _, team in team_needs_df.fillna("").iterrows():
        roster_id = _int(team.get("roster_id"))
        team_name = team.get("team_name", "")
        for _, player in scores_df.fillna("").iterrows():
            if str(player.get("current_availability_status") or "").strip() == "no_current_nfl_team":
                continue
            position = str(player.get("position", ""))
            timeline = _timeline_fit_score(position, _num(player.get("age")), config)
            need = _need_fit_score(position, team)
            # Market values are already canonical values from the economics
            # layer.  A value of 102.32 is a legitimate high-end asset, not a
            # raw x100 source value that should be divided again.
            liquidity = min(100.0, max(0.0, _num(player.get("market_value"))))
            total = round(timeline * 0.35 + need * 0.35 + liquidity * 0.3, 2)
            rows.append(
                {
                    "roster_id": roster_id,
                    "team_name": team_name,
                    "player_id": player.get("player_id", ""),
                    "player_name": player.get("player_name", ""),
                    "position": position,
                    "timeline_fit_score": timeline,
                    "need_fit_score": need,
                    "liquidity_fit_score": round(liquidity, 2),
                    "fit_label": "strong_fit" if total >= 65 else "watch_fit" if total >= 45 else "thin_fit",
                    "evidence": f"timeline={timeline}; need={need}; liquidity={round(liquidity, 2)}",
                    "risk": player.get("risk", ""),
                    "confidence": player.get("confidence", ""),
                    "source_trace": player.get("source_trace", ""),
                }
            )
    return pd.DataFrame(rows, columns=_fit_columns()).sort_values(["roster_id", "timeline_fit_score"], ascending=[True, False])


def build_action_recommendations(scores_df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if scores_df.empty:
        return pd.DataFrame(rows, columns=_action_columns())
    current_roster = _int((config.get("current_team") or {}).get("roster_id"))
    for _, row in scores_df.fillna("").iterrows():
        action = _classify_action(row, current_roster)
        rows.append(
            {
                "roster_id": row.get("roster_id", 0),
                "team_name": row.get("team_name", ""),
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "age": row.get("age", 0),
                "current_availability_status": row.get("current_availability_status", ""),
                "action_label": action["action_label"],
                "consumer_label": action["consumer_label"],
                "action_rank": action["action_rank"],
                "action_score": action["action_score"],
                "projected_ppg": row.get("projected_ppg", 0),
                "market_value": row.get("market_value", 0),
                "why": action["why"],
                "evidence": row.get("evidence", ""),
                "risk": action["risk"] or row.get("risk", ""),
                "confidence": action["confidence"] or row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_action_columns()).sort_values(["action_rank", "action_score"], ascending=[True, False])


def build_counterparty_trade_edges(
    scores_df: pd.DataFrame,
    manager_valuation_profiles_df: pd.DataFrame | None,
    team_needs_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if scores_df.empty:
        return pd.DataFrame(rows, columns=_counterparty_columns())
    current_roster = _int((config.get("current_team") or {}).get("roster_id"))
    profile_map = _manager_pref_map(manager_valuation_profiles_df if manager_valuation_profiles_df is not None else pd.DataFrame())
    needs = _row_map(team_needs_df, "roster_id")
    for _, row in scores_df.fillna("").iterrows():
        if str(row.get("current_availability_status") or "").strip() == "no_current_nfl_team":
            continue
        target_roster_id = _int(row.get("roster_id"))
        if current_roster and target_roster_id == current_roster:
            continue
        position = str(row.get("position", ""))
        position_group = "PASS_CATCHER" if position in PASS_CATCHERS else position
        profile = profile_map.get((target_roster_id, position_group)) or profile_map.get((target_roster_id, "DEPTH")) or {}
        owner_preference = _num(profile.get("preference_score"))
        owner_confidence = str(profile.get("confidence", "low")) or "low"
        market = _normalize_market(_num(row.get("market_value")))
        projection_value = _num(row.get("projection_edge_score"))
        timeline = _num(row.get("timeline_fit_score"))
        our_value = round(projection_value * 0.52 + timeline * 0.28 + max(0.0, _num(row.get("market_gap_score"))) * 0.2, 2)
        team_need = _owner_need_score(position, needs.get(target_roster_id, {}))
        estimated_owner_value = round(market * 0.48 + owner_preference * 0.34 + team_need * 0.18, 2)
        edge_score = round(our_value - estimated_owner_value, 2)
        edge_type = _edge_type(edge_score, owner_preference, owner_confidence, _num(row.get("projected_ppg")), market)
        confidence = _counterparty_confidence(str(row.get("confidence", "low")), owner_confidence, market)
        rows.append(
            {
                "target_roster_id": target_roster_id,
                "target_team": row.get("team_name", ""),
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": position,
                "our_value_score": our_value,
                "market_consensus_value": round(market, 2),
                "estimated_owner_value_score": estimated_owner_value,
                "trade_edge_score": edge_score,
                "edge_type": edge_type,
                "evidence": (
                    f"projection_edge={row.get('projection_edge_score')}; market={round(market, 2)}; "
                    f"owner_pref={round(owner_preference, 2)}; owner_label={profile.get('label', 'low-signal manager')}; "
                    f"owner_need={team_need}"
                ),
                "risk": _counterparty_risk(edge_type, confidence, market),
                "confidence": confidence,
                "source_trace": row.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_counterparty_columns()).sort_values("trade_edge_score", ascending=False)


def enrich_counterparty_trade_edges_with_horizons(
    edges_df: pd.DataFrame,
    horizon_df: pd.DataFrame | None,
    team_needs_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Attach the selected and target team's time-horizon fit to trade edges.

    ``counterparty_trade_edges`` is built before horizon scores because the
    horizon model consumes the signal table.  This second, explicit join keeps
    the dependency direction honest: it enriches an existing edge with a
    target-team timeline read instead of reimplementing horizon math inside
    the counterparty model.  The result is not a trade price or a new blended
    score; it describes which team has the stronger use for the asset.
    """

    result = edges_df.copy() if isinstance(edges_df, pd.DataFrame) else pd.DataFrame()
    added_columns = {
        "target_team_lens": "",
        "target_horizon_fit_score": "",
        "active_horizon_fit_score": "",
        "horizon_fit_edge": "",
        "horizon_fit_read": "",
        "horizon_fit_basis": "",
        "horizon_model_version": "",
    }
    added_columns.update({column: "" for column in HORIZON_CONTEXT_COLUMNS})
    for column, default in added_columns.items():
        if column not in result.columns:
            result[column] = pd.Series(default, index=result.index, dtype=object)
        else:
            # Existing frames may carry pandas StringDtype columns from a CSV
            # read.  Timeline scores are numeric when joined, so use an object
            # seam that can safely hold both a score and an unavailable blank.
            result[column] = result[column].astype(object).where(result[column].notna(), default)
    if result.empty or horizon_df is None or horizon_df.empty:
        return result.reindex(columns=_counterparty_columns())

    horizon_by_key = {
        (str(row.get("player_id") or ""), _int(row.get("roster_id"))): row.to_dict()
        for _, row in horizon_df.fillna("").iterrows()
        if str(row.get("player_id") or "").strip()
    }
    needs = _row_map(team_needs_df, "roster_id")
    active_lens = _horizon_lens((config.get("strategy_profile") or {}).get("team_direction", ""))

    for index, edge in result.iterrows():
        horizon = horizon_by_key.get(
            (str(edge.get("player_id") or ""), _int(edge.get("target_roster_id"))),
            {},
        )
        if not horizon:
            continue
        target_roster_id = _int(edge.get("target_roster_id"))
        target_shape = needs.get(target_roster_id, {}).get("team_shape", "")
        target_lens = _horizon_lens(target_shape)
        target_fit = _horizon_fit(horizon, target_lens)
        active_fit = _horizon_fit(horizon, active_lens)
        horizon_context = _horizon_market_context(horizon)
        fit_edge = round(target_fit - active_fit, 2) if target_fit is not None and active_fit is not None else None
        if fit_edge is None:
            fit_read = "horizon_fit_unavailable"
        elif fit_edge >= 8:
            fit_read = "target_team_timeline_premium"
        elif fit_edge <= -8:
            fit_read = "active_team_timeline_premium"
        else:
            fit_read = "balanced_timeline_fit"
        basis = (
            f"target lens={target_lens} from team_shape={target_shape or 'unavailable'}; "
            f"active lens={active_lens}; horizon fit edge=target minus active ({fit_edge if fit_edge is not None else 'unavailable'}); "
            "timeline fit is separate from market price and position-relative horizon percentiles are not cross-position prices"
        )
        result.at[index, "target_team_lens"] = target_lens
        result.at[index, "target_horizon_fit_score"] = target_fit if target_fit is not None else ""
        result.at[index, "active_horizon_fit_score"] = active_fit if active_fit is not None else ""
        result.at[index, "horizon_fit_edge"] = fit_edge if fit_edge is not None else ""
        result.at[index, "horizon_fit_read"] = fit_read
        result.at[index, "horizon_fit_basis"] = basis
        result.at[index, "horizon_model_version"] = horizon.get("horizon_model_version", "")
        for column, value in horizon_context.items():
            result.at[index, column] = value
        result.at[index, "evidence"] = "; ".join(
            value
            for value in (
                str(edge.get("evidence") or ""),
                f"target_team_lens={target_lens}",
                f"target_horizon_fit={_display(target_fit)}",
                f"active_horizon_fit={_display(active_fit)}",
                f"horizon_fit_edge={_display(fit_edge)}",
                f"horizon_fit_read={fit_read}",
                f"horizon_model={horizon.get('horizon_model_version', '')}",
                (
                    f"largest_clock_market_disagreement={horizon_context.get('horizon_market_disagreement_window')}:"
                    f"{_display(horizon_context.get('horizon_market_disagreement_delta'))}"
                    if horizon_context.get("horizon_market_disagreement_window")
                    else ""
                ),
            )
            if value
        )
        trace = str(edge.get("source_trace") or "")
        if "player_horizon_market_scores" not in trace:
            trace = ";".join(value for value in (trace, "player_horizon_market_scores") if value)
        result.at[index, "source_trace"] = trace

    return result.reindex(columns=_counterparty_columns())


COUNTERPARTY_ASSET_INTEREST_COLUMNS = [
    "active_roster_id",
    "active_team",
    "asset_id",
    "asset_name",
    "asset_type",
    "position",
    "market_value",
    "target_roster_id",
    "target_team",
    "target_team_lens",
    "transaction_lane_read",
    "transaction_acquired_count",
    "transaction_sold_count",
    "transaction_net_acquired_count",
    "transaction_current_roster_overlap",
    "transaction_history_status",
    "transaction_lane_confidence",
    "target_need",
    "target_need_fit_score",
    "target_horizon_fit_score",
    "active_horizon_fit_score",
    "horizon_fit_edge",
    "horizon_fit_read",
    "horizon_model_version",
    *HORIZON_CONTEXT_COLUMNS,
    "observed_acquisition_signal",
    "conversation_fit_score",
    "conversation_fit_label",
    "evidence",
    "risk",
    "confidence",
    "source_trace",
]


def build_counterparty_asset_interest(
    inventory_df: pd.DataFrame,
    manager_transaction_preferences_df: pd.DataFrame | None,
    team_needs_df: pd.DataFrame,
    horizon_df: pd.DataFrame | None,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Find evidence-backed audiences for assets on the active roster.

    This is deliberately separate from ``counterparty_trade_edges``.  That
    table asks whether an asset held by another team looks mispriced relative
    to our model.  This table asks which other managers have an observed
    position-level acquisition lane, current need, and timeline fit for an
    asset we own.  ``conversation_fit_score`` is a prioritization aid, not a
    market value, probability of acceptance, or claim about manager intent.
    """

    empty = pd.DataFrame(columns=COUNTERPARTY_ASSET_INTEREST_COLUMNS)
    if inventory_df is None or inventory_df.empty:
        return empty
    if manager_transaction_preferences_df is None or manager_transaction_preferences_df.empty:
        return empty

    active_roster_id = _int((config.get("current_team") or {}).get("roster_id"))
    if not active_roster_id:
        return empty
    active_assets = inventory_df[
        inventory_df.apply(lambda row: _int(row.get("roster_id")) == active_roster_id, axis=1)
    ].copy()
    active_assets = active_assets[active_assets.get("asset_type", pd.Series(dtype=str)).astype(str).str.lower() == "player"]
    if active_assets.empty:
        return empty

    needs = _row_map(team_needs_df, "roster_id")
    active_lens = _horizon_lens((config.get("strategy_profile") or {}).get("team_direction", ""))
    horizon_by_key = _horizon_by_player_roster(horizon_df)
    lanes = _lane_map(manager_transaction_preferences_df)
    active_team = str((config.get("current_team") or {}).get("team_name") or "")
    rows: list[dict[str, Any]] = []

    for _, asset in active_assets.fillna("").iterrows():
        asset_id = str(asset.get("asset_id") or "").strip()
        position = str(asset.get("position") or "").upper().strip()
        position_group = _position_group_for_interest(position)
        if not asset_id or not position_group:
            continue
        horizon = horizon_by_key.get((asset_id, active_roster_id), {})
        for (target_roster_id, lane_position), lane in lanes.items():
            if target_roster_id == active_roster_id or lane_position != position_group:
                continue
            acquired = _int(lane.get("acquired_count"))
            sold = _int(lane.get("sold_count"))
            total = acquired + sold
            if total <= 0:
                continue
            target_roster_id = _int(target_roster_id)
            target_need = needs.get(target_roster_id, {})
            target_shape = str(target_need.get("team_shape") or "")
            target_lens = _horizon_lens(target_shape)
            target_fit = _horizon_fit(horizon, target_lens) if horizon else None
            active_fit = _horizon_fit(horizon, active_lens) if horizon else None
            horizon_context = _horizon_market_context(horizon)
            fit_edge = round(target_fit - active_fit, 2) if target_fit is not None and active_fit is not None else None
            if fit_edge is None:
                fit_read = "horizon_fit_unavailable"
            elif fit_edge >= 8:
                fit_read = "target_team_timeline_premium"
            elif fit_edge <= -8:
                fit_read = "active_team_timeline_premium"
            else:
                fit_read = "balanced_timeline_fit"

            acquisition_signal = _observed_acquisition_signal(acquired, sold)
            need_fit = _owner_need_score(position, target_need)
            components = [acquisition_signal, need_fit]
            weights = [0.55, 0.45]
            if target_fit is not None:
                components.append(target_fit)
                weights = [0.45, 0.30, 0.25]
            conversation_fit = round(sum(value * weight for value, weight in zip(components, weights)), 2)
            history_status = str(lane.get("history_status") or "sparse")
            lane_confidence = str(lane.get("confidence") or "low")
            confidence = _interest_confidence(lane_confidence, target_fit is not None, total)
            target_team = str(lane.get("team_name") or "")
            lane_read = str(lane.get("transaction_read") or "observed lane")
            horizon_basis = str(horizon.get("fit_basis") or "") if horizon else ""
            risk_parts = []
            if history_status != "supported":
                risk_parts.append("sparse transaction history")
            if not horizon:
                risk_parts.append("horizon context unavailable")
            risk_parts.append("observed lane is not proof of intent or offer acceptance")
            rows.append(
                {
                    "active_roster_id": active_roster_id,
                    "active_team": active_team or asset.get("team_name", ""),
                    "asset_id": asset_id,
                    "asset_name": asset.get("asset_name", ""),
                    "asset_type": asset.get("asset_type", "player"),
                    "position": position,
                    "market_value": _num(asset.get("market_value")),
                    "target_roster_id": target_roster_id,
                    "target_team": target_team,
                    "target_team_lens": target_lens,
                    "transaction_lane_read": lane_read,
                    "transaction_acquired_count": acquired,
                    "transaction_sold_count": sold,
                    "transaction_net_acquired_count": acquired - sold,
                    "transaction_current_roster_overlap": _int(lane.get("current_roster_acquired_count")),
                    "transaction_history_status": history_status,
                    "transaction_lane_confidence": lane_confidence,
                    "target_need": target_need.get(_need_field(position), "unavailable") if target_need else "unavailable",
                    "target_need_fit_score": need_fit,
                    "target_horizon_fit_score": target_fit if target_fit is not None else "",
                    "active_horizon_fit_score": active_fit if active_fit is not None else "",
                    "horizon_fit_edge": fit_edge if fit_edge is not None else "",
                    "horizon_fit_read": fit_read,
                    "horizon_model_version": horizon.get("horizon_model_version", "") if horizon else "",
                    **horizon_context,
                    "observed_acquisition_signal": acquisition_signal,
                    "conversation_fit_score": conversation_fit,
                    "conversation_fit_label": _conversation_fit_label(conversation_fit, lane_read),
                    "evidence": (
                        f"position_group={position_group}; observed acquired={acquired}; sold={sold}; net={acquired - sold}; "
                        f"target_need={target_need.get(_need_field(position), 'unavailable') if target_need else 'unavailable'}; "
                        f"need_fit={_display(need_fit)}; observed_acquisition_signal={_display(acquisition_signal)}; "
                        f"target_horizon_fit={_display(target_fit)}; active_horizon_fit={_display(active_fit)}; "
                        f"largest_clock_market_disagreement={horizon_context.get('horizon_market_disagreement_window') or 'unavailable'}:"
                        f"{_display(horizon_context.get('horizon_market_disagreement_delta'))}; "
                        "conversation fit prioritizes a question and does not estimate intent"
                    ),
                    "risk": "; ".join(risk_parts),
                    "confidence": confidence,
                    "source_trace": (
                        "team_asset_inventory;manager_transaction_preferences;team_needs_matrix"
                        + (";player_horizon_market_scores" if horizon else "")
                    ),
                }
            )

    if not rows:
        return empty
    return pd.DataFrame(rows, columns=COUNTERPARTY_ASSET_INTEREST_COLUMNS).sort_values(
        ["asset_name", "conversation_fit_score", "target_team"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def _lane_map(frame: pd.DataFrame) -> dict[tuple[int, str], dict[str, Any]]:
    lanes: dict[tuple[int, str], dict[str, Any]] = {}
    for _, row in frame.fillna("").iterrows():
        key = (_int(row.get("roster_id")), str(row.get("position_group") or ""))
        if not key[0] or not key[1]:
            continue
        existing = lanes.get(key)
        if existing is None or _int(row.get("acquired_count")) + _int(row.get("sold_count")) > _int(existing.get("acquired_count")) + _int(existing.get("sold_count")):
            lanes[key] = row.to_dict()
    return lanes


def _horizon_by_player_roster(frame: pd.DataFrame | None) -> dict[tuple[str, int], dict[str, Any]]:
    if frame is None or frame.empty:
        return {}
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for _, row in frame.fillna("").iterrows():
        player_id = str(row.get("player_id") or "").strip()
        roster_id = _int(row.get("roster_id"))
        if player_id and roster_id and (player_id, roster_id) not in result:
            result[(player_id, roster_id)] = row.to_dict()
    return result


def _position_group_for_interest(position: str) -> str:
    if position in PASS_CATCHERS:
        return "PASS_CATCHER"
    if position in {"QB", "RB"}:
        return position
    return ""


def _need_field(position: str) -> str:
    if position == "QB":
        return "need_qb"
    if position == "RB":
        return "need_rb"
    if position in PASS_CATCHERS:
        return "need_pass_catcher"
    return ""


def _observed_acquisition_signal(acquired: int, sold: int) -> float:
    total = acquired + sold
    if total <= 0:
        return 50.0
    # Shrink small samples toward neutral.  At eight movement events the
    # observed net direction reaches its full 0-100 range.
    return round(max(0.0, min(100.0, 50.0 + 50.0 * ((acquired - sold) / total) * min(total / 8.0, 1.0))), 2)


def _interest_confidence(lane_confidence: str, has_horizon: bool, total_events: int) -> str:
    if lane_confidence == "low" or total_events < 3:
        return "low"
    if lane_confidence == "high" and has_horizon:
        return "high"
    return "medium"


def _conversation_fit_label(score: float, lane_read: str) -> str:
    if "disposal" in lane_read and score < 60:
        return "limited_conversation_fit"
    if score >= 70:
        return "strong_conversation_fit"
    if score >= 55:
        return "watch_conversation_fit"
    return "limited_conversation_fit"


def _horizon_lens(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(token in text for token in ("contender", "win_now", "win-now", "compete")):
        return "contender"
    if any(token in text for token in ("rebuild", "asset_bank", "asset-bank", "patient", "future")):
        return "rebuilder"
    return "balanced"


def _optional_num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if not str(value).strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _horizon_fit(row: Mapping[str, Any], lens: str) -> float | None:
    contender = _optional_num(row.get("contender_fit_score"))
    rebuilder = _optional_num(row.get("rebuilder_fit_score"))
    if lens == "contender":
        return contender
    if lens == "rebuilder":
        return rebuilder
    if contender is not None and rebuilder is not None:
        return round((contender + rebuilder) / 2, 2)
    return contender if contender is not None else rebuilder


def _display(value: Any) -> str:
    number = _optional_num(value)
    if number is None:
        return "n/a"
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _horizon_market_context(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy canonical horizon evidence into a counterparty-facing row.

    The horizon table owns the score and delta calculation.  This helper only
    projects that evidence onto a trade conversation so the reader can see
    whether the disagreement is short-term, seasonal, dynasty, or career
    shaped.  The largest disagreement is a discovery label, never a blended
    valuation or a claim that the market is wrong.
    """

    source = row or {}
    context: dict[str, Any] = {
        column: "" for column in HORIZON_CONTEXT_COLUMNS
    }
    for column in (
        "next_game_market_score",
        "rest_of_season_market_score",
        "dynasty_market_score",
        "career_projection_score",
        "next_game_minus_market_delta",
        "rest_of_season_minus_market_delta",
        "dynasty_minus_market_delta",
        "career_minus_market_delta",
        "rest_of_season_minus_next_game_delta",
        "dynasty_minus_rest_of_season_delta",
        "career_minus_dynasty_delta",
    ):
        value = _optional_num(source.get(column))
        if value is not None:
            context[column] = round(value, 2)
    market_percentile = _optional_num(
        source.get("market_percentile", source.get("horizon_market_percentile"))
    )
    if market_percentile is not None:
        context["horizon_market_percentile"] = round(market_percentile, 2)

    comparable = []
    for window, delta_column in _HORIZON_MARKET_WINDOWS:
        delta = _optional_num(source.get(delta_column))
        if delta is not None:
            comparable.append((window, round(delta, 2)))
    if comparable:
        window, delta = max(comparable, key=lambda item: abs(item[1]))
        context["horizon_market_disagreement_window"] = window
        context["horizon_market_disagreement_delta"] = delta
        context["horizon_market_disagreement_magnitude"] = round(abs(delta), 2)
        if delta > 0:
            context["horizon_market_disagreement_read"] = "clock_leads_market"
        elif delta < 0:
            context["horizon_market_disagreement_read"] = "market_leads_clock"
        else:
            context["horizon_market_disagreement_read"] = "near_market"
    return context


def _classify_action(row: pd.Series, current_roster: int) -> dict[str, Any]:
    roster_id = _int(row.get("roster_id"))
    own_player = bool(current_roster and roster_id == current_roster)
    position = str(row.get("position", ""))
    age = _num(row.get("age"))
    ppg = _num(row.get("projected_ppg"))
    market = _num(row.get("market_value"))
    normalized_market = _normalize_market(market)
    gap = _num(row.get("market_gap_score"))
    breakout = _num(row.get("breakout_score"))
    sell = _num(row.get("sell_score"))
    timeline = _num(row.get("timeline_fit_score"))
    confidence = str(row.get("confidence", "low")) or "low"
    availability_status = str(row.get("current_availability_status") or "").strip()

    if availability_status == "no_current_nfl_team":
        return _action(
            "conditional_watch",
            "Conditional Watch",
            4,
            max(10.0, normalized_market),
            "Sleeper lists no current NFL team. Historical production remains useful context, but there is no current weekly role to act on until a signing and role are confirmed.",
            "high: no current NFL team; historical baseline is conditional on signing",
            "low",
        )
    if confidence == "low" and ppg == 0:
        return _action("avoid_noise", "Avoid / Noise", 6, normalized_market, "The row lacks enough projection support to deserve action now (no baseline PPG, low confidence).", "high: sparse projection evidence", "low")
    if own_player and sell >= 45:
        return _action("sell_window", "Sell Window", 1, sell, f"Sell score of {sell:.0f} (threshold 45) at age {age:.0f} signals timing or age-based value risk -- shop this asset before it decays further.", "medium: do not force a weak offer", confidence)
    if own_player and position == "RB" and age >= 27:
        return _action("sell_window", "Sell Window", 1, max(45.0, sell), f"At age {age:.0f}, {ppg:.1f} baseline PPG of RB production is worth more to a contender than to a rebuild timeline right now.", "medium: market may discount age already", confidence)
    if str(row.get("signal_label", "")) == "role_uncertain_watch":
        return _action("role_check", "Role Check", 4, max(15.0, gap), "The baseline has production support, but age and market context do not establish a reliable current role. Verify the depth-chart path before treating the gap as an opportunity.", row.get("risk", "") or "medium: role is not confirmed", confidence)
    if own_player and ppg >= 12 and (position == "QB" or age <= 28) and sell < 40:
        return _action("core_hold", "Core Hold", 2, ppg * 3 + timeline, f"{ppg:.1f} baseline PPG with a {timeline:.0f} timeline-fit score makes this a roster pillar unless another manager overpays.", row.get("risk", ""), confidence)
    if own_player and ppg >= 10:
        return _action("price_check", "Price Check", 3, ppg * 3 + sell, f"{ppg:.1f} PPG is useful production (sell pressure only {sell:.0f}), but the best move is to learn the market price before deciding.", row.get("risk", ""), confidence)
    if not own_player and confidence != "low" and position in {"QB", "WR", "TE"} and age and age <= 25 and gap >= 30 and 0 < market <= 1500 and ppg >= 8:
        return _action("true_buy_low", "True Buy Low", 1, gap + breakout, f"Market gap score of {gap:.0f} (threshold 30) at {ppg:.1f} baseline PPG and age {age:.0f} suggests the price may lag the role or production.", row.get("risk", ""), confidence)
    if not own_player and confidence != "low" and (gap >= 18 or breakout >= 60):
        return _action("price_check", "Price Check", 3, gap + breakout * 0.4, f"Gap score of {gap:.0f} and breakout score of {breakout:.0f} make this interesting, but the market may already be pricing it efficiently.", row.get("risk", ""), confidence)
    if position in {"QB", "WR", "TE"} and age and age <= 25 and confidence != "high":
        return _action("deep_watch", "Deep Watch", 4, max(breakout, timeline), f"Age {age:.0f} timeline fits (breakout score {breakout:.0f}), but {confidence} confidence isn't strong enough yet for a confident move.", row.get("risk", ""), "low" if confidence == "low" else confidence)
    return _action("monitor", "Monitor", 5, max(gap, breakout, ppg), f"Gap {gap:.0f}, breakout {breakout:.0f}, {ppg:.1f} PPG -- track this player, but the current signal isn't action-ready.", row.get("risk", ""), confidence)


def _action(action_label: str, consumer_label: str, rank: int, score: float, why: str, risk: Any, confidence: Any) -> dict[str, Any]:
    return {
        "action_label": action_label,
        "consumer_label": consumer_label,
        "action_rank": rank,
        "action_score": round(float(score or 0), 2),
        "why": why,
        "risk": risk,
        "confidence": confidence,
    }


def _projection_edge_score(ppg: float, confidence: str, availability_status: str = "") -> float:
    multiplier = {"high": 1.0, "medium": 0.82, "low": 0.55}.get(confidence, 0.55)
    if availability_status == "no_current_nfl_team":
        # Historical production is useful context, but it cannot be treated as
        # current opportunity until the player has an NFL team again.
        multiplier *= 0.25
    return round(min(100.0, ppg * 4.2 * multiplier), 2)


def _market_gap_score(
    edge: float,
    normalized_market: float,
    market_record: dict[str, Any],
    role_uncertainty: str = "",
    projection_percentile: float | None = None,
    market_percentile: float | None = None,
) -> float:
    """Return signed projection-vs-market disagreement on a common scale.

    The old implementation subtracted raw market value from ``PPG * 4.2``.
    Those quantities are not calibrated to one another, so elite assets could
    look like enormous bargains. Percentiles compare each player with peers at
    the same position; missing or proxy markets remain unscored rather than
    pretending an internal estimate is an observed market.
    """

    if not market_record or _is_proxy_market(market_record) or market_percentile is None:
        base = 0.0
    elif projection_percentile is not None:
        base = projection_percentile - market_percentile
    else:
        base = 0.0
    # A recent per-game baseline is not a starter forecast.  Age plus a low
    # market value is a deterministic proxy for missing role/availability
    # context, so keep it visible as a watch rather than a false bargain.
    if role_uncertainty.startswith("high"):
        base *= 0.35
    elif role_uncertainty.startswith("medium"):
        base *= 0.70
    return round(base, 2)


def _timeline_fit_score(position: str, age: float, config: dict[str, Any]) -> float:
    direction = (config.get("strategy_profile") or {}).get("team_direction", "")
    if direction == "deep_rebuild":
        if position in {"QB", "WR", "TE"} and (not age or age <= 25):
            return 85.0
        if position in {"QB", "WR", "TE"} and age <= 28:
            return 65.0
        if position == "RB" and age >= 27:
            return 20.0
    return 50.0


def _breakout_score(position: str, age: float, ppg: float, gap: float, confidence: str, news_signal: str, opportunity_score: float = 0.0, role_uncertainty: str = "") -> float:
    score = max(0.0, gap) * 0.65 + min(45.0, ppg * 2.2)
    if position in PASS_CATCHERS and age and age <= 25:
        score += 16
    if position == "QB" and age and age <= 27:
        score += 10
    if "market_heat" in news_signal or "role_or_value_change" in news_signal:
        score += 8
    # Opportunity is the forward-looking signal validated by our own rolling-origin backtest
    # (AUC ~0.80 for rest-of-season finishes). A real breakout needs the usage to back it, so
    # opportunity above the league-median (>50) adds, well below it subtracts.
    if opportunity_score:
        score += (opportunity_score - 50.0) * 0.30
    if role_uncertainty.startswith("high"):
        score *= 0.55
    elif role_uncertainty.startswith("medium"):
        score *= 0.80
    if confidence == "low":
        score *= 0.65
    return round(max(0.0, min(100.0, score)), 2)


def _sell_score(
    position: str,
    age: float,
    ppg: float,
    normalized_market: float,
    roster_id: int,
    config: dict[str, Any],
    confidence: str,
    news_signal: str,
) -> float:
    current_roster = _int((config.get("current_team") or {}).get("roster_id"))
    score = 0.0
    if current_roster and roster_id == current_roster:
        score += 12
    if position == "RB" and age >= 27:
        score += 35
    if position in {"WR", "TE"} and age >= 29:
        score += 24
    if normalized_market >= 45 and ppg < 11:
        score += 22
    if normalized_market >= 30 and confidence == "low":
        score += 15
    if "sell_pressure" in news_signal or "injury_risk" in news_signal:
        score += 12
    return round(min(100.0, score), 2)


def _signal_label(breakout: float, sell: float, gap: float, ppg: float, confidence: str, role_uncertainty: str = "") -> str:
    if confidence == "low" and ppg == 0:
        return "missing_projection_watch"
    if role_uncertainty:
        return "role_uncertain_watch"
    if sell >= 55:
        return "sell_candidate"
    if breakout >= 65:
        return "breakout_target"
    if gap >= 35:
        return "buy_or_watch"
    if ppg >= 14:
        return "productive_hold"
    return "monitor"


def _signal_confidence(
    projection_confidence: str,
    market_record: dict[str, Any],
    availability_status: str = "",
) -> str:
    if availability_status == "no_current_nfl_team":
        return "low"
    if projection_confidence == "low":
        return "low"
    if not market_record:
        return "medium"
    if _is_proxy_market(market_record):
        return "medium"
    if _single_source_market(market_record):
        return "medium"
    return projection_confidence


def _risk(projection_confidence: str, market_record: dict[str, Any], sell_score: float, availability_note: str = "", role_uncertainty: str = "") -> str:
    if projection_confidence == "low":
        base = "high: sparse or missing projection history"
    elif not market_record:
        base = "medium: external market value unavailable"
    elif _is_proxy_market(market_record):
        base = "medium: external market value unavailable; internal proxy used"
    elif sell_score >= 55:
        base = "medium: timing matters before value decay"
    else:
        base = "medium: verify role and market price"
    notes = []
    if _single_source_market(market_record):
        notes.append("single-source market evidence")
    if role_uncertainty:
        notes.append(role_uncertainty)
    if availability_note and not availability_note.startswith("No current Sleeper injury flag"):
        notes.append(availability_note)
    return f"{base}; {'; '.join(notes)}" if notes else base


def _gap_label(score: float) -> str:
    if score >= 35:
        return "projection_value_gap"
    if score <= -15:
        return "market_rich"
    return "fair_or_unclear"


def _role_uncertainty(
    position: str,
    age: float,
    market_value: float,
    availability_status: str = "",
) -> str:
    """Flag when a baseline projection is especially vulnerable to role risk."""

    if availability_status == "no_current_nfl_team":
        return "high: no current NFL team; historical baseline is not a current-role forecast"
    if age >= 35:
        return "high: age/role uncertainty; baseline is not a starter forecast"
    if age >= 30 and market_value < 10:
        return "high: age/role uncertainty; baseline is not a starter forecast"
    if position == "RB" and age >= 29:
        return "medium: age/role uncertainty"
    return ""


def _need_fit_score(position: str, team: pd.Series) -> float:
    if position == "QB":
        return _need_score(team.get("need_qb"))
    if position == "RB":
        return _need_score(team.get("need_rb"))
    if position in PASS_CATCHERS:
        return _need_score(team.get("need_pass_catcher"))
    return 35.0


def _need_score(value: Any) -> float:
    return {"high": 82.0, "medium": 55.0, "low": 28.0}.get(str(value), 35.0)


def _evidence(
    projection: pd.Series,
    market_value: float,
    team_need: dict[str, Any],
    manager: dict[str, Any],
    news_signal: str,
    availability_note: str = "",
    role_uncertainty: str = "",
    projection_percentile: float | None = None,
    market_percentile: float | None = None,
    market_gap_status: str = "",
) -> str:
    return (
        f"baseline_ppg={projection.get('projected_ppg')}; points={projection.get('projected_fantasy_points')}; "
        f"projection={projection.get('projection_confidence')}; market={round(market_value, 2)}; "
        f"projection_percentile={_num_text(projection_percentile) if projection_percentile is not None else 'n/a'}; "
        f"market_percentile={_num_text(market_percentile) if market_percentile is not None else 'n/a'}; "
        f"market_gap_status={market_gap_status or 'not_calibrated'}; "
        f"team_shape={team_need.get('team_shape', '')}; manager={manager.get('plain_language_label', '')}; "
        f"news={news_signal or 'none'}; availability={availability_note or 'not recorded'}; "
        f"role_context={role_uncertainty or 'no additional age/role flag'}"
    )


def _join_trace(*parts: Any) -> str:
    return "; ".join(str(part) for part in parts if part not in ("", None))


def _player_value_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    if frame.empty:
        return values
    for _, row in frame.fillna("").iterrows():
        record = row.to_dict()
        if str(record.get("player_id", "")):
            values[str(record.get("player_id"))] = record
        if str(record.get("player_name", "")):
            values[str(record.get("player_name")).lower()] = record
    return values


def _market_value_map(
    external_frame: pd.DataFrame,
    inventory_frame: pd.DataFrame | None = None,
) -> dict[str, dict[str, Any]]:
    """Prefer external values and explicitly fill missing players from the asset ledger."""

    values = _player_value_map(external_frame)
    if inventory_frame is None or inventory_frame.empty:
        return values
    for _, row in inventory_frame.fillna("").iterrows():
        if str(row.get("asset_type", "player")).lower() != "player":
            continue
        player_id = str(row.get("asset_id", ""))
        player_name = str(row.get("asset_name", ""))
        if not player_id or player_id in values or (player_name and player_name.lower() in values):
            continue
        record = row.to_dict()
        record["player_id"] = player_id
        record["player_name"] = player_name
        record["market_source"] = "internal_proxy"
        values[player_id] = record
        if player_name:
            values[player_name.lower()] = record
    return values


def _values_by_position(frame: pd.DataFrame, value_column: str) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    if frame.empty or value_column not in frame.columns:
        return values
    for _, row in frame.fillna("").iterrows():
        position = str(row.get("position", "")).strip()
        value = _num(row.get(value_column))
        if position and value > 0:
            values.setdefault(position, []).append(value)
    return values


def _market_values_by_position(frame: pd.DataFrame) -> dict[str, list[float]]:
    """Return external market cohorts only; internal proxies never calibrate peers."""

    return _values_by_position(frame, "market_value")


def _percentile(value: float, cohort: list[float]) -> float | None:
    if not cohort:
        return None
    ordered = sorted(float(item) for item in cohort)
    less = sum(item < value for item in ordered)
    equal = sum(item == value for item in ordered)
    return round(((less + (equal / 2.0)) / len(ordered)) * 100.0, 2)


def _market_gap_status(
    market_record: dict[str, Any],
    market_percentile: float | None,
    market_gap: float | None = None,
) -> str:
    if not market_record:
        return "market_missing"
    if _is_proxy_market(market_record):
        return "proxy_market_not_calibrated"
    if market_percentile is None:
        return "market_cohort_sparse"
    if market_gap is not None and abs(market_gap) < 15:
        return "position_percentile_aligned"
    return "position_percentile_disagreement"


def _single_source_market(record: dict[str, Any]) -> bool:
    """Detect a one-source market row without treating it as consensus."""

    value_format = str(record.get("value_format", ""))
    if "consensus_sources=1" in value_format:
        return True
    try:
        return bool(record.get("source_count")) and int(float(record.get("source_count"))) <= 1
    except (TypeError, ValueError):
        return False


def _is_proxy_market(record: dict[str, Any]) -> bool:
    return (
        str(record.get("market_source", "")).lower() == "internal_proxy"
        or str(record.get("source_trace", "")) == "internal_proxy_player_value"
    )


def _age_map(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    selected: dict[str, dict[str, Any]] = {}
    for _, row in frame.fillna("").iterrows():
        player_id = str(row.get("player_id", ""))
        if player_id and _prefer_current_roster_row(selected.get(player_id), row.to_dict()):
            selected[player_id] = row.to_dict()
    return {player_id: _num(row.get("age")) for player_id, row in selected.items()}


def _availability_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "player_id" not in frame:
        return {}
    selected: dict[str, dict[str, Any]] = {}
    for _, row in frame.fillna("").iterrows():
        player_id = str(row.get("player_id", ""))
        if player_id and _prefer_current_roster_row(selected.get(player_id), row.to_dict()):
            selected[player_id] = row.to_dict()
    return selected


def _prefer_current_roster_row(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    """Prefer a current Sleeper snapshot over historical rows for player facts.

    The processed roster table intentionally contains multiple seasons. A plain
    dict comprehension lets whichever row happens to be last win, which can
    turn a current free-agent/injury state into ``historical_unavailable``.
    """

    if existing is None:
        return True
    existing_scope = str(existing.get("availability_scope") or "").strip()
    candidate_scope = str(candidate.get("availability_scope") or "").strip()
    if candidate_scope == "current_season_snapshot" and existing_scope != "current_season_snapshot":
        return True
    if candidate_scope != "current_season_snapshot" and existing_scope == "current_season_snapshot":
        return False
    try:
        return int(float(candidate.get("season") or 0)) >= int(float(existing.get("season") or 0))
    except (TypeError, ValueError):
        return False


def _availability_note(status: Any, body_part: Any) -> str:
    """Backward-compatible injury formatter for callers outside the signal loop."""

    injury_status = str(status or "").strip()
    body = str(body_part or "").strip()
    if injury_status:
        return f"{injury_status}{f' ({body})' if body else ''}; baseline projection does not adjust for availability"
    return "No current Sleeper injury flag; baseline projection"


def _row_map(frame: pd.DataFrame, key: str) -> dict[int, dict[str, Any]]:
    if frame.empty or key not in frame:
        return {}
    return {_int(row.get(key)): row.to_dict() for _, row in frame.fillna("").iterrows()}


def _opportunity_map(frame: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if frame is None or frame.empty or "player_id" not in frame:
        return {}
    return {str(row.get("player_id")): row.to_dict() for _, row in frame.fillna("").iterrows()}


def _scope_news_impact(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.DataFrame:
    """Keep news inside the authenticated league and current-season boundary.

    ``league_news_impact`` intentionally repeats a global Sleeper event for each
    league owner. News therefore cannot be reduced by player ID alone: roster
    IDs repeat across leagues, and a historical event can otherwise change a
    current signal. Blank legacy rows remain usable only when no identified
    scoped row exists.
    """

    if frame.empty:
        return frame.copy()
    result = frame.copy()
    context = config.get("context") if isinstance(config, Mapping) else None
    context = context if isinstance(context, Mapping) else {}
    season = context.get("season") or config.get("current_season", "")
    configured_leagues = config.get("leagues") if isinstance(config, Mapping) else {}
    league_id = (
        context.get("league_id")
        or config.get("league_id", "")
        or (configured_leagues.get(str(season), "") if isinstance(configured_leagues, Mapping) else "")
    )

    if league_id and "league_id" in result.columns:
        identified = result[result["league_id"].astype(str).str.strip() != ""]
        scoped = identified[identified["league_id"].map(lambda value: _same_identifier(value, league_id))]
        result = scoped if not scoped.empty else result[result["league_id"].astype(str).str.strip() == ""]

    if season and "season" in result.columns:
        identified = result[result["season"].astype(str).str.strip() != ""]
        scoped = identified[identified["season"].map(lambda value: _same_identifier(value, season))]
        result = scoped if not scoped.empty else result[result["season"].astype(str).str.strip() == ""]
    return result.reset_index(drop=True)


def _same_identifier(left: Any, right: Any) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except (TypeError, ValueError):
        return False


def _edge_confidence(score_confidence: str, news_confidences: set[str]) -> str:
    levels = {"low": 0, "medium": 1, "high": 2}
    observed = [levels.get(score_confidence, 0)] + [levels.get(value, 0) for value in news_confidences]
    level = min(observed) if observed else 0
    return {0: "low", 1: "medium", 2: "high"}[level]


def _num_text(value: Any) -> str:
    number = _num(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _news_map(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty:
        return {}
    signals: dict[str, list[str]] = {}
    for _, row in frame.fillna("").iterrows():
        player_id = str(row.get("player_id", ""))
        if player_id:
            signals.setdefault(player_id, []).append(str(row.get("impact_type", "")))
    return {player_id: ",".join(sorted(set(items))) for player_id, items in signals.items()}


def _normalize_market(value: float) -> float:
    """Return a canonical market value without guessing at source units.

    DynastyProcess ``value_2qb`` is normalized at ingestion.  Heuristics such
    as ``value > 100`` are unsafe here because canonical high-end values can
    legitimately exceed 100.
    """

    return max(0.0, value)


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


def _signal_columns() -> list[str]:
    return [
        "player_id",
        "player_name",
        "position",
        "age",
        "roster_id",
        "team_name",
        "current_availability_status",
        "projected_fantasy_points",
        "projected_ppg",
        "market_value",
        "projection_edge_score",
        "market_gap_score",
        "timeline_fit_score",
        "breakout_score",
        "sell_score",
        "opportunity_score",
        "xfp_regression_score",
        "role_trend_score",
        "fragility_score",
        "signal_label",
        "projection_percentile",
        "market_percentile",
        "market_gap_status",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    ]


def _breakout_columns() -> list[str]:
    return ["player_id", "player_name", "position", "current_availability_status", "current_team_name", "breakout_score", "projection_edge", "market_value", "evidence", "risk", "confidence", "source_trace"]


def _sell_columns() -> list[str]:
    return ["player_id", "player_name", "position", "current_availability_status", "current_team_name", "sell_score", "projection_risk", "market_value", "evidence", "risk", "confidence", "source_trace"]


def _gap_columns() -> list[str]:
    return ["player_id", "player_name", "position", "current_availability_status", "projected_fantasy_points", "projected_ppg", "market_value", "projection_percentile", "market_percentile", "market_gap_status", "gap_score", "gap_label", "evidence", "risk", "confidence", "source_trace"]


def _news_market_columns() -> list[str]:
    return [
        "player_id",
        "player_name",
        "position",
        "roster_id",
        "league_id",
        "season",
        "team_name",
        "news_direction",
        "edge_type",
        "news_impact",
        "news_event_count",
        "market_value",
        "projected_ppg",
        "market_gap_score",
        "sell_score",
        "news_market_edge_score",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    ]


def _fit_columns() -> list[str]:
    return ["roster_id", "team_name", "player_id", "player_name", "position", "timeline_fit_score", "need_fit_score", "liquidity_fit_score", "fit_label", "evidence", "risk", "confidence", "source_trace"]


def _action_columns() -> list[str]:
    return ["roster_id", "team_name", "player_id", "player_name", "position", "age", "current_availability_status", "action_label", "consumer_label", "action_rank", "action_score", "projected_ppg", "market_value", "why", "evidence", "risk", "confidence", "source_trace"]


def _counterparty_columns() -> list[str]:
    return [
        "target_roster_id",
        "target_team",
        "player_id",
        "player_name",
        "position",
        "target_team_lens",
        "target_horizon_fit_score",
        "active_horizon_fit_score",
        "horizon_fit_edge",
        "horizon_fit_read",
        "horizon_fit_basis",
        "horizon_model_version",
        *HORIZON_CONTEXT_COLUMNS,
        "our_value_score",
        "market_consensus_value",
        "estimated_owner_value_score",
        "trade_edge_score",
        "edge_type",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    ]


def _manager_pref_map(frame: pd.DataFrame) -> dict[tuple[int, str], dict[str, Any]]:
    if frame.empty:
        return {}
    rows: dict[tuple[int, str], dict[str, Any]] = {}
    for _, row in frame.fillna("").iterrows():
        key = (_int(row.get("roster_id")), str(row.get("position_group", "")))
        existing = rows.get(key, {})
        if _num(row.get("preference_score")) >= _num(existing.get("preference_score")):
            rows[key] = row.to_dict()
    return rows


def _owner_need_score(position: str, team: dict[str, Any]) -> float:
    if not team:
        return 25.0
    if position == "QB":
        return _need_score(team.get("need_qb"))
    if position == "RB":
        return _need_score(team.get("need_rb"))
    if position in PASS_CATCHERS:
        return _need_score(team.get("need_pass_catcher"))
    return 35.0


def _edge_type(edge_score: float, owner_preference: float, owner_confidence: str, ppg: float, market: float) -> str:
    if ppg <= 2 and market <= 5:
        return "do_not_chase"
    if owner_confidence == "low":
        return "insufficient_signal"
    if edge_score >= 18 and owner_preference < 55:
        return "we_may_value_more"
    if edge_score <= -18 or owner_preference >= 75:
        return "owner_may_overvalue"
    if abs(edge_score) <= 12 and ppg >= 8:
        return "mutual_fit"
    return "insufficient_signal"


def _counterparty_confidence(signal_confidence: str, owner_confidence: str, market: float) -> str:
    if signal_confidence == "low" or owner_confidence == "low" or market <= 0:
        return "low"
    if signal_confidence == "high" and owner_confidence == "high":
        return "high"
    return "medium"


def _counterparty_risk(edge_type: str, confidence: str, market: float) -> str:
    if confidence == "low":
        return "high: sparse manager, projection, or market evidence"
    if market <= 0:
        return "high: market consensus unavailable"
    if edge_type == "owner_may_overvalue":
        return "medium: current owner may price above our model"
    if edge_type == "we_may_value_more":
        return "medium: confirm current owner is actually open to selling"
    if edge_type == "do_not_chase":
        return "high: low-impact asset"
    return "medium: estimate only, not a trade quote"
