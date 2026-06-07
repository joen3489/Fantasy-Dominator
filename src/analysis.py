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
    validations = validate_analysis_artifacts(target_theses, sell_theses, trade_theses)

    artifacts = {
        "analysis_context_packets.json": _json_artifact("analysis_context_packets", context_packets, generated_at, active_roster_id, active_team_name),
        "target_theses.json": _json_artifact("target_theses", target_theses, generated_at, active_roster_id, active_team_name),
        "sell_theses.json": _json_artifact("sell_theses", sell_theses, generated_at, active_roster_id, active_team_name),
        "trade_theses.json": _json_artifact("trade_theses", trade_theses, generated_at, active_roster_id, active_team_name),
        "analysis_validation.json": _json_artifact("analysis_validation", validations, generated_at, active_roster_id, active_team_name),
    }
    for filename, payload in artifacts.items():
        _write_json(analysis_dir / filename, payload)

    markdown_artifacts = {
        "daily_gm_brief.md": build_daily_gm_brief(active_roster_id, active_team_name, target_theses, sell_theses, trade_theses, generated_at),
        "manager_dossiers.md": build_manager_dossiers(dataframes, generated_at),
        "news_impact_brief.md": build_news_impact_brief(dataframes, generated_at),
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
    for row in _rows(dataframes.get("breakout_candidates", pd.DataFrame()).head(12)):
        packets.append(
            {
                "packet_id": f"target:{row.get('player_id', row.get('player_name', 'unknown'))}",
                "packet_type": "target_thesis",
                "roster_id": active_roster_id,
                "team_name": active_team_name,
                "subject_id": str(row.get("player_id", "")),
                "subject_name": row.get("player_name", ""),
                "source_tables": "breakout_candidates;player_signal_scores;player_projection_season",
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "created_at": generated_at,
            }
        )
    for row in _rows(dataframes.get("sell_candidates", pd.DataFrame()).head(12)):
        packets.append(
            {
                "packet_id": f"sell:{row.get('player_id', row.get('player_name', 'unknown'))}",
                "packet_type": "sell_thesis",
                "roster_id": active_roster_id,
                "team_name": active_team_name,
                "subject_id": str(row.get("player_id", "")),
                "subject_name": row.get("player_name", ""),
                "source_tables": "sell_candidates;player_signal_scores;player_projection_season",
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
    breakouts = dataframes.get("breakout_candidates", pd.DataFrame())
    for index, row in enumerate(_rows(breakouts.head(16)), start=1):
        player = row.get("player_name", "Unknown player")
        team = row.get("current_team_name", "")
        score = row.get("breakout_score", "")
        evidence = str(row.get("evidence", ""))
        risk = str(row.get("risk", "medium"))
        theses.append(
            {
                "thesis_id": f"target-{index:03d}",
                "roster_id": active_roster_id,
                "player_id": str(row.get("player_id", "")),
                "player_name": player,
                "position": row.get("position", ""),
                "team_name": team,
                "signal_label": "breakout_target",
                "approach": _target_approach(row),
                "evidence": evidence,
                "risk": risk,
                "confidence": row.get("confidence", "medium"),
                "source_trace": row.get("source_trace", ""),
                "analysis_text": (
                    f"{player} is a target because the signal layer found a breakout score of {score}. "
                    f"The clean angle is to price the player before the league fully reacts, while checking the evidence row for projection, market, and news inputs."
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
    sells = dataframes.get("sell_candidates", pd.DataFrame())
    for index, row in enumerate(_rows(sells.head(16)), start=1):
        player = row.get("player_name", "Unknown player")
        score = row.get("sell_score", "")
        theses.append(
            {
                "thesis_id": f"sell-{index:03d}",
                "roster_id": active_roster_id,
                "player_id": str(row.get("player_id", "")),
                "player_name": player,
                "position": row.get("position", ""),
                "team_name": row.get("current_team_name", active_team_name),
                "signal_label": "sell_candidate",
                "sell_window": _sell_window(row),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", "medium"),
                "confidence": row.get("confidence", "medium"),
                "source_trace": row.get("source_trace", ""),
                "analysis_text": (
                    f"{player} is a sell-window candidate because the model assigned a sell score of {score}. "
                    f"The thesis is about exploring market price and timing, not forcing a move."
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
        "player_projection_season",
        "player_signal_scores",
        "breakout_candidates",
        "sell_candidates",
        "league_news_impact",
        "manager_behavior_signals",
        "opportunity_board",
    ]


def _int(value: Any) -> int:
    try:
        if value in ("", None) or pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def build_default_analysis_artifacts(dataframes: dict[str, pd.DataFrame], config: dict[str, Any], active_roster_id: int | None) -> dict[str, Any]:
    return build_analysis_artifacts(ANALYSIS_DIR, dataframes, config, active_roster_id)
