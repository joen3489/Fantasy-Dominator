from __future__ import annotations

from typing import Any

import pandas as pd


PASS_CATCHERS = {"WR", "TE"}


def build_signal_tables(
    projections_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    player_market_values_df: pd.DataFrame,
    team_needs_df: pd.DataFrame,
    manager_behavior_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    scores = build_player_signal_scores(
        projections_df,
        roster_players_df,
        player_market_values_df,
        team_needs_df,
        manager_behavior_df,
        news_impact_df,
        config,
    )
    gaps = build_projection_market_gaps(scores)
    breakouts = build_breakout_candidates(scores)
    sells = build_sell_candidates(scores, config)
    fits = build_team_fit_scores(scores, team_needs_df, config)
    actions = build_action_recommendations(scores, config)
    return {
        "player_signal_scores": scores,
        "breakout_candidates": breakouts,
        "sell_candidates": sells,
        "projection_market_gaps": gaps,
        "team_fit_scores": fits,
        "action_recommendations": actions,
    }


def build_player_signal_scores(
    projections_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    player_market_values_df: pd.DataFrame,
    team_needs_df: pd.DataFrame,
    manager_behavior_df: pd.DataFrame,
    news_impact_df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    if projections_df.empty:
        return pd.DataFrame([], columns=_signal_columns())

    market = _player_value_map(player_market_values_df)
    ages = _age_map(roster_players_df)
    needs = _row_map(team_needs_df, "roster_id")
    behavior = _row_map(manager_behavior_df, "roster_id")
    news = _news_map(news_impact_df)
    rows: list[dict[str, Any]] = []

    for _, projection in projections_df.fillna("").iterrows():
        player_id = str(projection.get("player_id", ""))
        player_name = str(projection.get("player_name", ""))
        roster_id = _int(projection.get("roster_id"))
        position = str(projection.get("position", ""))
        age = ages.get(player_id, 0.0)
        market_record = market.get(player_id) or market.get(player_name.lower()) or {}
        market_value = _num(market_record.get("market_value"))
        normalized_market = _normalize_market(market_value)
        ppg = _num(projection.get("projected_ppg"))
        points = _num(projection.get("projected_fantasy_points"))
        projection_confidence = str(projection.get("projection_confidence", "low")) or "low"
        team_need = needs.get(roster_id, {})
        manager = behavior.get(roster_id, {})
        news_signal = news.get(player_id, "")

        projection_edge = _projection_edge_score(ppg, projection_confidence)
        market_gap = _market_gap_score(projection_edge, normalized_market, market_record)
        timeline_fit = _timeline_fit_score(position, age, config)
        breakout = _breakout_score(position, age, ppg, market_gap, projection_confidence, news_signal)
        sell = _sell_score(position, age, ppg, normalized_market, roster_id, config, projection_confidence, news_signal)
        label = _signal_label(breakout, sell, market_gap, ppg, projection_confidence)
        confidence = _signal_confidence(projection_confidence, market_record)
        source_trace = _join_trace(projection.get("source_trace", ""), market_record.get("source_trace", ""), news_signal)

        rows.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "position": position,
                "age": age,
                "roster_id": roster_id,
                "team_name": projection.get("team_name", ""),
                "projected_fantasy_points": round(points, 2),
                "projected_ppg": round(ppg, 2),
                "market_value": round(market_value, 2),
                "projection_edge_score": projection_edge,
                "market_gap_score": market_gap,
                "timeline_fit_score": timeline_fit,
                "breakout_score": breakout,
                "sell_score": sell,
                "signal_label": label,
                "evidence": _evidence(projection, market_value, team_need, manager, news_signal),
                "risk": _risk(projection_confidence, market_record, sell),
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
        rows.append(
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "projected_fantasy_points": row.get("projected_fantasy_points", 0),
                "projected_ppg": row.get("projected_ppg", 0),
                "market_value": row.get("market_value", 0),
                "gap_score": row.get("market_gap_score", 0),
                "gap_label": _gap_label(_num(row.get("market_gap_score"))),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_gap_columns()).sort_values("gap_score", ascending=False)


def build_breakout_candidates(scores_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    candidates = scores_df[scores_df.get("breakout_score", pd.Series(dtype=float)) >= 45] if not scores_df.empty else pd.DataFrame()
    for _, row in candidates.fillna("").iterrows():
        rows.append(
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
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
    candidates = candidates[candidates.get("sell_score", pd.Series(dtype=float)) >= 35] if not candidates.empty else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, row in candidates.fillna("").iterrows():
        rows.append(
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
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
            position = str(player.get("position", ""))
            timeline = _timeline_fit_score(position, _num(player.get("age")), config)
            need = _need_fit_score(position, team)
            liquidity = min(100.0, _num(player.get("market_value")) / 100 if _num(player.get("market_value")) > 100 else _num(player.get("market_value")))
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

    if confidence == "low" and ppg == 0:
        return _action("avoid_noise", "Avoid / Noise", 6, normalized_market, "The row lacks enough projection support to deserve action now.", "high: sparse projection evidence", "low")
    if own_player and sell >= 45:
        return _action("sell_window", "Sell Window", 1, sell, "Shop this asset while the model sees timing or age-based value risk.", "medium: do not force a weak offer", confidence)
    if own_player and position == "RB" and age >= 27:
        return _action("sell_window", "Sell Window", 1, max(45.0, sell), "Aging RB production is more valuable to contenders than to a rebuild timeline.", "medium: market may discount age already", confidence)
    if own_player and ppg >= 12 and (position == "QB" or age <= 28) and sell < 40:
        return _action("core_hold", "Core Hold", 2, ppg * 3 + timeline, "Keep this player as a roster pillar unless another manager overpays.", row.get("risk", ""), confidence)
    if own_player and ppg >= 10:
        return _action("price_check", "Price Check", 3, ppg * 3 + sell, "Useful production, but the best move is to learn the market price before deciding.", row.get("risk", ""), confidence)
    if not own_player and confidence != "low" and position in {"QB", "WR", "TE"} and age and age <= 25 and gap >= 30 and 0 < market <= 1500 and ppg >= 8:
        return _action("true_buy_low", "True Buy Low", 1, gap + breakout, "Projection and market inputs suggest the price may lag the role or production.", row.get("risk", ""), confidence)
    if not own_player and confidence != "low" and (gap >= 18 or breakout >= 60):
        return _action("price_check", "Price Check", 3, gap + breakout * 0.4, "The player is interesting, but the market may already be efficient.", row.get("risk", ""), confidence)
    if position in {"QB", "WR", "TE"} and age and age <= 25 and confidence != "high":
        return _action("deep_watch", "Deep Watch", 4, max(breakout, timeline), "Young timeline fit, but the evidence is not strong enough for a confident move.", row.get("risk", ""), "low" if confidence == "low" else confidence)
    return _action("monitor", "Monitor", 5, max(gap, breakout, ppg), "Track this player, but do not treat the current signal as action-ready.", row.get("risk", ""), confidence)


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


def _projection_edge_score(ppg: float, confidence: str) -> float:
    multiplier = {"high": 1.0, "medium": 0.82, "low": 0.55}.get(confidence, 0.55)
    return round(min(100.0, ppg * 4.2 * multiplier), 2)


def _market_gap_score(edge: float, normalized_market: float, market_record: dict[str, Any]) -> float:
    if not market_record:
        return round(edge * 0.65, 2)
    return round(edge - normalized_market * 0.38, 2)


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


def _breakout_score(position: str, age: float, ppg: float, gap: float, confidence: str, news_signal: str) -> float:
    score = max(0.0, gap) * 0.65 + min(45.0, ppg * 2.2)
    if position in PASS_CATCHERS and age and age <= 25:
        score += 16
    if position == "QB" and age and age <= 27:
        score += 10
    if "market_heat" in news_signal or "role_or_value_change" in news_signal:
        score += 8
    if confidence == "low":
        score *= 0.65
    return round(min(100.0, score), 2)


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


def _signal_label(breakout: float, sell: float, gap: float, ppg: float, confidence: str) -> str:
    if confidence == "low" and ppg == 0:
        return "missing_projection_watch"
    if sell >= 55:
        return "sell_candidate"
    if breakout >= 65:
        return "breakout_target"
    if gap >= 35:
        return "buy_or_watch"
    if ppg >= 14:
        return "productive_hold"
    return "monitor"


def _signal_confidence(projection_confidence: str, market_record: dict[str, Any]) -> str:
    if projection_confidence == "low":
        return "low"
    if not market_record:
        return "medium"
    return projection_confidence


def _risk(projection_confidence: str, market_record: dict[str, Any], sell_score: float) -> str:
    if projection_confidence == "low":
        return "high: sparse or missing projection history"
    if not market_record:
        return "medium: external market value unavailable"
    if sell_score >= 55:
        return "medium: timing matters before value decay"
    return "medium: verify role and market price"


def _gap_label(score: float) -> str:
    if score >= 35:
        return "projection_value_gap"
    if score <= -15:
        return "market_rich"
    return "fair_or_unclear"


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


def _evidence(projection: pd.Series, market_value: float, team_need: dict[str, Any], manager: dict[str, Any], news_signal: str) -> str:
    return (
        f"ppg={projection.get('projected_ppg')}; points={projection.get('projected_fantasy_points')}; "
        f"projection={projection.get('projection_confidence')}; market={round(market_value, 2)}; "
        f"team_shape={team_need.get('team_shape', '')}; manager={manager.get('plain_language_label', '')}; news={news_signal or 'none'}"
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


def _age_map(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    return {str(row.get("player_id", "")): _num(row.get("age")) for _, row in frame.fillna("").iterrows()}


def _row_map(frame: pd.DataFrame, key: str) -> dict[int, dict[str, Any]]:
    if frame.empty or key not in frame:
        return {}
    return {_int(row.get(key)): row.to_dict() for _, row in frame.fillna("").iterrows()}


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
    return value / 100 if value > 100 else value


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
        "projected_fantasy_points",
        "projected_ppg",
        "market_value",
        "projection_edge_score",
        "market_gap_score",
        "timeline_fit_score",
        "breakout_score",
        "sell_score",
        "signal_label",
        "evidence",
        "risk",
        "confidence",
        "source_trace",
    ]


def _breakout_columns() -> list[str]:
    return ["player_id", "player_name", "position", "current_team_name", "breakout_score", "projection_edge", "market_value", "evidence", "risk", "confidence", "source_trace"]


def _sell_columns() -> list[str]:
    return ["player_id", "player_name", "position", "current_team_name", "sell_score", "projection_risk", "market_value", "evidence", "risk", "confidence", "source_trace"]


def _gap_columns() -> list[str]:
    return ["player_id", "player_name", "position", "projected_fantasy_points", "projected_ppg", "market_value", "gap_score", "gap_label", "evidence", "risk", "confidence", "source_trace"]


def _fit_columns() -> list[str]:
    return ["roster_id", "team_name", "player_id", "player_name", "position", "timeline_fit_score", "need_fit_score", "liquidity_fit_score", "fit_label", "evidence", "risk", "confidence", "source_trace"]


def _action_columns() -> list[str]:
    return ["roster_id", "team_name", "player_id", "player_name", "position", "age", "action_label", "consumer_label", "action_rank", "action_score", "projected_ppg", "market_value", "why", "evidence", "risk", "confidence", "source_trace"]
