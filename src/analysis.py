from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .personas import normalize_writer_preferences, persona_metadata
from .utils import ANALYSIS_DIR


ANALYSIS_VERSION = "analysis_v1"
GENERATION_MODE = "deterministic_template"
PROMPT_VERSION = "analysis_prompt_contract_v1"
FALLBACK_ARTICLE_SCHEMA_VERSION = "deterministic_fallback_v2"
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
    writer_preferences = normalize_writer_preferences(config.get("writer_preferences"))

    context_packets = build_context_packets(dataframes, active_roster_id, active_team_name, generated_at)
    target_theses = build_target_theses(dataframes, active_roster_id, active_team_name, generated_at)
    sell_theses = build_sell_theses(dataframes, active_roster_id, active_team_name, generated_at)
    trade_theses = build_trade_theses(dataframes, active_roster_id, active_team_name, generated_at)
    previous_manager_items = _load_prior_items(analysis_dir / "manager_dossiers.json")
    manager_dossier_items = build_manager_dossier_items(dataframes, generated_at, previous_manager_items)
    player_dossier_items = build_player_dossier_items(dataframes, generated_at)
    validations = validate_analysis_artifacts(target_theses, sell_theses, trade_theses)

    artifacts = {
        "analysis_context_packets.json": _json_artifact("analysis_context_packets", context_packets, generated_at, active_roster_id, active_team_name),
        "target_theses.json": _json_artifact("target_theses", target_theses, generated_at, active_roster_id, active_team_name),
        "sell_theses.json": _json_artifact("sell_theses", sell_theses, generated_at, active_roster_id, active_team_name),
        "trade_theses.json": _json_artifact("trade_theses", trade_theses, generated_at, active_roster_id, active_team_name),
        "manager_dossiers.json": _json_artifact(
            "manager_dossiers",
            manager_dossier_items,
            generated_at,
            active_roster_id,
            active_team_name,
            metadata=_dossier_receipt(manager_dossier_items),
        ),
        "player_dossiers.json": _json_artifact("player_dossiers", player_dossier_items, generated_at, active_roster_id, active_team_name),
        "analysis_validation.json": _json_artifact("analysis_validation", validations, generated_at, active_roster_id, active_team_name),
    }
    for filename, payload in artifacts.items():
        _write_json(analysis_dir / filename, payload)

    markdown_artifacts = {
        "daily_gm_brief.md": build_daily_gm_brief(
            active_roster_id,
            active_team_name,
            target_theses,
            sell_theses,
            trade_theses,
            generated_at,
            writer_preferences,
        ),
        "manager_dossiers.md": build_manager_dossiers(dataframes, generated_at),
        "news_impact_brief.md": build_news_impact_brief(dataframes, generated_at),
        # Sprint 17 per-section article fallbacks -- the LLM workflow overwrites these in place.
        "team_report.md": build_team_report(dataframes, active_roster_id, active_team_name, generated_at, writer_preferences),
        "market_watch.md": build_market_watch(target_theses, sell_theses, generated_at, writer_preferences),
        "trade_desk.md": build_trade_desk(trade_theses, active_team_name, generated_at, writer_preferences),
        "manager_intel.md": build_manager_intel(dataframes, generated_at, writer_preferences),
    }
    fallback_inputs = {
        "daily_brief": (
            target_theses[:5] + sell_theses[:5] + trade_theses[:5],
            ["target_theses", "sell_theses", "trade_theses"],
        ),
        "team_report": (
            [
                row
                for row in _rows(dataframes.get("player_dossiers", pd.DataFrame()))
                if _int(row.get("roster_id")) == _int(active_roster_id)
            ],
            ["player_dossiers", "roster_players", "player_projection_season", "player_signal_scores"],
        ),
        "market_watch": (
            target_theses[:12] + sell_theses[:12],
            ["target_theses", "sell_theses", "player_opportunity_scores"],
        ),
        "trade_desk": (
            trade_theses[:12],
            ["trade_theses", "manager_profiles", "manager_valuation_profiles", "counterparty_trade_edges"],
        ),
        "manager_intel": (
            manager_dossier_items[:14],
            [
                "manager_dossiers",
                "manager_profiles",
                "manager_event_log",
                "manager_season_history",
                "manager_cycle_profiles",
            ],
        ),
    }
    article_filenames = {
        "daily_brief": "daily_gm_brief.md",
        "team_report": "team_report.md",
        "market_watch": "market_watch.md",
        "trade_desk": "trade_desk.md",
        "manager_intel": "manager_intel.md",
    }
    for article_key, (rows, source_tables) in fallback_inputs.items():
        filename = article_filenames[article_key]
        markdown_artifacts[filename] = _decorate_deterministic_article(
            article_key,
            markdown_artifacts[filename],
            rows,
            source_tables,
            active_roster_id,
            active_team_name,
            writer_preferences,
        )
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
        "manager_dossier_receipt": _dossier_receipt(manager_dossier_items),
        "player_dossier_count": len(player_dossier_items),
        "validation_error_count": len(validations["errors"]),
        "source_tables": _source_tables(),
    }


def _decorate_deterministic_article(
    article_key: str,
    text: str,
    evidence_rows: list[dict[str, Any]],
    source_tables: list[str],
    roster_id: int | None,
    team_name: str,
    writer_preferences: dict[str, Any] | None,
) -> str:
    """Give deterministic fallback articles the same inspectable receipt shape as LLM output."""

    reporter = persona_metadata(writer_preferences, article_key)
    evidence_ids = _deterministic_evidence_ids(article_key, evidence_rows)
    source_ids = _deterministic_source_ids(evidence_rows, source_tables)
    related_entities = _deterministic_related_entities(evidence_rows)
    confidence = _deterministic_confidence(evidence_rows)
    fingerprint = _fingerprint(
        {
            "article_key": article_key,
            "roster_id": roster_id,
            "team_name": team_name,
            "source_tables": source_tables,
            "rows": _without_generated_at(evidence_rows),
        }
    )
    source_quality = (
        "multi_source" if len(source_ids) > 1 else "single_source" if source_ids else "unattributed"
    )
    editorial_fields = _deterministic_fallback_editorial_fields(
        article_key,
        reporter["name"],
        evidence_rows,
        evidence_ids,
        source_ids,
        roster_id,
        team_name,
    )
    structured = {
        "fallback_schema_version": FALLBACK_ARTICLE_SCHEMA_VERSION,
        "headline": _article_headline(text, article_key),
        **editorial_fields,
        "risk": "Deterministic fallback content is not a newly generated analyst article.",
        "confidence": confidence,
        "related_entities": related_entities,
        "evidence_ids": evidence_ids,
        "evidence_count": len(evidence_ids),
        "source_ids": source_ids,
        "source_count": len(source_ids),
        "source_quality": source_quality,
        "source_tables": source_tables,
    }
    source_receipt = {
        "source_ids": source_ids,
        "source_count": len(source_ids),
        "quality": source_quality,
        "scope": "deterministic_validated_evidence",
        "tables": source_tables,
    }
    fields = {
        "reporter_persona": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "fallback_schema_version": FALLBACK_ARTICLE_SCHEMA_VERSION,
        "evidence_fingerprint": fingerprint,
        "fallback_reason": "No current LLM artifact; deterministic fallback from validated evidence.",
        "article_payload_json": json.dumps(structured, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "source_receipt_json": json.dumps(source_receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }
    return _replace_front_matter_fields(text, fields)


def upgrade_deterministic_article_receipts(
    analysis_dir: Path | None,
    analysis: dict[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    roster_id: int | None,
    team_name: str,
    writer_preferences: dict[str, Any] | None,
) -> dict[str, Any]:
    """Migrate old fallback markdown without refreshing facts or invoking an LLM.

    A source-only deploy may have a durable browser bundle and durable analysis
    markdown from an older receipt contract. Keep the migration deterministic:
    reuse the preserved article body and validated rows, write only missing
    fallback metadata, and leave automatic-LLM articles untouched.
    """

    table_rows = {
        str(name): [dict(row) for row in rows if isinstance(row, Mapping)]
        for name, rows in (tables or {}).items()
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes))
    }
    analysis_rows = {
        "target_theses": list(analysis.get("targetTheses") or []),
        "sell_theses": list(analysis.get("sellTheses") or []),
        "trade_theses": list(analysis.get("tradeTheses") or []),
        "manager_dossiers": list(analysis.get("managerDossierItems") or []),
        "player_dossiers": list(analysis.get("playerDossierItems") or []),
    }
    fallback_inputs = {
        "daily_brief": (
            analysis_rows["target_theses"][:5]
            + analysis_rows["sell_theses"][:5]
            + analysis_rows["trade_theses"][:5],
            ["target_theses", "sell_theses", "trade_theses"],
            "dailyGmBrief",
            "daily_gm_brief.md",
        ),
        "team_report": (
            [
                row
                for row in (table_rows.get("player_dossiers") or analysis_rows["player_dossiers"])
                if roster_id is None or _int(row.get("roster_id")) == _int(roster_id)
            ],
            ["player_dossiers", "roster_players", "player_projection_season", "player_signal_scores"],
            "teamReport",
            "team_report.md",
        ),
        "market_watch": (
            analysis_rows["target_theses"][:12] + analysis_rows["sell_theses"][:12],
            ["target_theses", "sell_theses", "player_opportunity_scores"],
            "marketWatch",
            "market_watch.md",
        ),
        "trade_desk": (
            analysis_rows["trade_theses"][:12],
            ["trade_theses", "manager_profiles", "manager_valuation_profiles", "counterparty_trade_edges"],
            "tradeDeskRead",
            "trade_desk.md",
        ),
        "manager_intel": (
            analysis_rows["manager_dossiers"][:14],
            [
                "manager_dossiers",
                "manager_profiles",
                "manager_event_log",
                "manager_season_history",
                "manager_cycle_profiles",
            ],
            "managerIntel",
            "manager_intel.md",
        ),
    }
    receipts = dict(analysis.get("articleReceipts") or {}) if isinstance(analysis.get("articleReceipts"), Mapping) else {}
    for article_key, (rows, source_tables, body_field, filename) in fallback_inputs.items():
        path = analysis_dir / filename if analysis_dir is not None else None
        body = str(analysis.get(body_field) or "")
        if path is not None and path.is_file():
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                pass
        if not body or _front_matter_text_field(body, "model_mode") not in {"", GENERATION_MODE}:
            continue
        existing_payload = _front_matter_json_text(body, "article_payload_json")
        if (
            _front_matter_text_field(body, "evidence_fingerprint")
            and existing_payload.get("fallback_schema_version") == FALLBACK_ARTICLE_SCHEMA_VERSION
        ):
            continue
        upgraded = _decorate_deterministic_article(
            article_key,
            body,
            rows,
            source_tables,
            roster_id,
            team_name,
            writer_preferences,
        )
        analysis[body_field] = upgraded
        if path is not None and upgraded != body:
            try:
                path.write_text(upgraded, encoding="utf-8")
            except OSError:
                # The browser payload still receives the migrated receipt even
                # when the durable markdown is temporarily read-only.
                pass
        previous_receipt = receipts.get(article_key) if isinstance(receipts.get(article_key), Mapping) else {}
        receipts[article_key] = _article_receipt_from_text(filename, upgraded, previous_receipt)
    if receipts:
        analysis["articleReceipts"] = receipts
    return analysis


def _deterministic_fallback_editorial_fields(
    article_key: str,
    reporter_name: str,
    evidence_rows: list[dict[str, Any]],
    evidence_ids: list[str],
    source_ids: list[str],
    roster_id: int | None,
    team_name: str,
) -> dict[str, str]:
    """Give fallback publications a useful story spine without adding facts.

    These sentences describe the evidence scope and the decision boundary; they
    do not claim a new event, a manager motive, or a recommendation outcome.
    The protected writer can replace them with a richer lens while retaining
    the same structured fields and evidence receipt.
    """

    count = len(evidence_ids)
    source_count = len(source_ids)
    lead = next(
        (
            str(row.get("player_name") or row.get("target_manager_name") or row.get("team_name") or row.get("name") or "")
            for row in evidence_rows
            if str(row.get("player_name") or row.get("target_manager_name") or row.get("team_name") or row.get("name") or "").strip()
        ),
        "the lead evidence row",
    )
    scope = f"{count} evidence anchor{'s' if count != 1 else ''} across {source_count} source receipt{'s' if source_count != 1 else ''}"
    changed = (
        f"No prior-edition change is asserted in this fallback; the current receipt covers {scope}. "
        "Use the publication change ledger to distinguish new evidence from a new shell."
    )
    counter = (
        "No LLM counter-signal is stored. Review the row-level risk, freshness, and source receipt "
        "before treating the read as actionable."
    )
    if article_key == "team_report":
        return {
            "dek": f"{reporter_name} reads {team_name or 'the selected roster'} through its current market, projection, and role evidence.",
            "lede": f"{team_name or 'The selected roster'} has {scope} in view. Start with {lead}, then compare the roster's strongest holds with its price-discovery candidates.",
            "thesis": "The useful roster decision is where market value, projected production, and team need disagree; this report frames the queue rather than making the move.",
            "what_changed": changed,
            "counter_evidence": counter,
            "action": "Open the cornerstone and shop-candidate evidence, then decide whether the return clears the selected roster's need.",
            "visual_brief": "Use a ranked roster rail with one market-versus-projection comparison; keep all factual values in accessible HTML.",
        }
    if article_key == "market_watch":
        return {
            "dek": f"{reporter_name} scans market disagreement and opportunity signals for price discovery, not automatic action.",
            "lede": f"The market watch opens on {lead} and {scope}. The signal is a question about price, role, and timing—not a verdict.",
            "thesis": "Investigate the gaps where projected opportunity or roster context has not clearly been reflected in the market value.",
            "what_changed": changed,
            "counter_evidence": counter,
            "action": "Check role, source freshness, and the live market before turning a ranked signal into a conversation.",
            "visual_brief": "Use a diverging market-versus-model bar for the lead read; do not place statistics inside artwork.",
        }
    if article_key == "trade_desk":
        return {
            "dek": f"{reporter_name} turns observed roster needs and valuation lanes into read-only conversation shortlists.",
            "lede": f"The desk starts with {lead} and {scope}. Each fit is a hypothesis bounded by owned assets, observed preferences, and price guardrails.",
            "thesis": "The best trade conversation begins where a counterparty's observed lane overlaps a real need on the selected roster.",
            "what_changed": changed,
            "counter_evidence": "The packet does not observe intent or predict a response; inspect the historical evidence and do-not-chase conditions.",
            "action": "Open the two-sided packet, test the offer band against the current market, and keep the shortlist read-only.",
            "visual_brief": "Use a two-column selected-roster versus counterparty comparison with an evidence drawer below.",
        }
    if article_key == "manager_intel":
        return {
            "dek": f"{reporter_name} profiles observed manager behavior across exact roster identities and historical seasons.",
            "lede": f"The manager room begins with {lead} and {scope}. Timing, roster shape, and repeated behavior are evidence; motive remains unknown.",
            "thesis": "Historical manager behavior is most useful when it narrows the next question without pretending to know how an opponent will respond.",
            "what_changed": changed,
            "counter_evidence": "Manager intent is not observed in Sleeper data; confidence and sample size should travel with every tendency.",
            "action": "Open a dossier, inspect season timing and trade fits, then choose the question you want to ask that manager.",
            "visual_brief": "Use a season timeline with roster-label changes and a separate two-sided trade-fit panel.",
        }
    return {
        "dek": f"{reporter_name} looks ahead through the selected league's validated signals and decision queues.",
        "lede": f"{team_name or 'The selected roster'} has {scope} in the daily read. The first name to investigate is {lead}.",
        "thesis": "Use the strongest cross-source signals to decide what deserves attention today, then open the underlying evidence before acting.",
        "what_changed": changed,
        "counter_evidence": counter,
        "action": "Open the evidence for the lead read and make the final decision yourself.",
        "visual_brief": "Lead with one ranked decision rail, followed by compact evidence and source-health indicators.",
    }


def _replace_front_matter_fields(text: str, fields: dict[str, Any]) -> str:
    if not text.startswith("---"):
        return text
    marker = "\n---"
    end = text.find(marker, 3)
    if end < 0:
        return text
    front = text[3:end].strip("\n")
    body = text[end + len(marker):].lstrip("\n")
    lines = front.splitlines()
    for key, value in fields.items():
        prefix = f"{key}:"
        lines = [line for line in lines if not line.startswith(prefix)]
        lines.append(f"{key}: {value}")
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def _front_matter_text_field(text: str, key: str) -> str:
    if not str(text or "").startswith("---"):
        return ""
    end = str(text).find("\n---", 3)
    if end < 0:
        return ""
    prefix = f"{key}:"
    for line in str(text)[3:end].splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _front_matter_json_text(text: str, key: str) -> dict[str, Any]:
    raw = _front_matter_text_field(text, key)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _article_receipt_from_text(
    filename: str,
    text: str,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    receipt = dict(previous or {})
    receipt.update(
        {
            "mode": _front_matter_text_field(text, "model_mode") or receipt.get("mode") or GENERATION_MODE,
            "model": _front_matter_text_field(text, "model") or receipt.get("model") or "",
            "reporter_id": _front_matter_text_field(text, "reporter_persona") or receipt.get("reporter_id") or "",
            "reporter_name": _front_matter_text_field(text, "reporter_name") or receipt.get("reporter_name") or "",
            "generated_at": _front_matter_text_field(text, "generated_at") or receipt.get("generated_at") or "",
            "evidence_fingerprint": _front_matter_text_field(text, "evidence_fingerprint") or receipt.get("evidence_fingerprint") or "",
            "fallback_reason": _front_matter_text_field(text, "fallback_reason") or receipt.get("fallback_reason") or "",
            "source_receipt": _front_matter_json_text(text, "source_receipt_json") or receipt.get("source_receipt") or {},
            "content_hash": hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
            "structured": _front_matter_json_text(text, "article_payload_json") or receipt.get("structured") or {},
            "path": filename,
        }
    )
    return receipt


def _deterministic_source_ids(rows: list[dict[str, Any]], source_tables: list[str]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for key in ("source_trace", "source_ids", "source_id", "source"):
            raw = row.get(key) if isinstance(row, dict) else ""
            parts = raw if isinstance(raw, (list, tuple, set)) else re.split(r"[;,|]", str(raw or ""))
            for part in parts:
                value = str(part).strip()
                if value and value not in values:
                    values.append(value)
    return values[:16]


def _deterministic_evidence_ids(article_key: str, rows: list[dict[str, Any]]) -> list[str]:
    """Assign canonical evidence identities to the exact rows behind a fallback read."""

    evidence_ids: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        if article_key in {"trade_desk", "manager_intel"}:
            entity_type = "manager"
            entity_id = row.get("target_manager_roster_id") or row.get("roster_id")
        elif article_key == "daily_brief" and row.get("target_manager_roster_id") not in (None, ""):
            entity_type = "manager"
            entity_id = row.get("target_manager_roster_id")
        else:
            entity_type = "player"
            entity_id = row.get("player_id")
        entity_id = _stable_entity_id(entity_id, index)
        evidence_id = f"{entity_type}:{entity_id}:{index}"
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    return evidence_ids[:24]


def _stable_entity_id(value: Any, fallback: int) -> str:
    if value in (None, ""):
        return str(fallback)
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return str(value).strip() or str(fallback)


def _deterministic_related_entities(rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("player_name") or row.get("target_manager_name") or row.get("team_name") or row.get("name")
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)
    return values[:8]


def _deterministic_confidence(rows: list[dict[str, Any]]) -> str:
    levels = {str(row.get("confidence") or "").strip().lower() for row in rows if isinstance(row, dict)}
    if "low" in levels:
        return "low"
    if "medium" in levels:
        return "medium"
    if levels and levels <= {"high"}:
        return "high"
    return "medium"


def _article_headline(text: str, article_key: str) -> str:
    for line in str(text or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return article_key.replace("_", " ").title()


def _without_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_generated_at(item) for key, item in value.items() if key != "generated_at"}
    if isinstance(value, list):
        return [_without_generated_at(item) for item in value]
    return value


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
    edges = dataframes.get("counterparty_trade_edges", pd.DataFrame())
    inventory = dataframes.get("team_asset_inventory", pd.DataFrame())
    profiles = dataframes.get("manager_profiles", pd.DataFrame())
    valuation_profiles = dataframes.get("manager_valuation_profiles", pd.DataFrame())
    needs = dataframes.get("team_needs_matrix", pd.DataFrame())
    # Opportunities keyed by the manager they actually target -- opportunity_board.target_team is
    # the real linkage (each asset_in genuinely belongs to that team). The old round-robin pairing
    # here attributed players to managers who don't roster them, which read as wrong data.
    opportunities_by_team: dict[str, list[dict[str, Any]]] = {}
    for opportunity in _rows(opportunities):
        opportunities_by_team.setdefault(str(opportunity.get("target_team", "")), []).append(opportunity)
    theses: list[dict[str, Any]] = []
    managers = [row for row in _rows(behavior) if _int(row.get("roster_id")) != active_roster_id]
    edge_rows = _rows(edges)
    inventory_rows = [row for row in _rows(inventory) if _int(row.get("roster_id")) == _int(active_roster_id)]
    current_assets = sorted(inventory_rows, key=lambda row: _num(row.get("market_value")), reverse=True)[:8]
    profile_by_roster = {_int(row.get("roster_id")): row for row in _rows(profiles)}
    need_by_roster = {_int(row.get("roster_id")): row for row in _rows(needs)}
    for index, manager in enumerate(managers[:10], start=1):
        manager_name = manager.get("team_name", "Unknown manager")
        target_roster_id = _int(manager.get("roster_id"))
        manager_signal = manager.get("plain_language_label", "")
        matched = opportunities_by_team.get(str(manager_name), [])
        assets = "; ".join(dict.fromkeys(str(opportunity.get("asset_in", "")) for opportunity in matched[:3] if opportunity.get("asset_in")))
        top = matched[0] if matched else {}
        target_edges = sorted(
            [row for row in edge_rows if _int(row.get("target_roster_id")) == target_roster_id],
            key=lambda row: _num(row.get("trade_edge_score")),
            reverse=True,
        )[:5]
        if not assets and target_edges:
            assets = "; ".join(str(row.get("player_name", "")) for row in target_edges[:3] if row.get("player_name"))
        target_profile = profile_by_roster.get(target_roster_id, {})
        target_need = need_by_roster.get(target_roster_id, {})
        manager_preferences = sorted(
            [
                row
                for row in _rows(valuation_profiles)
                if _int(row.get("roster_id")) == target_roster_id
            ],
            key=lambda row: _num(row.get("preference_score")),
            reverse=True,
        )
        offer_candidates = _offer_candidates(current_assets, manager_preferences)
        top_edge = target_edges[0] if target_edges else {}
        market_value = _num(top_edge.get("market_consensus_value"))
        estimated_owner_value = _num(top_edge.get("estimated_owner_value_score"))
        starting_low = round(max(0.0, market_value * 0.9), 2) if market_value else 0
        starting_high = round(max(starting_low, market_value * 1.1), 2) if market_value else 0
        minimum_return = round(max(0.0, market_value * 0.85), 2) if market_value else 0
        preferred_ours = [row.get("asset_name", "") for row in offer_candidates[:3] if row.get("asset_name")]
        alternate_counterparties = [
            str(row.get("target_team", ""))
            for row in edge_rows
            if _int(row.get("target_roster_id")) not in {target_roster_id, _int(active_roster_id)}
            and str(row.get("player_id")) == str(top_edge.get("player_id"))
            and row.get("target_team")
        ][:3]
        edge_confidence = top_edge.get("confidence") or (top.get("confidence") if matched else "low")
        fit_evidence = top_edge.get("evidence") or top.get("evidence") or manager.get("evidence", "")
        target_label = target_profile.get("contender_rebuilder_indicator") or target_need.get("team_shape") or manager_signal or "unclassified roster"
        if assets:
            analysis_text = (
                f"{manager_name} profiles as {manager_signal or 'unclear'}. "
                f"Use that as a conversation angle around {assets}, with the evidence row setting the guardrails."
            )
        else:
            analysis_text = (
                f"{manager_name} profiles as {manager_signal or 'unclear'}. "
                f"No specific roster target stands out from the current board -- open with their tendency "
                f"(what they buy, what they hoard) and let price discovery surface the asset."
            )
        theses.append(
            {
                "thesis_id": f"trade-{index:03d}",
                "roster_id": active_roster_id,
                "target_manager_roster_id": _int(manager.get("roster_id")),
                "target_manager_name": manager_name,
                "approach_type": _approach_type(manager_signal),
                "assets_to_discuss": assets or "tendency-based approach; no named asset",
                "assets_to_pursue": [
                    {
                        "player_name": row.get("player_name", ""),
                        "player_id": row.get("player_id", ""),
                        "position": row.get("position", ""),
                        "edge_type": row.get("edge_type", ""),
                        "market_value": row.get("market_consensus_value", ""),
                        "confidence": row.get("confidence", ""),
                    }
                    for row in target_edges[:3]
                ],
                "assets_we_can_offer": preferred_ours,
                "offer_candidates": offer_candidates[:5],
                "plausible_offer_range": {
                    "low": starting_low,
                    "high": starting_high,
                    "basis": "estimated market consensus band; not a suggested executed offer",
                },
                "minimum_acceptable_return": {
                    "value": minimum_return,
                    "basis": "estimated 85% of the target asset market value; review roster context before acting",
                },
                "why_manager_might_care": (
                    f"Observed roster label: {target_label}. Their recorded position needs are {_need_summary(target_need)}; "
                    f"their transaction history shows {target_profile.get('total_trades', manager.get('trade_activity_score', 0))} observed trades."
                ),
                "historical_evidence": {
                    "manager_profile": target_profile.get("most_common_transaction_partners", ""),
                    "behavior_signal": manager.get("evidence", ""),
                    "edge_signal": fit_evidence,
                    "valuation_lanes": [
                        {
                            "position_group": row.get("position_group", ""),
                            "label": row.get("label", ""),
                            "preference_score": row.get("preference_score", ""),
                            "evidence_count": row.get("evidence_count", ""),
                        }
                        for row in manager_preferences[:8]
                    ],
                },
                "risk_of_waiting": (
                    "The current market gap may close before the next review."
                    if target_edges and _num(top_edge.get("trade_edge_score")) > 20
                    else "No elevated timing risk is supported by the current evidence."
                ),
                "risk_of_acting": str(top_edge.get("risk") or top.get("risk") or "Do not force a deal on a low-confidence fit."),
                "alternative_counterparties": alternate_counterparties,
                "do_not_chase_conditions": [
                    "Do not treat the estimated owner value as a quote or motive.",
                    "An offer candidate reflects an observed valuation lane, not a predicted response.",
                    "Do not proceed if the live market or roster context invalidates the evidence packet.",
                ],
                "manager_signal": manager_signal,
                "evidence": fit_evidence,
                "risk": top_edge.get("risk") or top.get("risk", "medium"),
                "confidence": edge_confidence if target_edges else (top.get("confidence", "medium") if matched else "low"),
                "source_trace": top_edge.get("source_trace") or top.get("source_trace") or "manager_behavior_signals;opportunity_board;counterparty_trade_edges",
                "analysis_text": analysis_text,
                "generated_at": generated_at,
            }
        )
    return theses


def _offer_candidates(
    current_assets: list[dict[str, Any]],
    manager_preferences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank our own assets by an observed counterparty valuation lane.

    This is deliberately a conversation shortlist, not an offer generator. A
    manager profile can say that a roster historically collects pass catchers
    or accumulates picks; it cannot prove that the manager wants a particular
    asset today.
    """
    preferences: dict[str, dict[str, Any]] = {}
    for row in manager_preferences:
        group = str(row.get("position_group") or "DEPTH")
        existing = preferences.get(group)
        if existing is None or _num(row.get("preference_score")) > _num(existing.get("preference_score")):
            preferences[group] = row
    candidates: list[dict[str, Any]] = []
    for asset in current_assets:
        asset_name = str(asset.get("asset_name") or "").strip()
        if not asset_name:
            continue
        group = _asset_position_group(asset)
        preference = preferences.get(group) or preferences.get("DEPTH") or {}
        preference_score = _num(preference.get("preference_score"))
        evidence_count = _int(preference.get("evidence_count"))
        candidates.append(
            {
                "asset_id": asset.get("asset_id", ""),
                "asset_name": asset_name,
                "asset_type": asset.get("asset_type", ""),
                "position": asset.get("position", ""),
                "position_group": group,
                "market_value": asset.get("market_value", ""),
                "liquidity_tier": asset.get("liquidity_tier", ""),
                "timeline_fit": asset.get("timeline_fit", ""),
                "manager_preference_score": round(preference_score, 2),
                "manager_preference_label": preference.get("label", "low-signal manager lane"),
                "manager_preference_evidence_count": evidence_count,
                "fit_confidence": preference.get("confidence", "low") or "low",
                "evidence": (
                    f"asset_market={asset.get('market_value', '')}; asset_liquidity={asset.get('liquidity_tier', '')}; "
                    f"manager_lane={preference.get('label', 'low-signal manager lane')}; "
                    f"preference_score={round(preference_score, 2)}; evidence_count={evidence_count}"
                ),
                "source_trace": ";".join(
                    value
                    for value in (str(asset.get("source_trace") or ""), "manager_valuation_profiles")
                    if value
                ),
            }
        )
    return sorted(
        candidates,
        key=lambda row: (_num(row.get("manager_preference_score")), _num(row.get("market_value"))),
        reverse=True,
    )


def _asset_position_group(asset: dict[str, Any]) -> str:
    if str(asset.get("asset_type") or "") == "pick" or str(asset.get("position") or "") == "PICK":
        return "PICK"
    if str(asset.get("position") or "") in {"WR", "TE"}:
        return "PASS_CATCHER"
    if str(asset.get("position") or "") in {"QB", "RB"}:
        return str(asset.get("position"))
    return "DEPTH"


def _need_summary(needs: dict[str, Any]) -> str:
    labels = {
        "QB": needs.get("need_qb"),
        "RB": needs.get("need_rb"),
        "pass catcher": needs.get("need_pass_catcher"),
        "picks": needs.get("need_picks"),
    }
    high = [label for label, value in labels.items() if str(value).lower() == "high"]
    if high:
        return ", ".join(high)
    known = [f"{label}: {value}" for label, value in labels.items() if value not in (None, "", "unknown")]
    return ", ".join(known) if known else "not available"


def build_daily_gm_brief(
    active_roster_id: int | None,
    active_team_name: str,
    targets: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
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
                "reporter_persona": persona_metadata(writer_preferences, "daily_brief")["persona_id"],
            }
        ),
        f"# Daily GM Brief: {active_team_name}",
        "",
        _brief_intro(active_team_name, writer_preferences, "daily_brief"),
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
                "source_tables": "manager_behavior_signals, manager_event_log, manager_season_history, manager_profiles",
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

def _article_front_matter(
    key: str,
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
    **extra: Any,
) -> str:
    return _front_matter(
        {
            "artifact_type": key,
            "generated_at": generated_at,
            "model_mode": GENERATION_MODE,
            "reporter_persona": persona_metadata(writer_preferences, key)["persona_id"],
            **extra,
        }
    )


def build_team_report(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_team_name: str,
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
) -> str:
    players = [row for row in _rows(dataframes.get("player_dossiers", pd.DataFrame())) if _int(row.get("roster_id")) == _int(active_roster_id)]
    cornerstone_pool = [row for row in players if not _is_shop_candidate(row)]
    cornerstones = sorted(cornerstone_pool or players, key=_cornerstone_score, reverse=True)[:4]
    cornerstone_names = {_normalize_name(row.get("player_name")) for row in cornerstones}
    shop = sorted(
        [row for row in players if _normalize_name(row.get("player_name")) not in cornerstone_names],
        key=_shop_score,
        reverse=True,
    )[:4]
    lines = [
        _article_front_matter(
            "team_report",
            generated_at,
            writer_preferences,
            roster_id=active_roster_id,
            team_name=active_team_name,
        ),
        f"# Your Team Report: {active_team_name}",
        "",
        _team_report_intro(active_team_name, players, writer_preferences, "team_report"),
        "",
        "## Cornerstones",
        *_player_bullets(cornerstones, "cornerstone", writer_preferences, "team_report"),
        "",
        "## Shop Candidates",
        *_player_bullets(shop, "shop", writer_preferences, "team_report"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_market_watch(
    targets: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
) -> str:
    lines = [
        _article_front_matter("market_watch", generated_at, writer_preferences),
        "# Market Watch",
        "",
        _market_watch_intro(writer_preferences, "market_watch"),
        "",
        "## Buy-Low Targets",
        *_thesis_bullets(targets[:5], "buy_low", writer_preferences, "market_watch"),
        "",
        "## Sell-High Windows",
        *_thesis_bullets(sells[:5], "sell_high", writer_preferences, "market_watch"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_trade_desk(
    trades: list[dict[str, Any]],
    active_team_name: str,
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
) -> str:
    best = trades[:5]
    lines = [
        _article_front_matter("trade_desk", generated_at, writer_preferences, team_name=active_team_name),
        "# Trade Desk Read",
        "",
        _trade_desk_intro(active_team_name, writer_preferences, "trade_desk"),
        "",
        "## Best Fits",
        *_trade_bullets(best, writer_preferences, "trade_desk"),
        "",
        "## Steer Clear",
        "- No steer-clear counterparties flagged from the current evidence. Treat every manager read as a tendency estimate, not intent.",
    ]
    return "\n".join(lines).strip() + "\n"


def build_manager_intel(
    dataframes: dict[str, pd.DataFrame],
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
) -> str:
    cycles = _rows(dataframes.get("manager_cycle_profiles", pd.DataFrame()))
    contenders = [row for row in cycles if str(row.get("dynasty_cycle", "")) == "contender"]
    rebuilders = [row for row in cycles if str(row.get("dynasty_cycle", "")) == "rebuild"]
    lines = [
        _article_front_matter("manager_intel", generated_at, writer_preferences, manager_count=len(cycles)),
        "# Manager Intel",
        "",
        _manager_intel_intro(len(cycles), writer_preferences, "manager_intel"),
        "",
        "## Contenders",
        *_manager_bullets(contenders, writer_preferences, "manager_intel"),
        "",
        "## Rebuilders",
        *_manager_bullets(rebuilders, writer_preferences, "manager_intel"),
    ]
    return "\n".join(lines).strip() + "\n"


def build_manager_dossier_items(
    dataframes: dict[str, pd.DataFrame],
    generated_at: str,
    previous_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cycles = _rows(dataframes.get("manager_cycle_profiles", pd.DataFrame()))
    tags = _rows(dataframes.get("manager_profile_tags", pd.DataFrame()))
    profiles = _rows(dataframes.get("manager_profiles", pd.DataFrame()))
    events = _rows(dataframes.get("manager_event_log", pd.DataFrame()))
    inventory = _rows(dataframes.get("team_asset_inventory", pd.DataFrame()))
    needs = _rows(dataframes.get("team_needs_matrix", pd.DataFrame()))
    valuation_profiles = _rows(dataframes.get("manager_valuation_profiles", pd.DataFrame()))
    counterparty_edges = _rows(dataframes.get("counterparty_trade_edges", pd.DataFrame()))
    season_history_rows = _rows(dataframes.get("manager_season_history", pd.DataFrame()))
    tags_by_id: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        tags_by_id.setdefault(str(tag.get("entity_id", "")), []).append(tag)
    profile_by_id = {str(row.get("roster_id")): row for row in profiles if row.get("roster_id") not in (None, "")}
    needs_by_id = {str(row.get("roster_id")): row for row in needs if row.get("roster_id") not in (None, "")}
    items: list[dict[str, Any]] = []
    previous_by_roster = {
        str(item.get("roster_id")): item
        for item in (previous_items or [])
        if isinstance(item, dict) and item.get("roster_id") not in (None, "")
    }
    for index, cycle in enumerate(cycles, start=1):
        roster_id = str(cycle.get("roster_id", ""))
        profile = profile_by_id.get(roster_id, {})
        selected_tags = tags_by_id.get(roster_id, [])[:6]
        tag_text = ", ".join(str(tag.get("tag", "")) for tag in selected_tags if tag.get("tag"))
        evidence = str(cycle.get("evidence", ""))
        manager_events = [row for row in events if str(row.get("roster_id")) == roster_id]
        manager_seasons = [row for row in season_history_rows if str(row.get("roster_id")) == roster_id]
        manager_assets = [row for row in inventory if str(row.get("roster_id")) == roster_id]
        manager_needs = needs_by_id.get(roster_id, {})
        manager_preferences = [row for row in valuation_profiles if str(row.get("roster_id")) == roster_id]
        manager_edges = [row for row in counterparty_edges if str(row.get("target_roster_id")) == roster_id]
        fingerprint = _fingerprint(
            {
                "cycle": cycle,
                "profile": profile,
                "tags": selected_tags,
                "events": manager_events,
                "season_history": manager_seasons,
                "assets": manager_assets,
                "needs": manager_needs,
                "preferences": manager_preferences,
                "edges": manager_edges,
            }
        )
        previous = previous_by_roster.get(roster_id) or {}
        previous_fingerprint = str(previous.get("evidence_fingerprint") or "")
        update_status = "new" if not previous else ("unchanged" if previous_fingerprint == fingerprint else "updated")
        risk = "medium: manager cycle is an estimated tendency, not intent"
        sample_size = {
            "seasons": len(_split_values(profile.get("seasons_covered"))),
            "trades": _int(profile.get("total_trades")),
            "waiver_claims": _int(profile.get("number_of_waiver_claims")),
            "observed_events": len(manager_events),
            "seasons_with_activity": sum(
                1 for row in manager_seasons if _int(row.get("transaction_count")) > 0
            ),
        }
        roster_construction = {
            "team_shape": manager_needs.get("team_shape", ""),
            "qb_count": _int(profile.get("qb_count")),
            "rb_count": _int(profile.get("rb_count")),
            "pass_catcher_count": _int(profile.get("pass_catcher_count")),
            "future_firsts_owned": _int(manager_needs.get("future_firsts_owned")),
            "asset_count": len(manager_assets),
            "market_value_total": round(sum(_num(row.get("market_value")) for row in manager_assets), 2),
        }
        historical_aliases = _season_history(profile)
        # The alias parser is a compatibility fallback for older generated
        # artifacts. New dossiers carry the full deterministic season ledger;
        # this is what lets the UI distinguish recent behavior from a career
        # total instead of implying that every year looked the same.
        season_history = manager_seasons or historical_aliases
        repeated_behavior = {
            "players_acquired": _split_values(profile.get("players_acquired"), 12),
            "players_sold": _split_values(profile.get("players_sold"), 12),
            "trade_partners": _counted_values(profile.get("most_common_transaction_partners"), 8),
            "pick_posture": cycle.get("pick_posture", ""),
            "waiver_posture": cycle.get("waiver_posture", ""),
        }
        behavior_observations = [
            {"label": "Trade activity", "value": cycle.get("trade_temperature", ""), "evidence": f"total_trades={profile.get('total_trades', 0)}"},
            {"label": "Pick behavior", "value": cycle.get("pick_posture", ""), "evidence": f"future_1sts_acquired={profile.get('future_1sts_acquired', 0)}; future_1sts_sold={profile.get('future_1sts_sold', 0)}"},
            {"label": "Waiver behavior", "value": cycle.get("waiver_posture", ""), "evidence": f"claims={profile.get('number_of_waiver_claims', 0)}; faab={profile.get('faab_spent_on_waivers', 0)}"},
        ]
        trade_fits = [
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "edge_type": row.get("edge_type", ""),
                "trade_edge_score": row.get("trade_edge_score", ""),
                "market_consensus_value": row.get("market_consensus_value", ""),
                "estimated_owner_value_score": row.get("estimated_owner_value_score", ""),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
            for row in sorted(manager_edges, key=lambda value: _num(value.get("trade_edge_score")), reverse=True)[:6]
        ]
        questions = _manager_questions(cycle, profile, manager_needs, trade_fits)
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
                "source_trace": "manager_cycle_profiles;manager_profile_tags;manager_profiles;manager_event_log;manager_season_history",
                "sample_size": sample_size,
                "roster_construction": roster_construction,
                "historical_aliases": historical_aliases,
                "season_history": season_history,
                "repeated_behavior": repeated_behavior,
                "behavior_observations": behavior_observations,
                "trade_fits": trade_fits,
                "questions_to_ask": questions,
                "unknowns": [
                    "Manager intent is not observed in Sleeper data.",
                    "A trade fit is a model-supported conversation hypothesis, not a predicted response.",
                ],
                "analysis_text": (
                    f"{cycle.get('team_name', 'This manager')} profiles as {cycle.get('dynasty_cycle', 'unclear')} "
                    f"with {cycle.get('trade_temperature', 'unknown trade activity')} and {cycle.get('pick_posture', 'unclear pick posture')}. "
                    f"The profile covers {sample_size['seasons']} seasons and {sample_size['trades']} observed trades. "
                    f"Tags: {tag_text or 'none'}. Evidence: {evidence}."
                ),
                "evidence_fingerprint": fingerprint,
                "update_status": update_status,
                "updated_fields": _changed_dossier_fields(previous, cycle, tag_text),
                "generated_at": generated_at,
            }
        )
    return items


def _split_values(value: Any, limit: int | None = None) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    values = [part.strip() for part in text.split(";") if part.strip()]
    return values[:limit] if limit else values


def _counted_values(value: Any, limit: int = 8) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for value_part in _split_values(value, limit):
        if ":" not in value_part:
            output.append({"name": value_part, "count": 0})
            continue
        name, count = value_part.rsplit(":", 1)
        output.append({"name": name.strip(), "count": _int(count)})
    return output


def _season_history(profile: dict[str, Any]) -> list[dict[str, Any]]:
    names = {part.split(":", 1)[0]: part.split(":", 1)[1] for part in _split_values(profile.get("team_names_by_season")) if ":" in part}
    rosters = {part.split(":", 1)[0]: part.split(":", 1)[1] for part in _split_values(profile.get("roster_ids_by_season")) if ":" in part}
    trades = {part.split(":", 1)[0]: _int(part.split(":", 1)[1]) for part in _split_values(profile.get("trades_by_season")) if ":" in part}
    seasons = _split_values(profile.get("seasons_covered"))
    return [
        {"season": season, "team_name": names.get(season, ""), "roster_id": rosters.get(season, ""), "trades": trades.get(season, 0)}
        for season in seasons
    ]


def _manager_questions(
    cycle: dict[str, Any],
    profile: dict[str, Any],
    needs: dict[str, Any],
    trade_fits: list[dict[str, Any]],
) -> list[str]:
    questions = [
        f"Which of their recorded needs ({needs.get('team_shape', 'current roster shape')}) is actually urgent this season?",
        f"Would a conversation around their observed {cycle.get('pick_posture', 'pick')} posture create more value than a player-for-player offer?",
    ]
    if trade_fits:
        questions.append(f"Is {trade_fits[0].get('player_name', 'the top fit')} worth pursuing at the estimated market/owner-value gap shown here?")
    if _int(profile.get("number_of_waiver_claims")):
        questions.append("Does their waiver history suggest a depth need we can satisfy without weakening our core?")
    return questions[:4]


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


def _load_prior_items(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _changed_dossier_fields(previous: dict[str, Any], cycle: dict[str, Any], tag_text: str) -> list[str]:
    if not previous:
        return ["all"]
    comparisons = {
        "team_name": cycle.get("team_name", ""),
        "dynasty_cycle": cycle.get("dynasty_cycle", ""),
        "evidence": cycle.get("evidence", ""),
        "tags": tag_text,
        "confidence": cycle.get("confidence", "low"),
    }
    return [key for key, value in comparisons.items() if str(previous.get(key, "")) != str(value)]


def _dossier_receipt(items: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(item.get("update_status") or "") for item in items]
    return {
        "update_mode": "incremental_receipt",
        "item_count": len(items),
        "new_count": statuses.count("new"),
        "updated_count": statuses.count("updated"),
        "unchanged_count": statuses.count("unchanged"),
        "fingerprint": _fingerprint([item.get("evidence_fingerprint") for item in items]),
    }


def _json_artifact(
    artifact_type: str,
    items: list[dict[str, Any]] | dict[str, Any],
    generated_at: str,
    roster_id: int | None,
    team_name: str,
    metadata: dict[str, Any] | None = None,
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
        **(metadata or {}),
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


def _brief_intro(team_name: str, writer_preferences: dict[str, Any] | None, article_key: str = "daily_brief") -> str:
    persona_id = persona_metadata(writer_preferences, article_key)["persona_id"]
    intros = {
        "front_office": (
            f"The {team_name} edition: price, production, news, and manager behavior turned into a short list of decisions. "
            "The evidence is deterministic; the tone is allowed to have opinions."
        ),
        "scout": (
            f"The {team_name} edition is a role-and-timeline read. Each signal names what is known, what is missing, "
            "and what would change the evaluation."
        ),
        "commissioner": (
            f"The {team_name} edition, with the league room in view: useful pressure points, observed tendencies, and no invented manager intent."
        ),
        "quant": (
            f"The {team_name} edition is a measured decision memo: market values, projected PPG, thresholds, and confidence before adjectives."
        ),
    }
    return intros.get(persona_id, intros["front_office"])


def _team_report_intro(
    team_name: str,
    players: list[dict[str, Any]],
    writer_preferences: dict[str, Any] | None,
    article_key: str = "team_report",
) -> str:
    projected = sum(1 for row in players if _num(row.get("projected_ppg")) > 0)
    valued = sum(1 for row in players if _has_value(row.get("market_value")))
    persona_id = persona_metadata(writer_preferences, article_key)["persona_id"]
    if not players:
        return f"No roster rows are available for {team_name}; the report is waiting on a scoped refresh."
    if persona_id == "scout":
        lead = "The roster has been sorted by the intersection of market value, projected scoring, and role signal."
    elif persona_id == "commissioner":
        lead = "This is the part of the league paper where the roster gets a flattering headline and an unflattering footnote."
    elif persona_id == "quant":
        lead = "Ranking blends market value, projected PPG, breakout score, and starter status; it is not a league-wide trade value claim."
    else:
        lead = "The roster is sorted for decision value, not name recognition, with the market and projection doing most of the arguing."
    return f"{lead} {len(players)} players are in scope; {valued} have market values and {projected} carry non-zero projections."


def _market_watch_intro(writer_preferences: dict[str, Any] | None, article_key: str = "market_watch") -> str:
    persona_id = persona_metadata(writer_preferences, article_key)["persona_id"]
    if persona_id == "scout":
        return "These are price disagreements to investigate. A buy-low still needs a viable role, and a sell window still needs a credible market."
    if persona_id == "commissioner":
        return "The market is leaving fingerprints. Read the numbers, then decide which manager is most likely to pretend they did not see them."
    if persona_id == "quant":
        return "Targets are ranked by model gaps; windows are ranked by timing or age pressure. Risk and confidence remain attached to every row."
    return "The useful market read is a disagreement, not a command: investigate the gap, then check role, price, and risk before acting."


def _trade_desk_intro(team_name: str, writer_preferences: dict[str, Any] | None, article_key: str = "trade_desk") -> str:
    persona_id = persona_metadata(writer_preferences, article_key)["persona_id"]
    if persona_id == "scout":
        return f"For {team_name}, counterparties are ranked by observed behavior and roster fit. Manager tendencies are estimates, not mind-reading."
    if persona_id == "commissioner":
        return f"{team_name} has a short list of rooms worth entering. Bring evidence; leave the league-chat theatrics at the door."
    if persona_id == "quant":
        return f"Counterparties for {team_name} are ranked by manager signals and named opportunity rows, with confidence exposed rather than implied."
    return f"The {team_name} desk is looking for conversations where the manager signal and the named asset point in the same direction."


def _manager_intel_intro(count: int, writer_preferences: dict[str, Any] | None, article_key: str = "manager_intel") -> str:
    persona_id = persona_metadata(writer_preferences, article_key)["persona_id"]
    if persona_id == "scout":
        return f"The league cycle board covers {count} teams. Cycle labels summarize roster shape and observed behavior; they do not establish intent."
    if persona_id == "commissioner":
        return f"{count} teams, several familiar habits, and enough evidence to make the league chat uncomfortable—in a useful way."
    if persona_id == "quant":
        return f"{count} cycle profiles are shown with their inputs, needs, sells, and confidence. The label is a model output, not a fact about motivation."
    return f"{count} manager profiles are translated into possible pressure points using roster shape and observed league activity."


def _player_bullets(
    rows: list[dict[str, Any]],
    section: str,
    writer_preferences: dict[str, Any] | None,
    article_key: str = "team_report",
) -> list[str]:
    if not rows:
        return ["- No high-signal roster rows available for this section."]
    return [
        f"- **{_clean(row.get('player_name'), 'Unknown player')}** — "
        f"{_player_story(row, section, writer_preferences, article_key)}"
        for row in rows
    ]


def _player_story(
    row: dict[str, Any],
    section: str,
    writer_preferences: dict[str, Any] | None,
    article_key: str = "team_report",
) -> str:
    position = _clean(row.get("position"), "player")
    status = _clean(row.get("roster_status"), "roster")
    market = _metric(row.get("market_value"))
    ppg = _metric(row.get("projected_ppg"))
    confidence = _clean(row.get("projection_confidence"), "unknown")
    signal = _human_label(row.get("signal_label"), "no strong signal")
    news = _human_label(row.get("news_impact"), "none")
    transactions = _metric(row.get("transaction_count"), integer=True)
    last_transaction = _human_label(row.get("last_transaction"), "not recorded")
    evidence = (
        f"{position}, {status}; market value {market}; projected {ppg} PPG ({confidence} confidence); "
        f"signal {signal}; news {news}; {transactions} league transactions, most recent {last_transaction}."
    )
    if section == "shop":
        read = _shop_read(row)
    else:
        read = _cornerstone_read(row)
    return f"{evidence} {_persona_read(read, writer_preferences, article_key)}"


def _cornerstone_read(row: dict[str, Any]) -> str:
    signal = str(row.get("signal_label", "")).lower()
    if "missing_projection" in signal:
        return "The market still respects the asset, but the projection is incomplete; treat this as a value anchor with a data-quality asterisk."
    if "breakout" in signal:
        return "The model sees upside relative to the current profile; keep the role and projection inputs under review."
    return "This is a useful roster anchor while the market and projection remain inside the same general range."


def _shop_read(row: dict[str, Any]) -> str:
    signal = str(row.get("signal_label", "")).lower()
    news = str(row.get("news_impact", "")).lower()
    sell_score = _metric(row.get("sell_score"))
    if "sell" in signal or "sell" in news:
        return f"The sell score is {sell_score} and the current news/signal lane adds timing pressure; test the market without forcing a weak return."
    if "missing_projection" in signal:
        return "The value is mostly a market marker because the projection is missing; shop only if another manager pays for the name."
    return f"The sell score is {sell_score}; this is a price-discovery candidate, not an automatic move."


def _persona_read(read: str, writer_preferences: dict[str, Any] | None, article_key: str | None = None) -> str:
    persona_id = persona_metadata(writer_preferences, article_key)["persona_id"]
    labels = {
        "front_office": "Front-office read:",
        "scout": "Scout read:",
        "commissioner": "League note:",
        "quant": "Measured read:",
    }
    return f"{labels.get(persona_id, labels['front_office'])} {read}"


def _thesis_bullets(
    rows: list[dict[str, Any]],
    side: str,
    writer_preferences: dict[str, Any] | None,
    article_key: str = "market_watch",
) -> list[str]:
    if not rows:
        return ["- No high-signal rows available; do not manufacture a market move."]
    prefix = "Buy-low read" if side == "buy_low" else "Sell-window read"
    return [
        f"- **{_clean(row.get('player_name'), 'Unknown player')}** — {prefix}: "
        f"{_clean(row.get('analysis_text'), 'The model sees a decision point.')} "
        f"Confidence: {_clean(row.get('confidence'), 'unknown')}. Guardrail: {_clean(row.get('risk'), 'verify the market and role')}. "
        f"{_persona_read('Use the evidence as a starting point, then verify the live market.', writer_preferences, article_key)}"
        for row in rows
    ]


def _trade_bullets(
    rows: list[dict[str, Any]],
    writer_preferences: dict[str, Any] | None,
    article_key: str = "trade_desk",
) -> list[str]:
    if not rows:
        return ["- No manager opportunity rows available; the desk is quiet until the next scoped refresh."]
    bullets: list[str] = []
    for row in rows:
        manager = _clean(row.get("target_manager_name"), "Unknown manager")
        approach = _human_label(row.get("approach_type"), "price discovery")
        signal = _clean(row.get("manager_signal"), "unclear manager signal")
        assets = _clean(row.get("assets_to_discuss"), "no named asset")
        evidence = _clean(row.get("evidence"), "no evidence string")
        risk = _clean(row.get("risk"), "verify before acting")
        confidence = _clean(row.get("confidence"), "unknown")
        offer_range = row.get("plausible_offer_range") if isinstance(row.get("plausible_offer_range"), dict) else {}
        minimum_return = row.get("minimum_acceptable_return") if isinstance(row.get("minimum_acceptable_return"), dict) else {}
        packet = (
            f"Estimated range {offer_range.get('low', 'n/a')}-{offer_range.get('high', 'n/a')}; "
            f"estimated minimum return {minimum_return.get('value', 'n/a')}; "
            f"risk of waiting: {_clean(row.get('risk_of_waiting'), 'not established')}; "
            f"risk of acting: {_clean(row.get('risk_of_acting'), risk)}."
        )
        bullets.append(
            f"- **{manager}** — Approach: {approach}. Observed signal: {signal}. Named lane: {assets}. "
            f"{packet} Evidence: {evidence}. Confidence: {confidence}. Guardrail: {risk}. "
            f"{_persona_read('Keep this as a conversation hypothesis, not a claim about intent.', writer_preferences, article_key)}"
        )
    return bullets


def _manager_bullets(
    rows: list[dict[str, Any]],
    writer_preferences: dict[str, Any] | None,
    article_key: str = "manager_intel",
) -> list[str]:
    if not rows:
        return ["- No managers in this cycle bucket from the current evidence."]
    bullets: list[str] = []
    for row in rows:
        team = _clean(row.get("team_name"), "Unknown manager")
        cycle = _human_label(row.get("dynasty_cycle"), "unclear cycle")
        needs = _clean(row.get("likely_needs"), "no named need")
        sells = _clean(row.get("likely_sells"), "no named sell lane")
        trade = _clean(row.get("trade_temperature"), "unknown trade activity")
        picks = _clean(row.get("pick_posture"), "unknown pick posture")
        confidence = _clean(row.get("confidence"), "unknown")
        evidence = _clean(row.get("evidence"), "no evidence string")
        bullets.append(
            f"- **{team}** — Cycle: {cycle}. Likely need: {needs}. Possible sell lane: {sells}. "
            f"Observed behavior: {trade}; {picks}. Confidence: {confidence}. Evidence: {evidence}. "
            f"{_persona_read('Use the profile to choose a question, never to infer motive.', writer_preferences, article_key)}"
        )
    return bullets


def _cornerstone_score(row: dict[str, Any]) -> float:
    # Market value gives the asset its floor; projected output and a breakout signal keep
    # expensive zero-projection players from becoming automatic "cornerstones."
    starter_bonus = 5.0 if str(row.get("roster_status", "")).lower() == "starter" else 0.0
    return (_num(row.get("market_value")) * 0.7) + (_num(row.get("projected_ppg")) * 3.0) + (_num(row.get("breakout_score")) * 0.15) + starter_bonus


def _shop_score(row: dict[str, Any]) -> float:
    signal = str(row.get("signal_label", "")).lower()
    news = str(row.get("news_impact", "")).lower()
    missing_projection_penalty = 30.0 if "missing_projection" in signal else 0.0
    news_bonus = 20.0 if "sell" in news else 0.0
    signal_bonus = 12.0 if "sell" in signal else 0.0
    return (_num(row.get("sell_score")) * 2.0) + news_bonus + signal_bonus - missing_projection_penalty


def _is_shop_candidate(row: dict[str, Any]) -> bool:
    signal = str(row.get("signal_label", "")).lower()
    news = str(row.get("news_impact", "")).lower()
    return _shop_score(row) >= 90.0 or "sell" in signal or "sell" in news


def _clean(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return fallback if not text or text.lower() in {"nan", "none"} else text


def _has_value(value: Any) -> bool:
    return _clean(value) not in {"", "0", "0.0", "0.00"}


def _metric(value: Any, integer: bool = False) -> str:
    text = _clean(value)
    if not text:
        return "n/a"
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if integer:
        return str(int(number))
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _human_label(value: Any, fallback: str = "") -> str:
    text = _clean(value, fallback)
    return text.replace("_", " ")


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _clean(value).lower())


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
