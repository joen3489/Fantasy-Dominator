from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import ANALYSIS_DIR


ANALYSIS_VERSION = "analysis_v1"
GENERATION_MODE = "deterministic_template"
PROMPT_VERSION = "analysis_prompt_contract_v1"
BANNED_CLAIMS = ("sent", "accepted", "executed", "submitted", "messaged", "offered")


def build_analysis_artifacts(
    analysis_dir: Path,
    dataframes: dict[str, pd.DataFrame],
    config: dict[str, Any],
    active_roster_id: int | None,
) -> dict[str, Any]:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    active_roster_id = active_roster_id or _configured_roster_id(config)
    teams = dataframes.get("teams", pd.DataFrame())
    active_team_name = _team_name(teams, active_roster_id)

    context_packets = build_context_packets(dataframes, active_roster_id, active_team_name, generated_at)
    target_theses = build_target_theses(dataframes, active_roster_id, active_team_name, generated_at)
    sell_theses = build_sell_theses(dataframes, active_roster_id, active_team_name, generated_at)
    trade_theses = build_trade_theses(dataframes, active_roster_id, active_team_name, generated_at)
    manager_dossier_items = build_manager_dossier_items(dataframes, generated_at)
    player_dossier_items = build_player_dossier_items(dataframes, generated_at)
    validations = validate_analysis_artifacts(target_theses, sell_theses, trade_theses)

    artifacts = {
        "analysis_context_packets.json": _json_artifact("analysis_context_packets", context_packets, generated_at, active_roster_id, active_team_name),
        "target_theses.json": _json_artifact("target_theses", target_theses, generated_at, active_roster_id, active_team_name),
        "sell_theses.json": _json_artifact("sell_theses", sell_theses, generated_at, active_roster_id, active_team_name),
        "trade_theses.json": _json_artifact("trade_theses", trade_theses, generated_at, active_roster_id, active_team_name),
        "manager_dossiers.json": _json_artifact("manager_dossiers", manager_dossier_items, generated_at, active_roster_id, active_team_name),
        "player_dossiers.json": _json_artifact("player_dossiers", player_dossier_items, generated_at, active_roster_id, active_team_name),
        "analysis_validation.json": _json_artifact("analysis_validation", validations, generated_at, active_roster_id, active_team_name),
    }
    for filename, payload in artifacts.items():
        _write_json(analysis_dir / filename, payload)

    markdown_artifacts = {
        "daily_gm_brief.md": build_daily_gm_brief(active_roster_id, active_team_name, target_theses, sell_theses, trade_theses, generated_at),
        "manager_dossiers.md": build_manager_dossiers(dataframes, generated_at),
        "news_impact_brief.md": build_news_impact_brief(dataframes, generated_at),
        # Sprint 17 per-section article fallbacks -- the LLM workflow overwrites these in place.
        "team_report.md": build_team_report(dataframes, active_roster_id, active_team_name, generated_at),
        "market_watch.md": build_market_watch(target_theses, sell_theses, generated_at),
        "trade_desk.md": build_trade_desk(trade_theses, active_team_name, generated_at),
        "manager_intel.md": build_manager_intel(dataframes, generated_at),
    }
    for filename, text in markdown_artifacts.items():
        (analysis_dir / filename).write_text(text, encoding="utf-8")

    return {
        "status": "generated" if validations["valid"] else "validation_failed",
        "generated_at": generated_at,
        "active_roster_id": active_roster_id,
        "active_team_name": active_team_name,
        "context_packet_count": len(context_packets),
        "target_thesis_count": len(target_theses),
        "sell_thesis_count": len(sell_theses),
        "trade_thesis_count": len(trade_theses),
        "manager_dossier_count": len(manager_dossier_items),
        "player_dossier_count": len(player_dossier_items),
        "validation_error_count": len(validations["errors"]),
        "source_tables": _source_tables(),
    }


def build_context_packets(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_team_name: str,
    generated_at: str,
) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    actions = dataframes.get("action_recommendations", pd.DataFrame())
    target_rows = _analysis_action_rows(actions, {"true_buy_low", "deep_watch"})
    sell_rows = _analysis_action_rows(actions, {"sell_window"})
    if not target_rows:
        target_rows = _rows(dataframes.get("breakout_candidates", pd.DataFrame()).head(12))
    if not sell_rows:
        sell_rows = _rows(dataframes.get("sell_candidates", pd.DataFrame()).head(12))
    for row in target_rows[:12]:
        packets.append(
            {
                "packet_id": f"target:{row.get('player_id', row.get('player_name', 'unknown'))}",
                "packet_type": "target_thesis",
                "roster_id": active_roster_id,
                "team_name": active_team_name,
                "subject_id": str(row.get("player_id", "")),
                "subject_name": row.get("player_name", ""),
                "source_tables": "action_recommendations;player_signal_scores;player_projection_season",
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "created_at": generated_at,
            }
        )
    for row in sell_rows[:12]:
        packets.append(
            {
                "packet_id": f"sell:{row.get('player_id', row.get('player_name', 'unknown'))}",
                "packet_type": "sell_thesis",
                "roster_id": active_roster_id,
                "team_name": active_team_name,
                "subject_id": str(row.get("player_id", "")),
                "subject_name": row.get("player_name", ""),
                "source_tables": "action_recommendations;sell_candidates;player_signal_scores;player_projection_season",
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "created_at": generated_at,
            }
        )
    return packets


def build_target_theses(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_team_name: str,
    generated_at: str,
) -> list[dict[str, Any]]:
    theses: list[dict[str, Any]] = []
    actions = _analysis_action_rows(dataframes.get("action_recommendations", pd.DataFrame()), {"true_buy_low", "deep_watch"})
    for index, row in enumerate(actions[:16], start=1):
        player = row.get("player_name", "Unknown player")
        team = row.get("team_name") or row.get("current_team_name", "")
        evidence = str(row.get("evidence", ""))
        risk = str(row.get("risk", "medium"))
        label = row.get("consumer_label", "Price Check")
        theses.append(
            {
                "thesis_id": f"target-{index:03d}",
                "roster_id": active_roster_id,
                "player_id": str(row.get("player_id", "")),
                "player_name": player,
                "position": row.get("position", ""),
                "team_name": team,
                "signal_label": row.get("action_label", "price_check"),
                "approach": _target_approach(row),
                "evidence": evidence,
                "risk": risk,
                "confidence": row.get("confidence", "medium"),
                "source_trace": row.get("source_trace", ""),
                "analysis_text": (
                    f"Action: {label}. Why: {row.get('why', 'The calibrated action model sees a decision point.')} "
                    f"Evidence: {evidence}. Risk: {risk}."
                ),
                "generated_at": generated_at,
            }
        )
    return theses


def build_sell_theses(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_team_name: str,
    generated_at: str,
) -> list[dict[str, Any]]:
    theses: list[dict[str, Any]] = []
    sells = _analysis_action_rows(dataframes.get("action_recommendations", pd.DataFrame()), {"sell_window"})
    for index, row in enumerate(sells[:16], start=1):
        player = row.get("player_name", "Unknown player")
        theses.append(
            {
                "thesis_id": f"sell-{index:03d}",
                "roster_id": active_roster_id,
                "player_id": str(row.get("player_id", "")),
                "player_name": player,
                "position": row.get("position", ""),
                "team_name": row.get("team_name") or row.get("current_team_name", active_team_name),
                "signal_label": row.get("action_label", "sell_window"),
                "sell_window": _sell_window(row),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", "medium"),
                "confidence": row.get("confidence", "medium"),
                "source_trace": row.get("source_trace", ""),
                "analysis_text": (
                    f"Action: Sell Window. Why: {row.get('why', 'The calibrated action model sees market-timing risk.')} "
                    f"Evidence: {row.get('evidence', '')}. Risk: {row.get('risk', 'medium')}."
                ),
                "generated_at": generated_at,
            }
        )
    return theses


def build_trade_theses(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_team_name: str,
    generated_at: str,
) -> list[dict[str, Any]]:
    behavior = dataframes.get("manager_behavior_signals", pd.DataFrame())
    opportunities = dataframes.get("opportunity_board", pd.DataFrame())
    targets = _rows(opportunities.head(12))
    theses: list[dict[str, Any]] = []
    managers = [row for row in _rows(behavior) if _int(row.get("roster_id")) != active_roster_id]
    for index, manager in enumerate(managers[:10], start=1):
        opportunity = targets[(index - 1) % len(targets)] if targets else {}
        manager_name = manager.get("team_name", "Unknown manager")
        manager_signal = manager.get("plain_language_label", "")
        theses.append(
            {
                "thesis_id": f"trade-{index:03d}",
                "roster_id": active_roster_id,
                "target_manager_roster_id": _int(manager.get("roster_id")),
                "target_manager_name": manager_name,
                "approach_type": _approach_type(manager_signal),
                "assets_to_discuss": opportunity.get("asset_in", "watchlist asset"),
                "manager_signal": manager_signal,
                "evidence": opportunity.get("evidence") or manager.get("evidence", ""),
                "risk": opportunity.get("risk", "medium"),
                "confidence": opportunity.get("confidence", "medium"),
                "source_trace": opportunity.get("source_trace") or "manager_behavior_signals;opportunity_board",
                "analysis_text": (
                    f"{manager_name} profiles as {manager_signal or 'unclear'}. "
                    f"Use that as a conversation angle around {opportunity.get('asset_in', 'watchlist assets')}, with the evidence row setting the guardrails."
                ),
                "generated_at": generated_at,
            }
        )
    return theses


def build_daily_gm_brief(
    active_roster_id: int | None,
    active_team_name: str,
    targets: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    generated_at: str,
) -> str:
    top_targets = targets[:5]
    top_sells = sells[:5]
    top_trades = trades[:5]
    lines = [
        _front_matter(
            {
                "artifact_type": "daily_gm_brief",
                "generated_at": generated_at,
                "roster_id": active_roster_id,
                "team_name": active_team_name,
                "model_mode": GENERATION_MODE,
                "source_tables": ", ".join(_source_tables()),
            }
        ),
        f"# Daily GM Brief: {active_team_name}",
        "",
        "This is analyst interpretation generated from deterministic projection, signal, news, and manager-behavior tables.",
        "",
        "## Target Theses",
        *_bullets(top_targets, "player_name", "analysis_text"),
        "",
        "## Sell Windows",
        *_bullets(top_sells, "player_name", "analysis_text"),
        "",
        "## Manager Angles",
        *_bullets(top_trades, "target_manager_name", "analysis_text"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_manager_dossiers(dataframes: dict[str, pd.DataFrame], generated_at: str) -> str:
    managers = _rows(dataframes.get("manager_behavior_signals", pd.DataFrame()))
    lines = [
        _front_matter(
            {
                "artifact_type": "manager_dossiers",
                "generated_at": generated_at,
                "source_tables": "manager_behavior_signals, manager_event_log, manager_profiles",
                "manager_count": len(managers),
            }
        ),
        "# Manager Dossiers",
        "",
        "Interpretation is grounded in observed trades, waivers, FAAB, and pick movement.",
    ]
    for manager in managers:
        lines.extend(
            [
                "",
                f"## {manager.get('team_name', 'Unknown manager')}",
                f"- Label: {manager.get('plain_language_label', 'unclear')}",
                f"- Evidence: {manager.get('evidence', '')}",
                f"- Trade activity score: {manager.get('trade_activity_score', 0)}",
                f"- Pick seller score: {manager.get('pick_seller_score', 0)}",
                f"- FAAB aggression score: {manager.get('faab_aggression_score', 0)}",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def build_news_impact_brief(dataframes: dict[str, pd.DataFrame], generated_at: str) -> str:
    news = _rows(dataframes.get("league_news_impact", pd.DataFrame()).head(20))
    lines = [
        _front_matter(
            {
                "artifact_type": "news_impact_brief",
                "generated_at": generated_at,
                "source_tables": "league_news_impact, news_events, player_news_matches",
                "news_event_count": len(dataframes.get("league_news_impact", pd.DataFrame())),
            }
        ),
        "# News Impact Brief",
        "",
        "News interpretation summarizes imported rows and player matches; it is not a sourced injury database by itself.",
        "",
        *_bullets(news, "player_name", "evidence"),
    ]
    return "\n".join(lines).strip() + "\n"


# --- Sprint 17: deterministic fallbacks for the per-section articles. Each mirrors the LLM
# article's headers so the browser renders both the same way, and each is overwritten in place
# by the LLM version when the article workflow succeeds. -----------------------------------

def _article_front_matter(key: str, generated_at: str, **extra: Any) -> str:
    return _front_matter({"artifact_type": key, "generated_at": generated_at, "model_mode": GENERATION_MODE, **extra})


def build_team_report(dataframes: dict[str, pd.DataFrame], active_roster_id: int | None, active_team_name: str, generated_at: str) -> str:
    players = [row for row in _rows(dataframes.get("player_dossiers", pd.DataFrame())) if _int(row.get("roster_id")) == _int(active_roster_id)]
    players.sort(key=lambda row: _num(row.get("market_value")), reverse=True)
    cornerstones = players[:4]
    shop = [row for row in players if "sell" in str(row.get("signal_label", "")).lower()][:4] or players[4:8]
    lines = [
        _article_front_matter("team_report", generated_at, roster_id=active_roster_id, team_name=active_team_name),
        f"# Your Team Report: {active_team_name}",
        "",
        "## Cornerstones",
        *_bullets(cornerstones, "player_name", "evidence"),
        "",
        "## Shop Candidates",
        *_bullets(shop, "player_name", "evidence"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_market_watch(targets: list[dict[str, Any]], sells: list[dict[str, Any]], generated_at: str) -> str:
    lines = [
        _article_front_matter("market_watch", generated_at),
        "# Market Watch",
        "",
        "## Buy-Low Targets",
        *_bullets(targets[:5], "player_name", "analysis_text"),
        "",
        "## Sell-High Windows",
        *_bullets(sells[:5], "player_name", "analysis_text"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_trade_desk(trades: list[dict[str, Any]], active_team_name: str, generated_at: str) -> str:
    best = trades[:5]
    lines = [
        _article_front_matter("trade_desk", generated_at, team_name=active_team_name),
        "# Trade Desk Read",
        "",
        "## Best Fits",
        *_bullets(best, "target_manager_name", "analysis_text"),
        "",
        "## Steer Clear",
        "- No steer-clear counterparties flagged from the current evidence.",
    ]
    return "\n".join(lines).strip() + "\n"


def build_manager_intel(dataframes: dict[str, pd.DataFrame], generated_at: str) -> str:
    cycles = _rows(dataframes.get("manager_cycle_profiles", pd.DataFrame()))
    contenders = [row for row in cycles if str(row.get("dynasty_cycle", "")) == "contender"]
    rebuilders = [row for row in cycles if str(row.get("dynasty_cycle", "")) == "rebuild"]
    lines = [
        _article_front_matter("manager_intel", generated_at, manager_count=len(cycles)),
        "# Manager Intel",
        "",
        "## Contenders",
        *_bullets(contenders, "team_name", "likely_needs"),
        "",
        "## Rebuilders",
        *_bullets(rebuilders, "team_name", "likely_sells"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_manager_dossier_items(dataframes: dict[str, pd.DataFrame], generated_at: str) -> list[dict[str, Any]]:
    cycles = _rows(dataframes.get("manager_cycle_profiles", pd.DataFrame()))
    tags = _rows(dataframes.get("manager_profile_tags", pd.DataFrame()))
    tags_by_id: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        tags_by_id.setdefault(str(tag.get("entity_id", "")), []).append(tag)
    items: list[dict[str, Any]] = []
    for index, cycle in enumerate(cycles, start=1):
        roster_id = str(cycle.get("roster_id", ""))
        selected_tags = tags_by_id.get(roster_id, [])[:6]
        tag_text = ", ".join(str(tag.get("tag", "")) for tag in selected_tags if tag.get("tag"))
        evidence = str(cycle.get("evidence", ""))
        risk = "medium: manager cycle is an estimated tendency, not intent"
        items.append(
            {
                "dossier_id": f"manager-{index:03d}",
                "roster_id": _int(roster_id),
                "team_name": cycle.get("team_name", ""),
                "dynasty_cycle": cycle.get("dynasty_cycle", ""),
                "tags": tag_text,
                "evidence": evidence,
                "risk": risk,
                "confidence": cycle.get("confidence", "low"),
                "source_trace": "manager_cycle_profiles;manager_profile_tags;manager_profiles;manager_event_log",
                "analysis_text": (
                    f"{cycle.get('team_name', 'This manager')} profiles as {cycle.get('dynasty_cycle', 'unclear')} "
                    f"with {cycle.get('trade_temperature', 'unknown trade activity')} and {cycle.get('pick_posture', 'unclear pick posture')}. "
                    f"Tags: {tag_text or 'none'}. Evidence: {evidence}."
                ),
                "generated_at": generated_at,
            }
        )
    return items


def build_player_dossier_items(dataframes: dict[str, pd.DataFrame], generated_at: str) -> list[dict[str, Any]]:
    dossiers = _rows(dataframes.get("player_dossiers", pd.DataFrame()).head(120))
    tags = _rows(dataframes.get("player_profile_tags", pd.DataFrame()))
    tags_by_id: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        tags_by_id.setdefault(str(tag.get("entity_id", "")), []).append(tag)
    items: list[dict[str, Any]] = []
    for index, player in enumerate(dossiers, start=1):
        player_id = str(player.get("player_id", ""))
        selected_tags = tags_by_id.get(player_id, [])[:6]
        tag_text = ", ".join(str(tag.get("tag", "")) for tag in selected_tags if tag.get("tag"))
        evidence = (
            f"ppg={player.get('projected_ppg', 0)}; market={player.get('market_value', 0)}; "
            f"signal={player.get('signal_label', '')}; news={player.get('news_impact', '')}; transactions={player.get('transaction_count', 0)}"
        )
        items.append(
            {
                "dossier_id": f"player-{index:03d}",
                "roster_id": _int(player.get("roster_id")),
                "team_name": player.get("team_name", ""),
                "player_id": player_id,
                "player_name": player.get("player_name", ""),
                "position": player.get("position", ""),
                "tags": tag_text,
                "evidence": evidence,
                "risk": "medium: deterministic player tag, not a guaranteed outcome",
                "confidence": player.get("projection_confidence", "low"),
                "source_trace": player.get("source_trace", "") or "player_dossiers;player_profile_tags",
                "analysis_text": (
                    f"{player.get('player_name', 'This player')} carries tags {tag_text or 'none'} from projection, market, news, "
                    f"and league transaction signals. Evidence: {evidence}."
                ),
                "generated_at": generated_at,
            }
        )
    return items


def validate_analysis_artifacts(*artifact_lists: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    required = {"evidence", "risk", "confidence", "source_trace", "analysis_text"}
    for artifact_list in artifact_lists:
        for item in artifact_list:
            missing = [field for field in required if str(item.get(field, "")) == ""]
            if missing:
                errors.append(f"{item.get('thesis_id', 'unknown')} missing {','.join(missing)}")
            text = " ".join(str(item.get(field, "")) for field in ("analysis_text", "evidence", "risk")).lower()
            banned = [claim for claim in BANNED_CLAIMS if f" {claim} " in f" {text} "]
            if banned:
                errors.append(f"{item.get('thesis_id', 'unknown')} contains banned claim {','.join(banned)}")
    return {"valid": not errors, "errors": errors}


def _json_artifact(
    artifact_type: str,
    items: list[dict[str, Any]] | dict[str, Any],
    generated_at: str,
    roster_id: int | None,
    team_name: str,
) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "analysis_version": ANALYSIS_VERSION,
        "generation_mode": GENERATION_MODE,
        "prompt_version": PROMPT_VERSION,
        "generated_at": generated_at,
        "roster_id": roster_id,
        "team_name": team_name,
        "source_tables": _source_tables(),
        "items": items if isinstance(items, list) else [items],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return frame.fillna("").to_dict(orient="records")


def _team_name(teams: pd.DataFrame, roster_id: int | None) -> str:
    if teams.empty or roster_id is None:
        return "Unknown team"
    for row in _rows(teams):
        if _int(row.get("roster_id")) == roster_id:
            return str(row.get("team_name") or row.get("display_name") or "Unknown team")
    return "Unknown team"


def _configured_roster_id(config: dict[str, Any]) -> int | None:
    return _int((config.get("current_team") or {}).get("roster_id")) or None


def _target_approach(row: dict[str, Any]) -> str:
    position = str(row.get("position", ""))
    if position in {"WR", "TE"}:
        return "ask as young pass-catcher timeline fit"
    if position == "QB":
        return "test price as scarce long-window production"
    return "monitor market before making an aggressive move"


def _sell_window(row: dict[str, Any]) -> str:
    position = str(row.get("position", ""))
    if position == "RB":
        return "shop into contender demand before role or age discount grows"
    return "test whether market price is stronger than projected role"


def _approach_type(manager_signal: Any) -> str:
    signal = str(manager_signal).lower()
    if "pick seller" in signal:
        return "pick reacquisition or future pick probe"
    if "faab" in signal or "waiver" in signal:
        return "churn and depth conversation"
    if "contender" in signal or "win-now" in signal:
        return "veteran production for future value"
    return "price discovery"


def _front_matter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _bullets(rows: list[dict[str, Any]], title_key: str, text_key: str) -> list[str]:
    if not rows:
        return ["- No high-signal rows available."]
    return [f"- {row.get(title_key, 'Unknown')}: {row.get(text_key, '')}" for row in rows]


def _source_tables() -> list[str]:
    return [
        "action_recommendations",
        "player_projection_season",
        "player_signal_scores",
        "player_dossiers",
        "player_profile_tags",
        "breakout_candidates",
        "sell_candidates",
        "league_news_impact",
        "manager_behavior_signals",
        "manager_cycle_profiles",
        "manager_profile_tags",
        "opportunity_board",
    ]


def _analysis_action_rows(frame: pd.DataFrame, labels: set[str]) -> list[dict[str, Any]]:
    rows = _rows(frame)
    filtered = [row for row in rows if str(row.get("action_label", "")) in labels]
    return sorted(filtered, key=lambda row: (_int(row.get("action_rank")), -_num(row.get("action_score"))))


def _int(value: Any) -> int:
    try:
        if value in ("", None) or pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _num(value: Any) -> float:
    try:
        if value in ("", None) or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_default_analysis_artifacts(dataframes: dict[str, pd.DataFrame], config: dict[str, Any], active_roster_id: int | None) -> dict[str, Any]:
    return build_analysis_artifacts(ANALYSIS_DIR, dataframes, config, active_roster_id)
