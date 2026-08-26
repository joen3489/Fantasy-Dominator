from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .availability import baseline_ppg_text
from .manager_preferences import HORIZON_FIELD_LABELS
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
    active_league_id = _configured_league_id(config)
    current_season = _clean(config.get("current_season"))
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
        "team_report.md": build_team_report(
            dataframes,
            active_roster_id,
            active_team_name,
            generated_at,
            writer_preferences,
            active_league_id=active_league_id,
            current_season=current_season,
        ),
        "market_watch.md": build_market_watch(
            target_theses,
            sell_theses,
            generated_at,
            writer_preferences,
            horizon_rows=_rows(dataframes.get("player_horizon_market_scores", pd.DataFrame())),
            available_horizon_rows=_available_market_rows_for_article(
                _rows(dataframes.get("available_player_horizon_scores", pd.DataFrame()))
            ),
        ),
        "horizon_watch.md": build_horizon_market_read(
            _rows(dataframes.get("player_horizon_market_scores", pd.DataFrame())),
            generated_at,
            writer_preferences,
            movement_rows=_rows(dataframes.get("horizon_market_movements", pd.DataFrame())),
        ),
        "trade_desk.md": build_trade_desk(trade_theses, active_team_name, generated_at, writer_preferences),
        "manager_intel.md": build_manager_intel(
            dataframes,
            generated_at,
            writer_preferences,
            dossier_items=manager_dossier_items,
        ),
    }
    fallback_inputs = {
        "daily_brief": (
            target_theses[:5] + sell_theses[:5] + trade_theses[:5],
            ["target_theses", "sell_theses", "trade_theses"],
        ),
        "team_report": (
            _team_report_fallback_evidence(dataframes, active_roster_id, active_league_id, current_season),
            [
                "player_dossiers",
                "roster_players",
                "player_projection_season",
                "player_signal_scores",
                "news_market_edges",
                "player_horizon_market_scores",
                "nfl_schedule",
                "nfl_team_defense_factors",
                "league_news_impact",
                "matchups",
                "trades",
                "waivers",
            ],
        ),
        "market_watch": (
            target_theses[:8]
            + sell_theses[:8]
            + _available_market_rows_for_article(
                _rows(dataframes.get("available_player_horizon_scores", pd.DataFrame()))
            ),
            ["target_theses", "sell_theses", "player_opportunity_scores", "news_market_edges", "player_horizon_market_scores", "available_player_horizon_scores", "market_consensus_values", "player_projection_weekly", "nfl_schedule", "nfl_team_defense_factors", "league_news_impact"],
        ),
        "horizon_watch": (
            _horizon_watch_fallback_evidence(
                _rows(dataframes.get("player_horizon_market_scores", pd.DataFrame())),
                _rows(dataframes.get("horizon_market_movements", pd.DataFrame())),
            ),
            ["player_horizon_market_scores", "horizon_market_movements", "player_projection_season", "player_projection_weekly", "market_consensus_values", "nfl_schedule", "nfl_team_defense_factors"],
        ),
        "trade_desk": (
            trade_theses[:12],
            ["trade_theses", "manager_profiles", "manager_valuation_profiles", "counterparty_trade_edges", "counterparty_asset_interest"],
        ),
        "manager_intel": (
            manager_dossier_items[:14],
            [
                "manager_dossiers",
                "manager_profiles",
                "manager_event_log",
                "manager_season_history",
                "manager_cycle_profiles",
                "manager_transaction_preferences",
            ],
        ),
    }
    article_filenames = {
        "daily_brief": "daily_gm_brief.md",
        "team_report": "team_report.md",
        "market_watch": "market_watch.md",
        "horizon_watch": "horizon_watch.md",
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
        "horizon_watch": (
            list(table_rows.get("player_horizon_market_scores") or [])
            + [
                dict(
                    row,
                    _article_entity_type="horizon_movement",
                    _article_entity_id=(
                        f"{_clean(row.get('player_id'), _clean(row.get('player_name')))}:{_clean(row.get('current_as_of_week'), 'current')}"
                    ),
                )
                for row in (table_rows.get("horizon_market_movements") or [])
                if _clean(row.get("movement_status")) == "changed"
            ],
            ["player_horizon_market_scores", "horizon_market_movements", "player_projection_season", "player_projection_weekly", "market_consensus_values", "nfl_schedule", "nfl_team_defense_factors"],
            "horizonWatch",
            "horizon_watch.md",
        ),
        "trade_desk": (
            analysis_rows["trade_theses"][:12],
            ["trade_theses", "manager_profiles", "manager_valuation_profiles", "counterparty_trade_edges", "counterparty_asset_interest"],
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
    if article_key == "horizon_watch":
        movement_rows = [
            row for row in evidence_rows
            if row.get("_article_entity_type") == "horizon_movement"
            and _clean(row.get("movement_status")) == "changed"
        ]
        if movement_rows:
            movement = max(
                movement_rows,
                key=lambda row: (_num(row.get("largest_clock_movement_magnitude")), _clean(row.get("name") or row.get("player_name"))),
            )
            movement_name = _clean(movement.get("name") or movement.get("player_name"), "a tracked player")
            changed = (
                f"Since week {_clean(movement.get('prior_as_of_week'), 'unknown')} the exact-scope movement receipt shows "
                f"{movement_name}'s {_human_label(movement.get('largest_clock_movement_window'), 'clock')} moving "
                f"by {_metric(movement.get('largest_clock_movement_delta'))} percentile points. This is a dated model/market "
                "change receipt, not a fifth score or proof of mispricing."
            )
        return {
            "dek": f"{reporter_name} keeps next-game utility, season value, dynasty value, and the career window on separate dials for {team_name or 'the selected league'}.",
            "lede": f"The four-window read opens on {lead} and {scope}. A percentile is useful inside its position; the price anchor remains the separate market value.",
            "thesis": "The same player can be a contender edge, a rebuilder edge, or neither depending on the decision window; the component scores and fit spread keep that disagreement visible.",
            "what_changed": changed,
            "counter_evidence": "Missing projections, incomplete schedules, availability flags, and an internal five-year scenario can limit one or more clocks; no score is a universal trade price.",
            "action": "Choose the clock that matches the decision in front of you, compare within position, then inspect market value and the evidence receipt before acting.",
            "visual_brief": "Use a four-column window card with separate next-game, season, dynasty, and career rows plus a fit row; group comparisons by position and keep the evidence receipt adjacent.",
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
            "editorial_review": _front_matter_json_text(text, "editorial_review_json") or receipt.get("editorial_review") or {},
            "path": filename,
        }
    )
    return receipt


def _deterministic_source_ids(rows: list[dict[str, Any]], source_tables: list[str]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for key in ("source_trace", "_article_source_trace", "source_ids", "source_id", "source"):
            raw = row.get(key) if isinstance(row, dict) else ""
            parts = raw if isinstance(raw, (list, tuple, set)) else re.split(r"[;,|]", str(raw or ""))
            for part in parts:
                value = str(part).strip()
                if value and value not in values:
                    values.append(value)
    return values[:16]


def _deterministic_evidence_ids(article_key: str, rows: list[dict[str, Any]]) -> list[str]:
    """Assign canonical evidence identities to the exact rows behind a fallback read."""

    selected_rows = rows
    if article_key == "team_report":
        # Keep the fallback receipt useful when a roster has more than 24 players:
        # reserve room for the newsroom context that makes Topline Tony a beat
        # reporter instead of another valuation list.
        player_rows = [row for row in rows if not row.get("_article_entity_type")]
        context_rows = [row for row in rows if row.get("_article_entity_type")]
        selected_context: list[dict[str, Any]] = []
        for entity_type in ("news", "matchup", "transaction"):
            first = next(
                (row for row in context_rows if row.get("_article_entity_type") == entity_type),
                None,
            )
            if first is not None:
                selected_context.append(first)
        for row in context_rows:
            if len(selected_context) >= 6:
                break
            if row not in selected_context:
                selected_context.append(row)
        selected_rows = player_rows[:18] + selected_context[:6]
    evidence_ids: list[str] = []
    for index, row in enumerate(selected_rows, start=1):
        if not isinstance(row, dict):
            continue
        if row.get("_article_entity_type"):
            entity_type = str(row.get("_article_entity_type"))
            entity_id = row.get("_article_entity_id")
        elif article_key in {"trade_desk", "manager_intel"}:
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
    asset_interest = dataframes.get("counterparty_asset_interest", pd.DataFrame())
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
            key=lambda row: (
                _num(row.get("trade_edge_score")),
                _num(row.get("horizon_market_disagreement_magnitude")),
            ),
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
        target_interest = sorted(
            [
                row
                for row in _rows(asset_interest)
                if _int(row.get("target_roster_id")) == target_roster_id
            ],
            key=lambda row: (_num(row.get("conversation_fit_score")), _num(row.get("market_value"))),
            reverse=True,
        )[:5]
        interest_assets = [
            {
                "asset_id": row.get("asset_id", ""),
                "asset_name": row.get("asset_name", ""),
                "position": row.get("position", ""),
                "market_value": row.get("market_value", ""),
                "conversation_fit_score": row.get("conversation_fit_score", ""),
                "conversation_fit_label": row.get("conversation_fit_label", ""),
                "transaction_lane_read": row.get("transaction_lane_read", ""),
                "transaction_acquired_count": row.get("transaction_acquired_count", ""),
                "transaction_sold_count": row.get("transaction_sold_count", ""),
                "target_need": row.get("target_need", ""),
                "target_need_fit_score": row.get("target_need_fit_score", ""),
                "target_horizon_fit_score": row.get("target_horizon_fit_score", ""),
                "active_horizon_fit_score": row.get("active_horizon_fit_score", ""),
                "horizon_fit_edge": row.get("horizon_fit_edge", ""),
                "horizon_fit_read": row.get("horizon_fit_read", ""),
                "horizon_market_percentile": row.get("horizon_market_percentile", ""),
                "next_game_market_score": row.get("next_game_market_score", ""),
                "rest_of_season_market_score": row.get("rest_of_season_market_score", ""),
                "dynasty_market_score": row.get("dynasty_market_score", ""),
                "career_projection_score": row.get("career_projection_score", ""),
                "next_game_minus_market_delta": row.get("next_game_minus_market_delta", ""),
                "rest_of_season_minus_market_delta": row.get("rest_of_season_minus_market_delta", ""),
                "dynasty_minus_market_delta": row.get("dynasty_minus_market_delta", ""),
                "career_minus_market_delta": row.get("career_minus_market_delta", ""),
                "rest_of_season_minus_next_game_delta": row.get("rest_of_season_minus_next_game_delta", ""),
                "dynasty_minus_rest_of_season_delta": row.get("dynasty_minus_rest_of_season_delta", ""),
                "career_minus_dynasty_delta": row.get("career_minus_dynasty_delta", ""),
                "horizon_market_disagreement_window": row.get("horizon_market_disagreement_window", ""),
                "horizon_market_disagreement_delta": row.get("horizon_market_disagreement_delta", ""),
                "horizon_market_disagreement_magnitude": row.get("horizon_market_disagreement_magnitude", ""),
                "horizon_market_disagreement_read": row.get("horizon_market_disagreement_read", ""),
                "confidence": row.get("confidence", ""),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "source_trace": row.get("source_trace", ""),
            }
            for row in target_interest
        ]
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
        interest_evidence = "; ".join(
            str(row.get("evidence") or "") for row in target_interest[:2] if row.get("evidence")
        )
        target_label = target_profile.get("contender_rebuilder_indicator") or target_need.get("team_shape") or manager_signal or "unclassified roster"
        horizon_fit = {
            "target_team_lens": top_edge.get("target_team_lens", ""),
            "target_horizon_fit_score": top_edge.get("target_horizon_fit_score", ""),
            "active_horizon_fit_score": top_edge.get("active_horizon_fit_score", ""),
            "horizon_fit_edge": top_edge.get("horizon_fit_edge", ""),
            "horizon_fit_read": top_edge.get("horizon_fit_read", ""),
            "horizon_fit_basis": top_edge.get("horizon_fit_basis", ""),
            "horizon_model_version": top_edge.get("horizon_model_version", ""),
            "horizon_market_percentile": top_edge.get("horizon_market_percentile", ""),
            "next_game_market_score": top_edge.get("next_game_market_score", ""),
            "rest_of_season_market_score": top_edge.get("rest_of_season_market_score", ""),
            "dynasty_market_score": top_edge.get("dynasty_market_score", ""),
            "career_projection_score": top_edge.get("career_projection_score", ""),
            "next_game_minus_market_delta": top_edge.get("next_game_minus_market_delta", ""),
            "rest_of_season_minus_market_delta": top_edge.get("rest_of_season_minus_market_delta", ""),
            "dynasty_minus_market_delta": top_edge.get("dynasty_minus_market_delta", ""),
            "career_minus_market_delta": top_edge.get("career_minus_market_delta", ""),
            "rest_of_season_minus_next_game_delta": top_edge.get("rest_of_season_minus_next_game_delta", ""),
            "dynasty_minus_rest_of_season_delta": top_edge.get("dynasty_minus_rest_of_season_delta", ""),
            "career_minus_dynasty_delta": top_edge.get("career_minus_dynasty_delta", ""),
            "horizon_market_disagreement_window": top_edge.get("horizon_market_disagreement_window", ""),
            "horizon_market_disagreement_delta": top_edge.get("horizon_market_disagreement_delta", ""),
            "horizon_market_disagreement_magnitude": top_edge.get("horizon_market_disagreement_magnitude", ""),
            "horizon_market_disagreement_read": top_edge.get("horizon_market_disagreement_read", ""),
        }
        horizon_sentence = ""
        if horizon_fit["horizon_fit_read"]:
            horizon_sentence = (
                f" The timeline read is {horizon_fit['horizon_fit_read']}: "
                f"{manager_name} is a {horizon_fit['target_team_lens'] or 'unclassified'} lens at "
                f"{horizon_fit['target_horizon_fit_score'] or 'n/a'}, versus our "
                f"{horizon_fit['active_horizon_fit_score'] or 'n/a'}; this is timeline fit, not a price quote."
            )
        repricing_sentence = ""
        if horizon_fit["horizon_market_disagreement_window"]:
            repricing_sentence = (
                f" The largest same-position clock-versus-market lead is "
                f"{horizon_fit['horizon_market_disagreement_window']} at "
                f"{horizon_fit['horizon_market_disagreement_delta'] or 'n/a'} "
                f"({horizon_fit['horizon_market_disagreement_read']}); it is a research lead, not a dollar gap."
            )
        horizon_sentence += repricing_sentence
        if assets:
            analysis_text = (
                f"{manager_name} profiles as {manager_signal or 'unclear'}. "
                f"Use that as a conversation angle around {assets}, with the evidence row setting the guardrails."
                f"{horizon_sentence}"
            )
        else:
            analysis_text = (
                f"{manager_name} profiles as {manager_signal or 'unclear'}. "
                f"No specific roster target stands out from the current board -- open with their tendency "
                f"(what they buy, what they hoard) and let price discovery surface the asset."
                f"{horizon_sentence}"
            )
        if interest_assets:
            interest_names = ", ".join(
                str(row.get("asset_name") or "unnamed asset") for row in interest_assets[:3]
            )
            analysis_text += (
                f" Observed transaction lanes also put {interest_names} on the possible conversation list; "
                "that is a prioritization signal, not proof of intent or acceptance."
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
                        "target_team_lens": row.get("target_team_lens", ""),
                        "target_horizon_fit_score": row.get("target_horizon_fit_score", ""),
                        "active_horizon_fit_score": row.get("active_horizon_fit_score", ""),
                        "horizon_fit_edge": row.get("horizon_fit_edge", ""),
                        "horizon_fit_read": row.get("horizon_fit_read", ""),
                        "horizon_market_percentile": row.get("horizon_market_percentile", ""),
                        "next_game_market_score": row.get("next_game_market_score", ""),
                        "rest_of_season_market_score": row.get("rest_of_season_market_score", ""),
                        "dynasty_market_score": row.get("dynasty_market_score", ""),
                        "career_projection_score": row.get("career_projection_score", ""),
                        "next_game_minus_market_delta": row.get("next_game_minus_market_delta", ""),
                        "rest_of_season_minus_market_delta": row.get("rest_of_season_minus_market_delta", ""),
                        "dynasty_minus_market_delta": row.get("dynasty_minus_market_delta", ""),
                        "career_minus_market_delta": row.get("career_minus_market_delta", ""),
                        "rest_of_season_minus_next_game_delta": row.get("rest_of_season_minus_next_game_delta", ""),
                        "dynasty_minus_rest_of_season_delta": row.get("dynasty_minus_rest_of_season_delta", ""),
                        "career_minus_dynasty_delta": row.get("career_minus_dynasty_delta", ""),
                        "horizon_market_disagreement_window": row.get("horizon_market_disagreement_window", ""),
                        "horizon_market_disagreement_delta": row.get("horizon_market_disagreement_delta", ""),
                        "horizon_market_disagreement_magnitude": row.get("horizon_market_disagreement_magnitude", ""),
                        "horizon_market_disagreement_read": row.get("horizon_market_disagreement_read", ""),
                        "horizon_model_version": row.get("horizon_model_version", ""),
                    }
                    for row in target_edges[:3]
                ],
                "assets_we_can_offer": preferred_ours,
                "offer_candidates": offer_candidates[:5],
                "assets_target_may_value": interest_assets,
                "counterparty_interest_status": "supported" if interest_assets else "none_supported",
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
                    + (
                        f" Their observed position lane also surfaces {', '.join(str(row.get('asset_name') or 'unnamed asset') for row in interest_assets[:3])} "
                        "as a conversation question, not a predicted response."
                        if interest_assets
                        else " No active-roster asset has a supported observed acquisition lane for this manager."
                    )
                ),
                "historical_evidence": {
                    "manager_profile": target_profile.get("most_common_transaction_partners", ""),
                    "behavior_signal": manager.get("evidence", ""),
                    "edge_signal": fit_evidence,
                    "horizon_fit": horizon_fit,
                    "counterparty_interest": interest_assets,
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
                **horizon_fit,
                "evidence": fit_evidence,
                "risk": top_edge.get("risk") or top.get("risk", "medium"),
                "confidence": edge_confidence if target_edges else (top.get("confidence", "medium") if matched else "low"),
                "source_trace": ";".join(
                    value
                    for value in (
                        top_edge.get("source_trace") or top.get("source_trace") or "manager_behavior_signals;opportunity_board;counterparty_trade_edges",
                        "counterparty_asset_interest" if interest_assets else "",
                    )
                    if value
                ),
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


def _manager_trade_fit_evaluation(
    manager_preferences: list[dict[str, Any]],
    trade_fits: list[dict[str, Any]],
    manager_seasons: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare current edge rows with observed historical valuation lanes.

    This is a prioritization aid, not a response model. The preference rows are
    aggregated from observed manager activity, while the fit rows are current
    market/roster edges. Keeping both sides explicit prevents a historical
    label from becoming an invented claim about what a manager wants today.
    """

    lanes = sorted(
        manager_preferences,
        key=lambda row: (
            _num(row.get("recency_weighted_score")),
            _num(row.get("preference_score")),
            _int(row.get("evidence_count")),
        ),
        reverse=True,
    )
    historical_lanes = [
        {
            "position_group": row.get("position_group", ""),
            "label": row.get("label", ""),
            "preference_score": row.get("preference_score", ""),
            "recency_weighted_score": row.get("recency_weighted_score", ""),
            "evidence_count": row.get("evidence_count", ""),
            "confidence": row.get("confidence", ""),
            "evidence": row.get("evidence", ""),
        }
        for row in lanes[:8]
    ]
    lane_groups = {str(row.get("position_group") or "") for row in historical_lanes if row.get("position_group")}
    fit_groups = {
        _asset_position_group({"position": row.get("position")})
        for row in trade_fits
        if row.get("position")
    }
    aligned_groups = sorted(group for group in fit_groups if group in lane_groups)
    fit_alignment = []
    for fit in trade_fits:
        position_group = _asset_position_group({"position": fit.get("position")})
        matches = [row for row in historical_lanes if str(row.get("position_group") or "") == position_group]
        lane = matches[0] if matches else {}
        fit_alignment.append(
            {
                "player_id": fit.get("player_id", ""),
                "player_name": fit.get("player_name", ""),
                "position": fit.get("position", ""),
                "position_group": position_group,
                "status": "aligned" if lane else "no_direct_lane",
                "lane_label": lane.get("label", ""),
                "recency_weighted_score": lane.get("recency_weighted_score", ""),
                "evidence_count": lane.get("evidence_count", 0),
                "confidence": lane.get("confidence", ""),
                "evidence": lane.get("evidence", ""),
                "source_trace": "manager_valuation_profiles;manager_season_history",
                "reason": (
                    f"Matches the observed {lane.get('label') or position_group} lane."
                    if lane
                    else f"No direct {position_group} valuation lane is present in the observed profile."
                ),
            }
        )
    seasons = len(manager_seasons)
    fit_count = len(trade_fits)
    if not fit_count:
        summary = (
            "No supported trade fit is present in the current edge rows. Historical valuation lanes are shown as context only; "
            "do not manufacture a target from manager labels alone."
        )
    elif aligned_groups:
        summary = (
            f"{fit_count} current trade fit{'s' if fit_count != 1 else ''} overlap "
            f"{len(aligned_groups)} observed valuation lane{'s' if len(aligned_groups) != 1 else ''} "
            f"across {seasons} historical season{'s' if seasons != 1 else ''}: {', '.join(aligned_groups)}. "
            "This narrows the next conversation; it does not predict a response."
        )
    else:
        summary = (
            f"{fit_count} current trade fit{'s' if fit_count != 1 else ''} are present, but none aligns directly "
            f"with the ranked historical lanes across {seasons} season{'s' if seasons != 1 else ''}. "
            "Treat the current edge as a price question, not proof of manager preference."
        )
    return {
        "historical_lanes": historical_lanes,
        "fit_alignment": fit_alignment,
        "aligned_fit_count": sum(1 for row in fit_alignment if row["status"] == "aligned"),
        "no_direct_lane_fit_count": sum(1 for row in fit_alignment if row["status"] == "no_direct_lane"),
        "current_fit_count": fit_count,
        "aligned_position_groups": aligned_groups,
        "historical_seasons": seasons,
        "summary": summary,
        "confidence": "high" if historical_lanes and aligned_groups else "medium" if historical_lanes else "low",
        "source_trace": "manager_valuation_profiles;counterparty_trade_edges;manager_season_history",
    }


def _manager_transaction_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Project identity-resolved transaction lanes into a manager dossier.

    Current horizon averages are explicitly present context for historically
    moved players. A historical transaction row does not establish the price,
    reason, or willingness behind the move.
    """

    lanes = sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            _int(row.get("acquired_count")) + _int(row.get("sold_count")),
            _int(row.get("horizon_acquired_matches")) + _int(row.get("horizon_sold_matches")),
        ),
        reverse=True,
    )
    total_acquired = sum(_int(row.get("acquired_count")) for row in lanes)
    total_sold = sum(_int(row.get("sold_count")) for row in lanes)
    acquired_matches = sum(_int(row.get("horizon_acquired_matches")) for row in lanes)
    sold_matches = sum(_int(row.get("horizon_sold_matches")) for row in lanes)
    if not lanes:
        return {
            "status": "not_available",
            "lanes": [],
            "lane_count": 0,
            "acquired_count": 0,
            "sold_count": 0,
            "horizon_acquired_matches": 0,
            "horizon_sold_matches": 0,
            "horizon_coverage_by_clock": {},
            "summary": "No identity-resolved player transaction lanes are available for this manager.",
            "evidence": "manager_transaction_preferences; no rows",
            "risk": "Do not infer a manager preference from the absence of resolved history.",
            "source_trace": "manager_transaction_preferences",
        }
    status = "supported" if any(str(row.get("history_status")) == "supported" for row in lanes) else "sparse"
    coverage_by_clock = _transaction_horizon_coverage(lanes)
    summary = (
        f"Observed {total_acquired} player acquisitions and {total_sold} player disposals across "
        f"{len(lanes)} position lane{'s' if len(lanes) != 1 else ''}. "
        f"Current horizon context is matched for {acquired_matches} acquired and {sold_matches} sold event rows; "
        "those averages are present context for historical names, not historical prices or intent."
    )
    return {
        "status": status,
        "lanes": lanes,
        "lane_count": len(lanes),
        "acquired_count": total_acquired,
        "sold_count": total_sold,
        "horizon_acquired_matches": acquired_matches,
        "horizon_sold_matches": sold_matches,
        "horizon_coverage_by_clock": coverage_by_clock,
        "summary": summary,
        "evidence": f"manager_transaction_preferences; lanes={len(lanes)}; acquired={total_acquired}; sold={total_sold}",
        "risk": "Observed transaction lanes narrow a conversation; they do not predict a response or prove a preference.",
        "source_trace": "manager_transaction_preferences;player_transaction_history;player_horizon_market_scores",
    }


def _transaction_horizon_coverage(lanes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Summarize horizon availability separately for each decision clock."""

    acquired_total = sum(_int(row.get("acquired_count")) for row in lanes)
    sold_total = sum(_int(row.get("sold_count")) for row in lanes)
    return {
        label: {
            "acquired": sum(_int(row.get(f"horizon_acquired_{label}_matches")) for row in lanes),
            "sold": sum(_int(row.get(f"horizon_sold_{label}_matches")) for row in lanes),
            "acquired_total": acquired_total,
            "sold_total": sold_total,
        }
        for label in HORIZON_FIELD_LABELS.values()
    }


def _manager_counterparty_interest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize active-roster assets that have a supported audience signal."""

    ordered = sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            _num(row.get("conversation_fit_score")),
            _num(row.get("market_value")),
        ),
        reverse=True,
    )
    if not ordered:
        return {
            "status": "not_available",
            "rows": [],
            "asset_count": 0,
            "summary": "No active-roster asset has a supported observed counterparty lane.",
            "evidence": "counterparty_asset_interest; no rows",
            "risk": "Do not infer demand from the absence of an observed lane.",
            "source_trace": "counterparty_asset_interest",
        }
    assets = list(dict.fromkeys(str(row.get("asset_name") or "") for row in ordered if row.get("asset_name")))
    return {
        "status": "supported",
        "rows": ordered[:8],
        "asset_count": len(assets),
        "summary": (
            f"{len(ordered)} manager-asset conversation lane{'s' if len(ordered) != 1 else ''} are supported "
            "by observed transaction history, current need, and available horizon context."
        ),
        "evidence": f"counterparty_asset_interest; rows={len(ordered)}; assets={len(assets)}",
        "risk": "Conversation fit is a prioritization signal, not intent, willingness, or a predicted response.",
        "source_trace": "counterparty_asset_interest;manager_transaction_preferences;team_needs_matrix;player_horizon_market_scores",
    }


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
    *,
    active_league_id: str = "",
    current_season: str = "",
) -> str:
    players = [
        dict(row)
        for row in _scope_current_rows(dataframes.get("player_dossiers", pd.DataFrame()), active_league_id, current_season)
        if _int(row.get("roster_id")) == _int(active_roster_id)
    ]
    _attach_horizon_rows(
        players,
        dataframes.get("player_horizon_market_scores", pd.DataFrame()),
        active_league_id,
    )
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
        _team_report_context_summary(
            dataframes,
            active_roster_id,
            active_league_id,
            current_season,
        ),
        "",
        "## Cornerstones",
        *_player_bullets(cornerstones, "cornerstone", writer_preferences, "team_report"),
        "",
        "## Shop Candidates",
        *_player_bullets(shop, "shop", writer_preferences, "team_report"),
    ]
    return "\n".join(lines).strip() + "\n"


def _team_report_fallback_evidence(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_league_id: str,
    current_season: str,
) -> list[dict[str, Any]]:
    """Build the deterministic Topline packet from the same context as the LLM scope."""

    players = [
        dict(row)
        for row in _scope_current_rows(dataframes.get("player_dossiers", pd.DataFrame()), active_league_id, current_season)
        if _int(row.get("roster_id")) == _int(active_roster_id)
    ]
    _attach_horizon_rows(
        players,
        dataframes.get("player_horizon_market_scores", pd.DataFrame()),
        active_league_id,
    )
    player_ids = {_clean(row.get("player_id")) for row in players if _clean(row.get("player_id"))}
    rows = list(players)

    news = _scope_current_rows(dataframes.get("league_news_impact", pd.DataFrame()), active_league_id, current_season)
    selected_news = [row for row in news if _clean(row.get("player_id")) in player_ids]
    league_news = [row for row in news if row not in selected_news]
    for scope, news_rows in (("selected_roster", selected_news[:8]), ("league_context", league_news[:4])):
        for row in news_rows:
            item = dict(row)
            item["_article_entity_type"] = "news"
            item["_article_entity_id"] = _clean(row.get("event_id")) or f"news:{len(rows) + 1}"
            item["_article_name"] = _clean(row.get("player_name"), "League news")
            item["_article_context_scope"] = scope
            rows.append(item)

    matchups = [
        row for row in _scope_current_rows(dataframes.get("matchups", pd.DataFrame()), active_league_id, current_season)
        if _int(row.get("roster_id")) == _int(active_roster_id)
    ]
    completed = [
        row for row in matchups
        if _clean(row.get("result")).lower() in {"win", "loss", "tie"}
        or (_num(row.get("points_for")) != 0 or _num(row.get("points_against")) != 0)
    ]
    for row in sorted(completed or matchups, key=lambda value: _int(value.get("week")), reverse=True)[:3]:
        item = dict(row)
        item["_article_entity_type"] = "matchup"
        item["_article_entity_id"] = f"{_clean(row.get('season'))}:{_clean(row.get('week'))}:{_clean(row.get('matchup_id'))}"
        item["_article_name"] = f"Week {_clean(row.get('week'), 'n/a')} vs {_clean(row.get('opponent_team_name'), 'opponent')}"
        item["_article_source_trace"] = _clean(row.get("source_trace"), "sleeper:matchups")
        rows.append(item)

    moves: list[tuple[int, str, dict[str, Any]]] = []
    for row in _scope_current_rows(dataframes.get("trades", pd.DataFrame()), active_league_id, current_season):
        if _int(row.get("team_a_roster_id")) == _int(active_roster_id) or _int(row.get("team_b_roster_id")) == _int(active_roster_id):
            moves.append((_int(row.get("week")), "trade", row))
    for row in _scope_current_rows(dataframes.get("waivers", pd.DataFrame()), active_league_id, current_season):
        if _int(row.get("roster_id")) == _int(active_roster_id):
            moves.append((_int(row.get("week")), "waiver", row))
    for _, event_type, row in sorted(moves, key=lambda value: value[0], reverse=True)[:6]:
        item = dict(row)
        item["_article_entity_type"] = "transaction"
        item["_article_entity_id"] = _clean(row.get("transaction_id")) or f"move:{len(rows) + 1}"
        item["_article_name"] = f"{event_type.title()} week {_clean(row.get('week'), 'n/a')}"
        item["_article_source_trace"] = f"sleeper:{'trades' if event_type == 'trade' else 'waivers'}"
        item["_article_event_type"] = event_type
        item["_active_roster_id"] = active_roster_id
        rows.append(item)
    return rows


def _team_report_context_summary(
    dataframes: dict[str, pd.DataFrame],
    active_roster_id: int | None,
    active_league_id: str,
    current_season: str,
) -> str:
    """Render a compact observed-week ledger without creating a third article section."""

    evidence = _team_report_fallback_evidence(dataframes, active_roster_id, active_league_id, current_season)
    news = [row for row in evidence if row.get("_article_entity_type") == "news"]
    matchups = [row for row in evidence if row.get("_article_entity_type") == "matchup"]
    moves = [row for row in evidence if row.get("_article_entity_type") == "transaction"]
    parts: list[str] = []
    if news:
        news_text = "; ".join(
            f"{_clean(row.get('player_name'), 'League player')} — {_clean(row.get('evidence'), 'signal')}"
            for row in news[:3]
        )
        parts.append(f"News: {news_text}.")
    else:
        parts.append("News: no matched current-season league signal is recorded.")
    if matchups:
        matchup_text = "; ".join(
            f"week {_clean(row.get('week'), 'n/a')} vs {_clean(row.get('opponent_team_name'), 'opponent')} ({_clean(row.get('result'), 'status')})"
            for row in matchups[:2]
        )
        parts.append(f"Matchup ledger: {matchup_text}.")
    else:
        parts.append("Matchup ledger: no current-season matchup row is recorded.")
    if moves:
        move_text = "; ".join(_team_report_move_summary(row) for row in moves[:3])
        parts.append(f"Move ledger: {move_text}.")
    else:
        parts.append("Move ledger: no current-season roster move is recorded.")
    return "**Observed week context.** " + " ".join(parts)


def _team_report_move_summary(row: dict[str, Any]) -> str:
    event_type = _clean(row.get("_article_event_type"), "move")
    week = _clean(row.get("week"), "n/a")
    if event_type == "trade":
        own_prefix = "team_a" if _int(row.get("team_a_roster_id")) == _int(row.get("_active_roster_id")) else "team_b"
        other_prefix = "team_b" if own_prefix == "team_a" else "team_a"
        counterparty = _clean(row.get(f"{other_prefix}_name"), "counterparty")
        return f"trade week {week} with {counterparty}"
    return f"waiver week {week}: added {_clean(row.get('player_added'), 'none')}, dropped {_clean(row.get('player_dropped'), 'none')}"


def _horizon_rows_by_position(rows: list[dict[str, Any]], per_position: int = 3) -> list[dict[str, Any]]:
    """Select horizon evidence without turning position percentiles into a cross-position rank."""

    valid = [
        dict(row)
        for row in rows
        if _clean(row.get("player_name"))
        and _clean(row.get("value_lane")) != "insufficient_context"
        and any(_clean(row.get(field)) for field in (
            "next_game_market_score",
            "rest_of_season_market_score",
            "dynasty_market_score",
            "career_projection_score",
        ))
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in valid:
        grouped.setdefault(_clean(row.get("position"), "OTHER"), []).append(row)
    selected: list[dict[str, Any]] = []
    for position in sorted(grouped):
        selected.extend(
            sorted(
                grouped[position],
                key=lambda row: (
                    abs(_num(row.get("rebuilder_contender_spread"))),
                    max(
                        _num(row.get("next_game_market_score")),
                        _num(row.get("rest_of_season_market_score")),
                        _num(row.get("dynasty_market_score")),
                        _num(row.get("career_projection_score")),
                    ),
                    _clean(row.get("player_name")),
                ),
                reverse=True,
            )[:per_position]
        )
    return selected


def _horizon_watch_fallback_evidence(
    rows: list[dict[str, Any]],
    movement_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return the deterministic horizon packet used for fallback receipts."""

    selected = _horizon_rows_by_position(rows, per_position=3)
    movement_evidence: list[dict[str, Any]] = []
    for row in sorted(
        [
            dict(item)
            for item in (movement_rows or [])
            if _clean(item.get("movement_status")) == "changed" and _clean(item.get("player_name"))
        ],
        key=lambda item: (_num(item.get("largest_clock_movement_magnitude")), _clean(item.get("player_name"))),
        reverse=True,
    )[:8]:
        row["_article_entity_type"] = "horizon_movement"
        row["_article_entity_id"] = f"{_clean(row.get('player_id'), _clean(row.get('player_name')))}:{_clean(row.get('current_as_of_week'), 'current')}"
        movement_evidence.append(row)
    return selected + movement_evidence


def _available_market_rows_for_article(rows: list[dict[str, Any]], per_position: int = 2) -> list[dict[str, Any]]:
    """Select available clocks for Waverly without turning the board into a price rank."""

    valid = [
        dict(row)
        for row in rows
        if _clean(row.get("player_name"))
        and _clean(row.get("player_id"))
        and _clean(row.get("availability_status")) == "not_rostered_in_selected_league"
        and _clean(row.get("identity_status")) in {"sleeper_id", "sleeper_unique_name_match"}
        and any(_clean(row.get(field)) for field in (
            "next_game_market_score",
            "rest_of_season_market_score",
            "dynasty_market_score",
            "career_projection_score",
        ))
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in valid:
        grouped.setdefault(_clean(row.get("position"), "OTHER"), []).append(row)
    selected: list[dict[str, Any]] = []
    for position in sorted(grouped):
        selected.extend(
            sorted(
                grouped[position],
                key=lambda row: (
                    _available_clock_coverage(row),
                    max(
                        _num(row.get("next_game_market_score")),
                        _num(row.get("rest_of_season_market_score")),
                        _num(row.get("dynasty_market_score")),
                        _num(row.get("career_projection_score")),
                    ),
                    abs(_num(row.get("rebuilder_contender_spread"))),
                    _num(row.get("market_value")),
                ),
                reverse=True,
            )[:per_position]
        )
    return selected[:12]


def _available_clock_coverage(row: dict[str, Any]) -> int:
    try:
        return int(float(str(row.get("fit_coverage") or "").split("/", 1)[0]))
    except (TypeError, ValueError):
        return sum(
            1
            for field in (
                "next_game_market_score",
                "rest_of_season_market_score",
                "dynasty_market_score",
                "career_projection_score",
            )
            if _clean(row.get(field))
        )


def build_market_watch(
    targets: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
    horizon_rows: list[dict[str, Any]] | None = None,
    available_horizon_rows: list[dict[str, Any]] | None = None,
) -> str:
    horizon_rows = [
        row for row in (horizon_rows or [])
        if str(row.get("player_name") or "").strip()
        and str(row.get("value_lane") or "") != "insufficient_context"
    ]
    horizon_rows = _horizon_rows_by_position(horizon_rows, per_position=1)
    lines = [
        _article_front_matter("market_watch", generated_at, writer_preferences),
        "# Market Watch",
        "",
        _market_watch_intro(writer_preferences, "market_watch"),
        "",
    ]
    if horizon_rows:
        lines.extend([_horizon_market_note(horizon_rows[:8]), ""])
    lines.extend([
        "## Buy-Low Targets",
    ])
    available_horizon_rows = _available_market_rows_for_article(available_horizon_rows or [])
    if available_horizon_rows:
        lines.extend([_available_market_note(available_horizon_rows), ""])
    lines.extend([
        *_thesis_bullets(targets[:5], "buy_low", writer_preferences, "market_watch"),
        "",
        "## Sell-High Windows",
        *_thesis_bullets(sells[:5], "sell_high", writer_preferences, "market_watch"),
    ])
    return "\n".join(lines).strip() + "\n"


def _available_market_note(rows: list[dict[str, Any]]) -> str:
    """Keep the waiver lane connected to the scored available-market table."""

    bullets = []
    for row in rows:
        lane = _human_label(row.get("value_lane"), "balanced window")
        bullets.append(
            f"- **Available-market research — {_clean(row.get('player_name'), 'Unknown player')}**: {lane}; "
            f"this-week percentile {_metric(row.get('next_game_market_score'))} (clock-minus-market {_metric(row.get('next_game_minus_market_delta'))}), rest-of-season percentile "
            f"{_metric(row.get('rest_of_season_market_score'))} (clock-minus-market {_metric(row.get('rest_of_season_minus_market_delta'))}; delta {_metric(row.get('rest_of_season_minus_next_game_delta'))}), "
            f"dynasty percentile {_metric(row.get('dynasty_market_score'))} (clock-minus-market {_metric(row.get('dynasty_minus_market_delta'))}; delta {_metric(row.get('dynasty_minus_rest_of_season_delta'))}), "
            f"career-window percentile {_metric(row.get('career_projection_score'))} (clock-minus-market {_metric(row.get('career_minus_market_delta'))}; delta {_metric(row.get('career_minus_dynasty_delta'))}); "
            f"contender fit {_metric(row.get('contender_fit_score'))} vs rebuilder fit {_metric(row.get('rebuilder_fit_score'))}; "
            f"fit coverage {_clean(row.get('fit_coverage'), 'unavailable')}; price anchor market value {_metric(row.get('market_value'))}. "
            f"Availability is {_clean(row.get('availability_status'), 'unavailable')} from a Sleeper roster snapshot, not a waiver-eligibility or claim receipt; "
            f"{_clean(row.get('risk'), 'verify role, news, and eligibility before acting')}."
        )
    return "**Available market clock.** These names are research leads outside the selected league roster. The scores are separate position-relative percentiles, not dollar values or a cross-position rank; a missing clock stays missing.\n" + "\n".join(bullets)


def _horizon_market_disagreement_bullets(rows: list[dict[str, Any]]) -> list[str]:
    """Surface the largest same-position clock-versus-market disagreements.

    Each delta is already position-relative, so the selection is kept within
    position. This is a discovery queue for the writer and manager, not a
    claim that a positive delta proves a market error.
    """

    delta_fields = (
        ("next game", "next_game_minus_market_delta"),
        ("rest of season", "rest_of_season_minus_market_delta"),
        ("dynasty", "dynasty_minus_market_delta"),
        ("career window", "career_minus_market_delta"),
    )
    grouped: dict[str, list[tuple[dict[str, Any], list[tuple[float, str]]]]] = {}
    for row in rows:
        if not _clean(row.get("market_percentile")):
            continue
        deltas: list[tuple[float, str]] = []
        for label, field in delta_fields:
            raw = _clean(row.get(field))
            if not raw:
                continue
            try:
                deltas.append((float(raw), label))
            except (TypeError, ValueError):
                continue
        if deltas:
            grouped.setdefault(_clean(row.get("position"), "OTHER"), []).append((dict(row), deltas))

    output: list[str] = []
    for position in sorted(grouped):
        # Choose the strongest positive and negative leads independently across
        # the position cohort. Selecting a row by absolute disagreement first
        # can pair a meaningful lag with a trivial +0.08 delta from that same
        # player and hide the actual strongest positive lead elsewhere.
        positive_candidate = max(
            (
                (delta, label, row)
                for row, deltas in grouped[position]
                for delta, label in deltas
                if delta > 0
            ),
            default=None,
            key=lambda item: (item[0], _clean(item[2].get("player_name"))),
        )
        negative_candidate = min(
            (
                (delta, label, row)
                for row, deltas in grouped[position]
                for delta, label in deltas
                if delta < 0
            ),
            default=None,
            key=lambda item: (item[0], _clean(item[2].get("player_name"))),
        )
        selected_rows: list[tuple[dict[str, Any], list[tuple[float, str]]]] = []
        for candidate in (positive_candidate, negative_candidate):
            if candidate is None:
                continue
            row = candidate[2]
            existing = next((item for item in selected_rows if item[0] is row), None)
            if existing is None:
                selected_rows.append((row, []))
                existing = selected_rows[-1]
            existing[1].append((candidate[0], candidate[1]))
        if not selected_rows:
            selected_rows = [
                (row, [])
                for row, _ in sorted(
                    grouped[position],
                    key=lambda item: _clean(item[0].get("player_name")),
                )[:1]
            ]
        for row, selected_deltas in selected_rows:
            # If one player owns both extremes, retain both in one readable
            # bullet; otherwise each bullet represents its own player and its
            # strongest direction.
            deltas = selected_deltas or grouped[position][0][1]
            positive = max((item for item in deltas if item[0] > 0), default=None)
            negative = min((item for item in deltas if item[0] < 0), default=None)
            if positive and negative:
                read = (
                    f"{positive[1]} is {_metric(positive[0])} percentile points above the position market, "
                    f"while {negative[1]} is {_metric(negative[0])} below it"
                )
            elif positive:
                read = f"{positive[1]} is {_metric(positive[0])} percentile points above the position market"
            elif negative:
                read = f"{negative[1]} is {_metric(negative[0])} percentile points below the position market"
            else:
                read = "the available clock deltas are aligned with the position market"
            output.append(
                f"- **{position} — {_clean(row.get('player_name'), 'Unknown player')}**: {read}; "
                f"market value {_metric(row.get('market_value'))} remains the cross-position price anchor. "
                "This is a same-position repricing lead or lag for investigation, not proof that the market is wrong."
            )
    return output or ["- No comparable clock-versus-market disagreement is available for this edition."]


def _horizon_movement_bullets(rows: list[dict[str, Any]] | None) -> list[str]:
    """Publish dated horizon movement without turning it into a new score."""

    changed = [
        row for row in (rows or [])
        if _clean(row.get("movement_status")) == "changed" and _clean(row.get("player_name"))
    ]
    if not changed:
        return ["- No earlier exact-scope horizon snapshot is available; this edition establishes the movement baseline."]
    output: list[str] = []
    for row in sorted(
        changed,
        key=lambda item: (_num(item.get("largest_clock_movement_magnitude")), _clean(item.get("player_name"))),
        reverse=True,
    )[:8]:
        delta = _num(row.get("largest_clock_movement_delta"))
        direction = "rose" if delta > 0 else "fell" if delta < 0 else "held"
        output.append(
            f"- **{_clean(row.get('player_name'), 'Unknown player')}**: the {_human_label(row.get('largest_clock_movement_window'), 'clock')} "
            f"{direction} {_metric(abs(delta))} percentile points from week {_clean(row.get('prior_as_of_week'), 'unknown')} "
            f"to {_clean(row.get('current_as_of_week'), 'unknown')}; market-value delta {_metric(row.get('market_value_delta'))}, "
            f"lane {_human_label(row.get('value_lane'), 'unavailable')}. This is a dated exact-scope movement receipt, not a fifth score or proof of mispricing."
        )
    return output


def build_horizon_market_read(
    horizon_rows: list[dict[str, Any]],
    generated_at: str,
    writer_preferences: dict[str, Any] | None = None,
    movement_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Publish four decision windows as a dedicated evidence-led desk report."""

    rows = _horizon_rows_by_position(horizon_rows)
    lines = [
        _article_front_matter("horizon_watch", generated_at, writer_preferences),
        "# Four-Window Market Read",
        "",
        _horizon_market_intro(writer_preferences),
        "",
        "## This Week",
        _horizon_window_lede("next_game_market_score"),
        *_horizon_window_bullets(rows, "next_game_market_score", "next_game_status"),
        "",
        "## Rest of Season",
        _horizon_window_lede("rest_of_season_market_score"),
        *_horizon_window_bullets(rows, "rest_of_season_market_score", "rest_of_season_status"),
        "",
        "## Dynasty Window",
        _horizon_window_lede("dynasty_market_score"),
        *_horizon_window_bullets(rows, "dynasty_market_score", "dynasty_status", include_career=True),
        "",
        "## Market vs Clock",
        "The useful market question is where a clock moves away from its same-position price anchor. Those are research leads, not automatic buys or sells.",
        *_horizon_movement_bullets(movement_rows),
        *_horizon_market_disagreement_bullets(horizon_rows)[:4],
        "",
        "## Contender vs Rebuilder",
        "A contender weights usable points now; a rebuilder can pay more for dynasty and career-window value. The spread explains the audience, not the universal price.",
        *_horizon_fit_bullets(rows)[:4],
    ]
    return "\n".join(lines).strip() + "\n"


def _horizon_market_intro(writer_preferences: dict[str, Any] | None) -> str:
    persona_id = persona_metadata(writer_preferences, "horizon_watch")["persona_id"]
    if persona_id == "quant":
        return "The clocks are separate position-relative percentiles. Compare within position, use market value for cross-position price, and let the decision window choose the emphasis."
    if persona_id == "scout":
        return "A weekly need, a season plan, and a dynasty timeline can point in different directions. The useful read is the condition that makes each clock matter."
    return "The same player can be useful now, useful for the season, useful to a patient rebuild, or interesting only in the bounded career window. The four windows and their market deltas stay separate so the reader can choose the decision in front of them instead of accepting one universal grade."


def _horizon_window_lede(score_field: str) -> str:
    """Give each deterministic market a reader-facing decision question."""

    return {
        "next_game_market_score": "Decision question: who helps the lineup in the next game, after availability and matchup context?",
        "rest_of_season_market_score": "Decision question: who can supply dependable production across the remaining schedule?",
        "dynasty_market_score": "Decision question: who deserves patience when the roster is built beyond this season?",
    }.get(score_field, "Decision question: what does this market measure for the decision in front of us?")


def _horizon_window_bullets(
    rows: list[dict[str, Any]],
    score_field: str,
    status_field: str,
    *,
    include_career: bool = False,
) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if _clean(row.get(score_field)):
            grouped.setdefault(_clean(row.get("position"), "OTHER"), []).append(row)
    output: list[str] = []
    for position in sorted(grouped):
        # Keep the article to one representative lead per position. The full
        # cohort remains available in the data room and evidence drawer; the
        # publication surface should make the first read quickly actionable.
        ranked = sorted(grouped[position], key=lambda row: _num(row.get(score_field)), reverse=True)[:1]
        for row in ranked:
            name = _clean(row.get("player_name"), "Unknown player")
            status = _human_label(row.get(status_field), "status unavailable")
            details = [f"{_metric(row.get(score_field))} position-relative percentile", status]
            market_delta_field = {
                "next_game_market_score": "next_game_minus_market_delta",
                "rest_of_season_market_score": "rest_of_season_minus_market_delta",
                "dynasty_market_score": "dynasty_minus_market_delta",
                "career_projection_score": "career_minus_market_delta",
            }.get(score_field)
            if market_delta_field and _clean(row.get("market_percentile")) and _clean(row.get(market_delta_field)):
                details.append(
                    f"clock minus position market percentile {_metric(row.get(market_delta_field))}"
                )
            opponent = _clean(row.get("next_game_opponent"))
            if score_field == "next_game_market_score" and opponent:
                details.append(f"next opponent {opponent}")
            if score_field == "next_game_market_score" and _clean(row.get("next_game_matchup_validation_status")):
                validation = _human_label(row.get("next_game_matchup_validation_status"))
                games = _clean(row.get("next_game_matchup_validation_games"))
                details.append(f"matchup context {validation}{f' across {games} games' if games else ''}")
            if score_field == "next_game_market_score":
                transition = _clean(row.get("rest_of_season_minus_next_game_delta"))
                if transition:
                    details.append(f"rest-of-season minus next-game delta {_metric(transition)}")
            elif score_field == "rest_of_season_market_score":
                transition = _clean(row.get("dynasty_minus_rest_of_season_delta"))
                if transition:
                    details.append(f"dynasty minus rest-of-season delta {_metric(transition)}")
                ppg = _clean(row.get("rest_of_season_ppg") or row.get("projection_ppg"))
                if ppg:
                    details.append(baseline_ppg_text(row, _metric(ppg)))
            if include_career:
                details.append(f"five-year career-window percentile {_metric(row.get('career_projection_score'))}")
                transition = _clean(row.get("career_minus_dynasty_delta"))
                if transition:
                    details.append(f"career minus dynasty delta {_metric(transition)}")
                history_status = _clean(row.get("career_history_status"), "unavailable")
                if history_status == "matched":
                    details.append(
                        f"history anchor {_metric(row.get('career_history_ppg'))} PPG across "
                        f"{_clean(row.get('career_history_games'), '0')} games / "
                        f"{_clean(row.get('career_history_seasons'), '0')} seasons"
                    )
                else:
                    details.append(f"career history {history_status}")
            details.append(f"cross-position market value {_metric(row.get('market_value'))}")
            availability = _clean(row.get("availability_note"))
            if availability and not availability.lower().startswith("no current"):
                details.append(availability)
            availability_scope = _clean(row.get("availability_scope"))
            if availability_scope == "current_season_snapshot":
                details.append("availability scope current Sleeper snapshot")
            elif availability_scope == "historical_unavailable":
                details.append("historical availability unavailable by contract")
            output.append(f"- **{position} — {name}**: " + "; ".join(details) + ".")
    return output or ["- No usable horizon score is available for this window."]


def _horizon_fit_bullets(rows: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []
    for row in sorted(rows, key=lambda item: abs(_num(item.get("rebuilder_contender_spread"))), reverse=True)[:8]:
        spread = _clean(row.get("rebuilder_contender_spread"))
        if not spread:
            continue
        position = _clean(row.get("position"), "OTHER")
        name = _clean(row.get("player_name"), "Unknown player")
        lane = _human_label(row.get("value_lane"), "balanced window")
        output.append(
            f"- **{position} — {name}**: {lane}; contender fit {_metric(row.get('contender_fit_score'))} versus "
            f"rebuilder fit {_metric(row.get('rebuilder_fit_score'))} (spread {spread}; fit coverage {_clean(row.get('fit_coverage'), 'unavailable')}). "
            f"This is timeline fit, not a universal price or a claim about manager intent."
        )
    return output or ["- No contender-versus-rebuilder spread is available for this edition."]


def _horizon_market_note(rows: list[dict[str, Any]]) -> str:
    """Give deterministic fallback copy the same four-window evidence as a writer."""

    bullets = []
    for row in rows:
        name = _clean(row.get("player_name"), "Unknown player")
        lane = _clean(row.get("value_lane"), "balanced window").replace("_", " ")
        bullets.append(
            f"- **Window board:** {name} is a {lane}; next-game score {_metric(row.get('next_game_market_score'))}, "
            f"next-game minus market percentile {_metric(row.get('next_game_minus_market_delta'))}, "
            f"rest-of-season score {_metric(row.get('rest_of_season_market_score'))} "
            f"(minus market percentile {_metric(row.get('rest_of_season_minus_market_delta'))}; change from next game {_metric(row.get('rest_of_season_minus_next_game_delta'))}), "
            f"dynasty score {_metric(row.get('dynasty_market_score'))} "
            f"(minus market percentile {_metric(row.get('dynasty_minus_market_delta'))}; change from rest of season {_metric(row.get('dynasty_minus_rest_of_season_delta'))}). "
            f"Career-window score {_metric(row.get('career_projection_score'))} "
            f"(minus market percentile {_metric(row.get('career_minus_market_delta'))}; change from dynasty {_metric(row.get('career_minus_dynasty_delta'))}). "
            f"Career history {_clean(row.get('career_history_status'), 'unavailable')} "
            f"({_clean(row.get('career_history_games'), '0')} games / {_clean(row.get('career_history_seasons'), '0')} seasons; "
            f"historical PPG {_metric(row.get('career_history_ppg'))}). "
            f"Contender fit {_metric(row.get('contender_fit_score'))} vs rebuilder fit {_metric(row.get('rebuilder_fit_score'))} "
            f"(spread {_metric(row.get('rebuilder_contender_spread'))}); cross-position price anchor market value "
            f"{_metric(row.get('market_value'))}; market receipt {_metric(row.get('market_source_count'))} source(s), "
            f"disagreement {_metric(row.get('market_disagreement_score'))}, confidence {_clean(row.get('market_source_confidence'), 'unavailable')}."
        )
    return "**Four-window market board.** This sample is selected within position. The scores are separate position-relative percentiles, not one blended player grade or dollar market values; do not use them as cross-position price rankings. Rest-of-season scores are production baselines and are not recovery-adjusted forecasts. The clock-versus-market deltas are same-position repricing leads, not proof of mispricing. " + " ".join(bullets)


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
    dossier_items: list[dict[str, Any]] | None = None,
) -> str:
    cycles = _rows(dataframes.get("manager_cycle_profiles", pd.DataFrame()))
    dossiers = dossier_items if dossier_items is not None else build_manager_dossier_items(dataframes, generated_at)
    dossier_by_roster = {
        str(row.get("roster_id")): row
        for row in dossiers
        if isinstance(row, dict) and row.get("roster_id") not in (None, "")
    }
    enriched_cycles = [dict(dossier_by_roster.get(str(row.get("roster_id")), {}), **row) for row in cycles]
    rows = enriched_cycles or dossiers or cycles
    contenders = [row for row in rows if str(row.get("dynasty_cycle", "")) == "contender"]
    rebuilders = [row for row in rows if str(row.get("dynasty_cycle", "")) == "rebuild"]
    lines = [
        _article_front_matter("manager_intel", generated_at, writer_preferences, manager_count=len(rows)),
        "# Manager Intel",
        "",
        _manager_intel_intro(len(rows), writer_preferences, "manager_intel"),
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
    transaction_preferences = _rows(dataframes.get("manager_transaction_preferences", pd.DataFrame()))
    counterparty_edges = _rows(dataframes.get("counterparty_trade_edges", pd.DataFrame()))
    season_history_rows = _rows(dataframes.get("manager_season_history", pd.DataFrame()))
    tags_by_id: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        tags_by_id.setdefault(str(tag.get("entity_id", "")), []).append(tag)
    profile_by_id = {str(row.get("roster_id")): row for row in profiles if row.get("roster_id") not in (None, "")}
    profile_by_owner = {str(row.get("owner_id")): row for row in profiles if row.get("owner_id") not in (None, "")}
    needs_by_id = {str(row.get("roster_id")): row for row in needs if row.get("roster_id") not in (None, "")}
    items: list[dict[str, Any]] = []
    previous_by_roster = {
        str(item.get("roster_id")): item
        for item in (previous_items or [])
        if isinstance(item, dict) and item.get("roster_id") not in (None, "")
    }
    for index, cycle in enumerate(cycles, start=1):
        roster_id = str(cycle.get("roster_id", ""))
        owner_id = str(cycle.get("owner_id") or "")
        profile = profile_by_owner.get(owner_id) or profile_by_id.get(roster_id, {})
        owner_id = owner_id or str(profile.get("owner_id") or "")
        selected_tags = tags_by_id.get(roster_id, [])[:6]
        tag_text = ", ".join(str(tag.get("tag", "")) for tag in selected_tags if tag.get("tag"))
        evidence = str(cycle.get("evidence", ""))
        history_pairs = _manager_history_pairs(profile, roster_id)
        manager_events = [row for row in events if _manager_history_row_matches(row, owner_id, history_pairs, roster_id)]
        manager_seasons = [row for row in season_history_rows if _manager_history_row_matches(row, owner_id, history_pairs, roster_id)]
        transaction_timeline = _manager_transaction_timeline(manager_events)
        manager_assets = [row for row in inventory if str(row.get("roster_id")) == roster_id]
        manager_needs = needs_by_id.get(roster_id, {})
        manager_preferences = [row for row in valuation_profiles if str(row.get("roster_id")) == roster_id]
        manager_transaction_lanes = [row for row in transaction_preferences if str(row.get("roster_id")) == roster_id]
        manager_edges = [row for row in counterparty_edges if str(row.get("target_roster_id")) == roster_id]
        manager_asset_interest = [row for row in _rows(dataframes.get("counterparty_asset_interest", pd.DataFrame())) if str(row.get("target_roster_id")) == roster_id]
        outcome_summary = _manager_outcome_summary(manager_seasons)
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
                "transaction_preferences": manager_transaction_lanes,
                "edges": manager_edges,
                "asset_interest": manager_asset_interest,
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
            "matchups": outcome_summary["matchups"],
            "scheduled_matchup_rows": outcome_summary["scheduled_matchup_rows"],
            "scored_matchups": outcome_summary["scored_matchups"],
            "seasons_with_outcomes": outcome_summary["seasons_with_outcomes"],
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
        # Alias-only compatibility rows preserve historical names, but they do
        # not carry enough activity/outcome grain to support a trajectory.
        # Require the canonical manager_season_history seam or fail closed.
        trajectory = _manager_trajectory(manager_seasons)
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
        if outcome_summary["status"] != "not_recorded":
            behavior_observations.append(
                {
                    "label": "Season outcomes",
                    "value": outcome_summary["record"],
                    "evidence": outcome_summary["evidence"],
                }
            )
        trade_fits = [
            {
                "player_id": row.get("player_id", ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
                "edge_type": row.get("edge_type", ""),
                "trade_edge_score": row.get("trade_edge_score", ""),
                "market_consensus_value": row.get("market_consensus_value", ""),
                "estimated_owner_value_score": row.get("estimated_owner_value_score", ""),
                "target_team_lens": row.get("target_team_lens", ""),
                "target_horizon_fit_score": row.get("target_horizon_fit_score", ""),
                "active_horizon_fit_score": row.get("active_horizon_fit_score", ""),
                "horizon_fit_edge": row.get("horizon_fit_edge", ""),
                "horizon_fit_read": row.get("horizon_fit_read", ""),
                "horizon_fit_basis": row.get("horizon_fit_basis", ""),
                "horizon_model_version": row.get("horizon_model_version", ""),
                "horizon_market_percentile": row.get("horizon_market_percentile", ""),
                "next_game_market_score": row.get("next_game_market_score", ""),
                "rest_of_season_market_score": row.get("rest_of_season_market_score", ""),
                "dynasty_market_score": row.get("dynasty_market_score", ""),
                "career_projection_score": row.get("career_projection_score", ""),
                "next_game_minus_market_delta": row.get("next_game_minus_market_delta", ""),
                "rest_of_season_minus_market_delta": row.get("rest_of_season_minus_market_delta", ""),
                "dynasty_minus_market_delta": row.get("dynasty_minus_market_delta", ""),
                "career_minus_market_delta": row.get("career_minus_market_delta", ""),
                "horizon_market_disagreement_window": row.get("horizon_market_disagreement_window", ""),
                "horizon_market_disagreement_delta": row.get("horizon_market_disagreement_delta", ""),
                "horizon_market_disagreement_magnitude": row.get("horizon_market_disagreement_magnitude", ""),
                "horizon_market_disagreement_read": row.get("horizon_market_disagreement_read", ""),
                "evidence": row.get("evidence", ""),
                "risk": row.get("risk", ""),
                "confidence": row.get("confidence", ""),
                "source_trace": row.get("source_trace", ""),
            }
            for row in sorted(manager_edges, key=lambda value: _num(value.get("trade_edge_score")), reverse=True)[:6]
        ]
        trade_fit_status = "supported" if trade_fits else "none_supported"
        trade_fit_evaluation = _manager_trade_fit_evaluation(manager_preferences, trade_fits, manager_seasons)
        trade_fit_summary = trade_fit_evaluation["summary"]
        transaction_profile = _manager_transaction_profile(manager_transaction_lanes)
        counterparty_interest = _manager_counterparty_interest(manager_asset_interest)
        questions = _manager_questions(cycle, profile, manager_needs, trade_fits)
        dossier_source_trace = "manager_cycle_profiles;manager_profile_tags;manager_profiles;manager_event_log;manager_season_history"
        if manager_transaction_lanes:
            dossier_source_trace += ";manager_transaction_preferences"
        if manager_asset_interest:
            dossier_source_trace += ";counterparty_asset_interest"
        if outcome_summary["status"] != "not_recorded":
            dossier_source_trace += ";matchups"
        items.append(
            {
                "dossier_id": f"manager-{index:03d}",
                "owner_id": owner_id,
                "roster_id": _int(roster_id),
                "team_name": cycle.get("team_name", ""),
                "dynasty_cycle": cycle.get("dynasty_cycle", ""),
                "tags": tag_text,
                "evidence": evidence,
                "risk": risk,
                "confidence": cycle.get("confidence", "low"),
                "source_trace": dossier_source_trace,
                "sample_size": sample_size,
                "roster_construction": roster_construction,
                "outcome_summary": outcome_summary,
                "historical_aliases": historical_aliases,
                "season_history": season_history,
                "trajectory": trajectory,
                "transaction_timeline": transaction_timeline,
                "repeated_behavior": repeated_behavior,
                "behavior_observations": behavior_observations,
                "trade_fits": trade_fits,
                "trade_fit_status": trade_fit_status,
                "trade_fit_summary": trade_fit_summary,
                "trade_fit_evaluation": trade_fit_evaluation,
                "transaction_profile": transaction_profile,
                "counterparty_interest": counterparty_interest,
                "questions_to_ask": questions,
                "unknowns": [
                    "Manager intent is not observed in Sleeper data.",
                    "A trade fit is a model-supported conversation hypothesis, not a predicted response.",
                ] + (["Season outcome rows are not recorded in this source snapshot."] if outcome_summary["status"] == "not_recorded" else []),
                "analysis_text": (
                    f"{cycle.get('team_name', 'This manager')} profiles as {cycle.get('dynasty_cycle', 'unclear')} "
                    f"with {cycle.get('trade_temperature', 'unknown trade activity')} and {cycle.get('pick_posture', 'unclear pick posture')}. "
                    f"The profile covers {sample_size['seasons']} seasons and {sample_size['trades']} observed trades. "
                    f"{outcome_summary['narrative']} {trajectory['summary']} Tags: {tag_text or 'none'}. Evidence: {evidence}."
                ),
                "evidence_fingerprint": fingerprint,
                "update_status": update_status,
                "updated_fields": _changed_dossier_fields(previous, cycle, tag_text),
                "generated_at": generated_at,
            }
        )
    return items


def _manager_history_pairs(profile: Mapping[str, Any], current_roster_id: str) -> set[tuple[str, int]]:
    """Parse the owner-linked roster lineage stored by manager_profiles."""

    pairs: set[tuple[str, int]] = set()
    for value in _split_values(profile.get("roster_ids_by_season")):
        if ":" not in value:
            continue
        season, roster = value.split(":", 1)
        roster_id = _int(roster)
        if _clean(season) and roster_id:
            pairs.add((_clean(season), roster_id))
    return pairs


def _manager_history_row_matches(
    row: Mapping[str, Any],
    owner_id: str,
    history_pairs: set[tuple[str, int]],
    current_roster_id: str,
) -> bool:
    """Prefer stable Sleeper owner identity, with pair fallback for legacy event rows."""

    row_owner = _clean(row.get("owner_id"))
    if owner_id and row_owner:
        return row_owner == owner_id
    season = _clean(row.get("season"))
    roster_id = _int(row.get("roster_id"))
    if (season, roster_id) in history_pairs or (not season and ("", roster_id) in history_pairs):
        return True
    return not history_pairs and roster_id == _int(current_roster_id)


def _manager_trajectory(season_history: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the latest observed seasons with the prior observed window.

    This is deliberately descriptive.  It does not turn a partial current
    season into a forecast or infer why a manager changed behavior.  The
    dossier carries both windows and the underlying season IDs so a writer or
    reader can inspect the same rows before treating the trend as useful.
    """

    rows = [
        dict(row)
        for row in season_history
        if _int(row.get("season"))
    ]
    rows.sort(key=lambda row: _int(row.get("season")))
    if not rows:
        return {
            "status": "not_available",
            "recent_seasons": [],
            "prior_seasons": [],
            "recent": {},
            "prior": {},
            "activity_read": "not available",
            "outcome_read": "not comparable",
            "outcome_status": "not_comparable",
            "outcome_recent_seasons": [],
            "outcome_prior_seasons": [],
            "summary": "No season history is available for a trajectory comparison.",
            "evidence": "manager_season_history; no comparable season rows",
            "risk": "No historical window is available; do not infer a manager trend.",
            "source_trace": "manager_season_history",
        }

    recent = rows[-2:]
    prior = rows[:-2][-2:]
    recent_metrics = _trajectory_window_metrics(recent)
    prior_metrics = _trajectory_window_metrics(prior)
    if not prior:
        return {
            "status": "insufficient_history",
            "recent_seasons": recent_metrics["seasons"],
            "prior_seasons": [],
            "recent": recent_metrics,
            "prior": {},
            "activity_read": "not comparable",
            "outcome_read": "not comparable",
            "outcome_status": "not_comparable",
            "outcome_recent_seasons": recent_metrics["outcome_seasons"],
            "outcome_prior_seasons": [],
            "summary": (
                f"Latest observed window ({_season_label(recent_metrics['seasons'])}) has "
                f"{recent_metrics['trades']} trades and {recent_metrics['waiver_claims']} waiver claims; "
                "there is not enough prior history to call a trend."
            ),
            "evidence": f"manager_season_history; recent_seasons={_season_label(recent_metrics['seasons'])}; prior_seasons=none",
            "risk": "The latest window has no comparable prior window and may be partial.",
            "source_trace": "manager_season_history;matchups",
        }

    activity_delta = round(recent_metrics["activity_per_season"] - prior_metrics["activity_per_season"], 2)
    activity_read = _trajectory_direction(activity_delta, "more active", "quieter", "steady")
    outcome_delta = None
    outcome_read = "not comparable"
    outcome_status = "not_comparable"
    if (
        len(recent_metrics["outcome_seasons"]) >= 2
        and len(prior_metrics["outcome_seasons"]) >= 2
        and recent_metrics["win_rate"] is not None
        and prior_metrics["win_rate"] is not None
    ):
        outcome_delta = round(recent_metrics["win_rate"] - prior_metrics["win_rate"], 3)
        outcome_read = _trajectory_direction(outcome_delta, "stronger results", "weaker results", "similar results", threshold=0.10)
        outcome_status = "comparable"
    elif recent_metrics["outcome_seasons"] and prior_metrics["outcome_seasons"]:
        outcome_read = "limited coverage"
        outcome_status = "limited"
    recent_label = _season_label(recent_metrics["seasons"])
    prior_label = _season_label(prior_metrics["seasons"])
    recent_outcome_label = _season_label(recent_metrics["outcome_seasons"])
    prior_outcome_label = _season_label(prior_metrics["outcome_seasons"])
    partial_recent_label = _season_label(recent_metrics["partial_seasons"])
    if outcome_status == "comparable":
        outcome_clause = f" Outcomes read as {outcome_read}."
    elif outcome_status == "limited":
        outcome_clause = (
            f" Outcome comparison is limited: recorded seasons are recent {recent_outcome_label}, "
            f"prior {prior_outcome_label}; partial recent seasons: {partial_recent_label}."
        )
    else:
        outcome_clause = " Outcomes are not comparable across both windows."
    activity_clause = (
        f"is {activity_read} than the prior window"
        if activity_read != "steady"
        else "is steady compared with the prior window"
    )
    return {
        "status": "comparison",
        "recent_seasons": recent_metrics["seasons"],
        "prior_seasons": prior_metrics["seasons"],
        "recent": recent_metrics,
        "prior": prior_metrics,
        "activity_delta_per_season": activity_delta,
        "outcome_win_rate_delta": outcome_delta,
        "activity_read": activity_read,
        "outcome_read": outcome_read,
        "outcome_status": outcome_status,
        "outcome_recent_seasons": recent_metrics["outcome_seasons"],
        "outcome_prior_seasons": prior_metrics["outcome_seasons"],
        "partial_recent_seasons": recent_metrics["partial_seasons"],
        "summary": (
            f"Latest observed window ({recent_label}) {activity_clause} "
            f"({prior_label}) by {abs(activity_delta):.2f} transactions per season.{outcome_clause}"
        ),
        "evidence": (
            f"manager_season_history; recent_seasons={recent_label}; prior_seasons={prior_label}; "
            f"recent_outcome_seasons={recent_outcome_label}; prior_outcome_seasons={prior_outcome_label}; "
            f"partial_recent_seasons={partial_recent_label}; "
            f"recent_activity_per_season={recent_metrics['activity_per_season']}; "
            f"prior_activity_per_season={prior_metrics['activity_per_season']}; "
            f"activity_delta={activity_delta}; outcome_delta={outcome_delta if outcome_delta is not None else 'n/a'}"
        ),
        "risk": "Recent activity is descriptive, not intent; partial seasons are excluded from outcome comparisons.",
        "source_trace": "manager_season_history;matchups",
    }


def _trajectory_window_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seasons = [_int(row.get("season")) for row in rows if _int(row.get("season"))]
    season_count = len(seasons)
    trades = sum(_int(row.get("trades")) for row in rows)
    waiver_claims = sum(_int(row.get("waiver_claims")) for row in rows)
    transaction_count = sum(_int(row.get("transaction_count")) for row in rows)
    faab_spent = round(sum(_num(row.get("faab_spent")) for row in rows), 2)
    outcome_rows = [
        row for row in rows
        if str(row.get("outcome_status") or "").lower() == "recorded"
    ]
    partial_rows = [
        row for row in rows
        if str(row.get("outcome_status") or "").lower() == "partial"
    ]
    wins = sum(_int(row.get("wins")) for row in outcome_rows)
    losses = sum(_int(row.get("losses")) for row in outcome_rows)
    ties = sum(_int(row.get("ties")) for row in outcome_rows)
    played = wins + losses + ties
    return {
        "seasons": seasons,
        "season_count": season_count,
        "trades": trades,
        "waiver_claims": waiver_claims,
        "transaction_count": transaction_count,
        "faab_spent": faab_spent,
        "activity_per_season": round((trades + waiver_claims) / season_count, 2) if season_count else 0.0,
        "record": f"{wins}-{losses}-{ties}" if played else "not recorded",
        "outcome_seasons": [_int(row.get("season")) for row in outcome_rows if _int(row.get("season"))],
        "partial_seasons": [_int(row.get("season")) for row in partial_rows if _int(row.get("season"))],
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "played": played,
        "win_rate": round(wins / played, 3) if played else None,
    }


def _trajectory_direction(value: float, positive: str, negative: str, neutral: str, threshold: float = 2.0) -> str:
    if value >= threshold:
        return positive
    if value <= -threshold:
        return negative
    return neutral


def _season_label(seasons: list[int]) -> str:
    return ", ".join(str(season) for season in seasons) if seasons else "none"


def _manager_outcome_summary(manager_seasons: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize observed Sleeper matchup outcomes without treating absence as 0-0.

    A manager dossier may outlive a source refresh. The explicit status keeps a
    missing matchup endpoint, an offseason snapshot, and a recorded losing
    season distinct in both the data room and the editorial layer.
    """

    outcome_rows = [
        row
        for row in manager_seasons
        if str(row.get("outcome_status") or "").lower() in {"recorded", "partial"}
    ]
    status = "not_recorded"
    if any(str(row.get("outcome_status") or "").lower() == "recorded" for row in outcome_rows):
        status = "recorded"
    elif outcome_rows:
        status = "partial"
    wins = sum(_int(row.get("wins")) for row in outcome_rows)
    losses = sum(_int(row.get("losses")) for row in outcome_rows)
    ties = sum(_int(row.get("ties")) for row in outcome_rows)
    played = wins + losses + ties
    points_for = sum(_num(row.get("points_for")) for row in outcome_rows if row.get("points_for") not in (None, ""))
    points_against = sum(_num(row.get("points_against")) for row in outcome_rows if row.get("points_against") not in (None, ""))
    points_seen = any(row.get("points_for") not in (None, "") or row.get("points_against") not in (None, "") for row in outcome_rows)
    matchups = sum(len(_split_values(row.get("matchup_weeks"))) for row in outcome_rows)
    seasons_with_outcomes = sum(1 for row in outcome_rows if str(row.get("outcome_status") or "").lower() == "recorded")
    record = f"{wins}-{losses}-{ties}" if played else "not recorded"
    points_text = f"; points {round(points_for, 2)} for / {round(points_against, 2)} against" if points_seen else ""
    if status == "not_recorded":
        narrative = "Season outcomes are not recorded in this source snapshot."
        evidence = "manager_season_history; outcome_status=not_recorded"
    else:
        narrative = f"Observed season outcome record: {record} across {played} scored matchup weeks{points_text}."
        evidence = (
            f"manager_season_history; outcome_status={status}; "
            f"scheduled_matchup_rows={matchups}; scored_matchups={played}; record={record}"
        )
    return {
        "status": status,
        "record": record,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "played": played,
        "matchups": matchups,
        "scheduled_matchup_rows": matchups,
        "scored_matchups": played,
        "seasons_with_outcomes": seasons_with_outcomes,
        "points_for": round(points_for, 2) if points_seen else "",
        "points_against": round(points_against, 2) if points_seen else "",
        "point_diff": round(points_for - points_against, 2) if points_seen else "",
        "win_rate": round(wins / played, 3) if played else "",
        "evidence": evidence,
        "source_trace": "manager_season_history;matchups" if status != "not_recorded" else "manager_season_history",
        "narrative": narrative,
    }


def _manager_transaction_timeline(
    events: list[dict[str, Any]],
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Return a bounded, roster-scoped event ledger for the manager dossier.

    ``manager_event_log`` is already deterministic source data. The dossier
    keeps the event grain instead of asking the browser to reconstruct a
    timeline from aggregate season totals. This is evidence presentation, not
    an inference about motive or a forecast of the next transaction.
    """

    ordered = sorted(
        events,
        key=lambda row: (
            str(row.get("created_datetime") or ""),
            _int(row.get("season")),
            _int(row.get("week")),
            str(row.get("transaction_id") or ""),
        ),
        reverse=True,
    )
    fields = (
        "season",
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
    )
    timeline: list[dict[str, Any]] = []
    for row in ordered[:limit]:
        timeline.append(
            {
                "event_id": str(row.get("transaction_id") or ""),
                "source_trace": "manager_event_log",
                **{field: row.get(field, "") for field in fields},
            }
        )
    return timeline


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
    _attach_horizon_rows(
        dossiers,
        dataframes.get("player_horizon_market_scores", pd.DataFrame()),
    )
    tags = _rows(dataframes.get("player_profile_tags", pd.DataFrame()))
    tags_by_id: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        tags_by_id.setdefault(str(tag.get("entity_id", "")), []).append(tag)
    items: list[dict[str, Any]] = []
    for index, player in enumerate(dossiers, start=1):
        player_id = str(player.get("player_id", ""))
        selected_tags = tags_by_id.get(player_id, [])[:6]
        tag_text = ", ".join(str(tag.get("tag", "")) for tag in selected_tags if tag.get("tag"))
        horizon_text = (
            f"four-window scores: this week {_metric(player.get('next_game_market_score'))}, "
            f"rest of season {_metric(player.get('rest_of_season_market_score'))}, "
            f"dynasty {_metric(player.get('dynasty_market_score'))}, "
            f"career window {_metric(player.get('career_projection_score'))}; "
            f"contender fit {_metric(player.get('contender_fit_score'))}, "
            f"rebuilder fit {_metric(player.get('rebuilder_fit_score'))}; "
            f"fit coverage {_clean(player.get('fit_coverage'), 'unavailable')}"
        )
        ppg_text = baseline_ppg_text(player, _metric(player.get("projected_ppg")))
        evidence = (
            f"{ppg_text}; market={player.get('market_value', 0)}; "
            f"signal={player.get('signal_label', '')}; news={player.get('news_impact', '')}; transactions={player.get('transaction_count', 0)}; "
            f"{horizon_text}"
        )
        horizon_source = _clean(player.get("horizon_source_trace"))
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
                "injury_status": player.get("injury_status", ""),
                "availability_note": player.get("availability_note", ""),
                "current_availability_status": player.get("current_availability_status", ""),
                "next_game_market_score": player.get("next_game_market_score", ""),
                "rest_of_season_market_score": player.get("rest_of_season_market_score", ""),
                "dynasty_market_score": player.get("dynasty_market_score", ""),
                "career_projection_score": player.get("career_projection_score", ""),
                "contender_fit_score": player.get("contender_fit_score", ""),
                "rebuilder_fit_score": player.get("rebuilder_fit_score", ""),
                "rest_of_season_ppg": player.get("rest_of_season_ppg", ""),
                "career_projection_status": player.get("career_projection_status", ""),
                "fit_coverage": player.get("fit_coverage", ""),
                "horizon_model_version": player.get("horizon_model_version", ""),
                "horizon_score_basis": player.get("horizon_score_basis", ""),
                "availability_scope": player.get("availability_scope", ""),
                "risk": "medium: deterministic player tag and horizon context, not a guaranteed outcome; horizon scores are position-relative, not cross-position prices",
                "confidence": player.get("projection_confidence", "low"),
                "source_trace": ";".join(
                    value
                    for value in (
                        player.get("source_trace", "") or "player_dossiers;player_profile_tags",
                        horizon_source,
                    )
                    if value
                ),
                "analysis_text": (
                    f"{player.get('player_name', 'This player')} carries tags {tag_text or 'none'} from projection, market, news, "
                    f"and league transaction signals. {horizon_text}. Evidence: {evidence}."
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


def _attach_horizon_rows(
    players: list[dict[str, Any]],
    horizon_df: pd.DataFrame | None,
    league_id: str = "",
) -> None:
    """Join horizon evidence to a roster-scoped player row for deterministic prose."""

    horizon_rows = _rows(horizon_df if isinstance(horizon_df, pd.DataFrame) else pd.DataFrame())
    by_key = {
        (
            str(row.get("player_id")),
            str(row.get("roster_id")),
            _clean(row.get("league_id")),
        ): row
        for row in horizon_rows
        if _clean(row.get("player_id"))
    }
    legacy_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in horizon_rows:
        if _clean(row.get("player_id")) and not _clean(row.get("league_id")):
            legacy_by_key.setdefault(
                (str(row.get("player_id")), str(row.get("roster_id"))), []
            ).append(row)
    for player in players:
        key = (
            str(player.get("player_id")),
            str(player.get("roster_id")),
            _clean(league_id or player.get("league_id")),
        )
        horizon = by_key.get(key, {})
        if not horizon:
            legacy_rows = legacy_by_key.get(key[:2], [])
            horizon = legacy_rows[0] if len(legacy_rows) == 1 else {}
        for field in (
            "horizon_model_version",
            "as_of_week",
            "next_game_week",
            "horizon_score_basis",
            "market_value",
            "market_percentile",
            "next_game_baseline_points",
            "next_game_expected_points",
            "next_game_market_score",
            "next_game_status",
            "next_game_opponent",
            "next_game_home_away",
            "next_game_schedule_status",
            "next_game_matchup_factor",
            "next_game_matchup_validation_status",
            "next_game_matchup_validation_games",
            "next_game_matchup_validation_mae_delta",
            "next_game_matchup_adjustment_status",
            "rest_of_season_weeks",
            "rest_of_season_games",
            "rest_of_season_bye_weeks",
            "rest_of_season_baseline_points",
            "rest_of_season_ppg",
            "rest_of_season_market_score",
            "rest_of_season_status",
            "schedule_status",
            "dynasty_market_score",
            "dynasty_status",
            "career_projection_years",
            "career_projection_points",
            "career_projection_ppg",
            "career_projection_score",
            "career_projection_status",
            "career_projection_basis",
            "career_history_join_method",
            "career_history_source_player_id",
            "career_history_status",
            "career_history_seasons",
            "career_history_games",
            "career_history_ppg",
            "career_history_latest_season",
            "contender_fit_score",
            "rebuilder_fit_score",
            "fit_coverage",
            "fit_basis",
            "rebuilder_contender_spread",
            "value_lane",
            "horizon_risk",
            "horizon_source_trace",
        ):
            if field == "horizon_risk":
                player[field] = horizon.get("risk", "")
            elif field == "horizon_source_trace":
                value = horizon.get("source_trace", "")
                if _clean(value) or field not in player:
                    player[field] = value
            else:
                value = horizon.get(field, "")
                # Horizon rows are an enrichment, not a replacement for the
                # canonical dossier.  A partial/stale horizon bundle must not
                # erase a market value or another already-joined fact.
                if field in {"market_value", "market_percentile"} and _clean(player.get(field)):
                    continue
                if _clean(value) or field not in player:
                    player[field] = value


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
            f"The {team_name} edition is a measured decision memo: market values, baseline PPG, thresholds, and confidence before adjectives."
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
        lead = "Ranking blends market value, baseline PPG, breakout score, and starter status; it is not a league-wide trade value claim."
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
    ppg_text = baseline_ppg_text(row, ppg)
    confidence = _clean(row.get("projection_confidence"), "unknown")
    signal = _human_label(row.get("signal_label"), "no strong signal")
    news = _human_label(row.get("news_impact"), "none")
    transactions = _metric(row.get("transaction_count"), integer=True)
    last_transaction = _human_label(row.get("last_transaction"), "not recorded")
    evidence = (
        f"{position}, {status}; market value {market}; {ppg_text} ({confidence} confidence); "
        "rest-of-season baseline is not recovery-adjusted; "
        f"availability {_clean(row.get('availability_note'), 'not recorded')}; "
        f"signal {signal}; news {news}; {transactions} league transactions, most recent {last_transaction}."
    )
    if row.get("next_game_status") or row.get("dynasty_status"):
        ros_context = _rest_of_season_context(row)
        evidence += (
            f" Four-window model {_clean(row.get('horizon_model_version'), 'unversioned')}: next game {_metric(row.get('next_game_market_score'))} "
            f"(expected {_metric(row.get('next_game_expected_points'))} points vs {_clean(row.get('next_game_opponent'), 'opponent unavailable')}; {_clean(row.get('next_game_status'), 'status unavailable')}), "
            f"rest of season {_metric(row.get('rest_of_season_market_score'))} {ros_context}, dynasty market {_metric(row.get('dynasty_market_score'))}, "
            f"five-year career-window score {_metric(row.get('career_projection_score'))}; "
            f"contender fit {_metric(row.get('contender_fit_score'))} vs rebuilder fit {_metric(row.get('rebuilder_fit_score'))}; "
            f"cross-position price anchor market value {_metric(row.get('market_value'))}."
        )
        evidence += f" Scores are {_clean(row.get('horizon_score_basis'), 'position-relative percentiles, not dollar market values')}"
    if section == "shop":
        read = _shop_read(row)
    else:
        read = _cornerstone_read(row)
    return f"{evidence} {_persona_read(read, writer_preferences, article_key)}"


def _rest_of_season_context(row: dict[str, Any]) -> str:
    """Describe the ROS input without presenting missing schedule coverage as a game count."""

    value = _clean(row.get("rest_of_season_games"))
    if value:
        return f"across {_metric(value, integer=True)} scheduled games"
    return "from the season projection baseline; scheduled game count unavailable"


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
        horizon_read = ""
        if _clean(row.get("horizon_fit_read")):
            horizon_read = (
                f" Timeline fit: {_human_label(row.get('horizon_fit_read'))}; target lens "
                f"{_clean(row.get('target_team_lens'), 'unclassified')} at "
                f"{_metric(row.get('target_horizon_fit_score'))}, active lens at "
                f"{_metric(row.get('active_horizon_fit_score'))} (edge {_metric(row.get('horizon_fit_edge'))}); "
                "this is separate from market price and is not a trade quote."
            )
        if _clean(row.get("horizon_market_disagreement_window")):
            horizon_read += (
                f" Largest same-position clock-versus-market lead: "
                f"{_human_label(row.get('horizon_market_disagreement_window'))} "
                f"at {_metric(row.get('horizon_market_disagreement_delta'))} "
                f"({_human_label(row.get('horizon_market_disagreement_read'))}); "
                "research lead only, not a dollar gap."
            )
        bullets.append(
            f"- **{manager}** — Approach: {approach}. Observed signal: {signal}. Named lane: {assets}. "
            f"{packet}{horizon_read} Evidence: {evidence}. Confidence: {confidence}. Guardrail: {risk}. "
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
        sample = row.get("sample_size") if isinstance(row.get("sample_size"), Mapping) else {}
        outcome = row.get("outcome_summary") if isinstance(row.get("outcome_summary"), Mapping) else {}
        trajectory = row.get("trajectory") if isinstance(row.get("trajectory"), Mapping) else {}
        depth: list[str] = []
        if sample:
            depth.append(
                f"history={sample.get('seasons', 0)} seasons/{sample.get('trades', 0)} trades/{sample.get('matchups', 0)} matchups"
            )
        if outcome and outcome.get("status") not in (None, "", "not_recorded"):
            depth.append(f"record={outcome.get('record', 'not recorded')} ({outcome.get('status')})")
        if trajectory and trajectory.get("status") not in (None, "", "not_available"):
            depth.append(f"trajectory={str(trajectory.get('summary', 'comparison available')).rstrip('.')}")
        fit_summary = _clean(row.get("trade_fit_summary"))
        if fit_summary and not fit_summary.lower().startswith("no supported"):
            depth.append(f"fit={fit_summary.rstrip('.')}")
        transaction_profile = row.get("transaction_profile") if isinstance(row.get("transaction_profile"), Mapping) else {}
        transaction_lanes = transaction_profile.get("lanes") if isinstance(transaction_profile.get("lanes"), list) else []
        if transaction_lanes:
            lane_text = ", ".join(
                f"{_clean(lane.get('position_group'), 'unknown')} {_clean(lane.get('transaction_read'), 'observed lane')} "
                f"({lane.get('acquired_count', 0)} acquired/{lane.get('sold_count', 0)} sold)"
                for lane in transaction_lanes[:3]
            )
            depth.append(f"movement={lane_text}")
            coverage = transaction_profile.get("horizon_coverage_by_clock")
            if isinstance(coverage, Mapping):
                coverage_text = "; ".join(
                    f"{_human_label(clock)} acquired {value.get('acquired', 0)}/{value.get('acquired_total', 0)}, "
                    f"sold {value.get('sold', 0)}/{value.get('sold_total', 0)}"
                    for clock, value in coverage.items()
                    if isinstance(value, Mapping)
                )
                if coverage_text:
                    depth.append(f"horizon coverage={coverage_text}")
        depth_text = f" Deep read: {'; '.join(depth)}." if depth else ""
        bullets.append(
            f"- **{team}** — Cycle: {cycle}. Likely need: {needs}. Possible sell lane: {sells}. "
            f"Observed behavior: {trade}; {picks}. Confidence: {confidence}. Evidence: {evidence}. "
            f"{depth_text} {_persona_read('Use the profile to choose a question, never to infer motive.', writer_preferences, article_key)}"
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
        "player_projection_weekly",
        "player_horizon_market_scores",
        "available_player_horizon_scores",
        "market_consensus_values",
        "nfl_schedule",
        "nfl_team_defense_factors",
        "player_signal_scores",
        "news_market_edges",
        "player_dossiers",
        "player_profile_tags",
        "breakout_candidates",
        "sell_candidates",
        "league_news_impact",
        "manager_behavior_signals",
        "manager_cycle_profiles",
        "manager_transaction_preferences",
        "counterparty_trade_edges",
        "counterparty_asset_interest",
        "manager_profile_tags",
        "opportunity_board",
    ]


def _configured_league_id(config: Mapping[str, Any] | None) -> str:
    """Resolve the current league from the authenticated scope before legacy config."""

    config = config or {}
    context = config.get("context")
    if isinstance(context, Mapping) and _clean(context.get("league_id")):
        return _clean(context.get("league_id"))
    current_season = _clean(config.get("current_season"))
    leagues = config.get("leagues")
    if isinstance(leagues, Mapping):
        return _clean(leagues.get(current_season))
    return ""


def _scope_current_rows(
    frame: pd.DataFrame | None,
    league_id: str = "",
    season: str = "",
) -> list[dict[str, Any]]:
    """Select one league/season while retaining legacy unscoped fixtures."""

    rows = _rows(frame if isinstance(frame, pd.DataFrame) else pd.DataFrame())
    if league_id:
        identified = [row for row in rows if _clean(row.get("league_id"))]
        scoped = [row for row in identified if _same_identifier(row.get("league_id"), league_id)]
        rows = scoped or [row for row in rows if not _clean(row.get("league_id"))]
    if season:
        matching = [row for row in rows if _same_identifier(row.get("season"), season)]
        rows = matching or rows
    return rows


def _same_identifier(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    left_text = str(left).strip()
    right_text = str(right).strip()
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except (TypeError, ValueError):
        return False


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
