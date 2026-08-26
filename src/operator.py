from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import traceback
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from . import articles
from .browser_site import build_browser_site
from .context import FantasyContext
from .league_paths import LeaguePaths
from .llm import call_structured_tool, configured_llm, writer_api_configuration
from .personas import persona_metadata, persona_prompt_block
from .utils import (
    ANALYSIS_DIR,
    OPERATOR_INBOX_DIR,
    OPERATOR_OUTBOX_DIR,
    OPERATOR_STATUS_DIR,
    PROCESSED_DIR,
    SITE_DIR,
    load_json,
)


STATUS_PATH = OPERATOR_STATUS_DIR / "operator_status.json"
INSIGHT_PACKET_PATH = OPERATOR_INBOX_DIR / "front_office_insight_packet.json"
INSIGHT_OUTPUT_PATH = OPERATOR_OUTBOX_DIR / "front_office_insight_cards.json"
VALIDATED_INSIGHTS_PATH = ANALYSIS_DIR / "validated_insight_cards.json"
INSIGHT_VALIDATION_PATH = ANALYSIS_DIR / "insight_card_validation.json"
DAILY_GM_BRIEF_PATH = ANALYSIS_DIR / "daily_gm_brief.md"
DAILY_GM_BRIEF_VALIDATION_PATH = ANALYSIS_DIR / "daily_gm_brief_validation.json"

FORBIDDEN_TERMS = (
    "accepted",
    "executed",
    "guaranteed",
    "messaged",
    "offered",
    "sent",
    "submitted",
    "will overpay",
)

DAILY_GM_BRIEF_HEADERS = ("## Target Theses", "## Sell Windows", "## Manager Angles")

# FORBIDDEN_TERMS' bare-word substring scan produced real false positives in production on both
# entity cards and the narrative brief ("sent", "offered", "accepted" are common English words
# that show up constantly with no transactional meaning -- "his role sent his value climbing").
# Every validator that scans LLM prose for banned language uses these phrase-proximity patterns
# instead: a transaction verb only trips the check when it appears near trade/offer/deal
# vocabulary, which is the actual risk (claiming a real transaction happened). Genuinely
# unambiguous risk words ("guaranteed", "will overpay") stay banned outright.
FORBIDDEN_LANGUAGE_PATTERNS = (
    re.compile(r"\b(trade|offer|deal)\w*\b(?:\W+\w+){0,4}?\W+\b(sent|offered|accepted|submitted|executed|messaged)\b", re.IGNORECASE),
    re.compile(r"\b(sent|offered|accepted|submitted|executed|messaged)\b(?:\W+\w+){0,4}?\W+\b(trade|offer|deal)\w*\b", re.IGNORECASE),
    re.compile(r"\bguaranteed\b", re.IGNORECASE),
    re.compile(r"\bwill overpay\b", re.IGNORECASE),
)

# These are deliberately narrow claim-boundary checks, not a second language
# model. The deterministic layer already owns availability and projection
# facts; this seam prevents a writer from laundering a conditional historical
# baseline into a current forecast just because the prose sounds confident.
_PROJECTION_LANGUAGE = re.compile(
    r"\b(?:project(?:ed|ion|s)?|ppg|points per game|expected points|rest[- ]of[- ]season|next[- ]game)\b",
    re.IGNORECASE,
)
_CONDITIONAL_AVAILABILITY_LANGUAGE = re.compile(
    r"\b(?:conditional|if\s+(?:he|the player|they)\s+(?:is\s+)?signed|if\s+active|if\s+he\s+returns|assuming\s+(?:he\s+)?(?:is\s+)?signed|subject\s+to\s+(?:a\s+)?signing)\b",
    re.IGNORECASE,
)
_EXPLICIT_UNAVAILABLE_LANGUAGE = re.compile(
    r"\b(?:unavailable|not available|cannot\s+(?:be\s+)?project(?:ed)?|no usable projection|not a forecast)\b",
    re.IGNORECASE,
)
_RECOVERY_CAVEAT_LANGUAGE = re.compile(
    r"\b(?:not\s+recovery[- ]adjusted|does not model\s+(?:a\s+)?recovery|availability|injur(?:y|ies)|questionable|out|return timeline|conditional)\b",
    re.IGNORECASE,
)

_SHARED_SAFETY_RULES = (
    "Forbidden language (do not use these words or their forms, in any tense, anywhere in your output): "
    "accepted, executed, guaranteed, messaged, offered, sent, submitted, will overpay. "
    "Never claim a trade, waiver, or roster move was proposed, sent, accepted, or executed -- this app is "
    "read-only and has never contacted another manager or platform on the user's behalf. Never state a "
    "player's future performance as certain. Never invent a fact, name, score, or event that is not present "
    "in the evidence provided to you. If evidence is thin for a section, say so plainly rather than filling "
    "the gap with invented specifics. State manager tendencies as estimated patterns, not proven intent."
)

DAILY_GM_BRIEF_SYSTEM_PROMPT = (
    "You are the daily-brief writer for The Front Office, a dynasty fantasy football command surface for a "
    "single team manager. Your job is to turn the evidence packet into a short, sharp, entertaining morning "
    "briefing that still respects the facts. Voice: dry, confident, a little smug about being right, like a "
    "front-office analyst who has seen this exact roster-building mistake before and is trying not to smile "
    "about it. The app's own tagline is \"Find the market leak, then pretend it was obvious all along\" -- "
    "match that register: witty asides are welcome, but every claim must still trace back to the evidence.\n\n"
    "Write flowing narrative prose in markdown, organized under exactly these three headers, in this order: "
    "\"## Target Theses\", \"## Sell Windows\", \"## Manager Angles\". Under each header, write 2-4 sentences "
    "of connected prose synthesizing the evidence for that section -- not a bare bullet restatement of the "
    "input, and not one bullet per evidence row. Reference specific players, teams, or managers by name from "
    "the evidence. Keep the whole brief under 400 words total. Do not add extra headers, a title, or a "
    "sign-off.\n\n"
    f"{_SHARED_SAFETY_RULES}\n\n"
    "Every sentence containing a specific factual claim (a player's status, a manager's tendency, a market "
    "signal) must be traceable to at least one evidence_id you cite in cited_evidence_ids. Each item in the "
    "evidence array below has its own \"evidence_id\" field, e.g. \"player:4984:12\" or \"manager:6:3\" -- "
    "these exact values are what you must put in cited_evidence_ids. Copy each ID character-for-character "
    "from the \"evidence_id\" field of an item you actually used. Never construct, reformat, or guess an ID "
    "yourself, even if you know a player's or manager's real numeric ID -- only ever use the literal string "
    "found in that item's evidence_id field."
)

DAILY_GM_BRIEF_TOOL = {
    "name": "emit_daily_gm_brief",
    "description": "Emit the narrative Daily GM Brief as markdown prose with evidence citations.",
    "input_schema": {
        "type": "object",
        "properties": {
            "narrative_markdown": {
                "type": "string",
                "description": (
                    "The full brief as markdown, with '## Target Theses', '## Sell Windows', and "
                    "'## Manager Angles' headers in that order."
                ),
            },
            "cited_evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Every evidence_id referenced by a factual claim in narrative_markdown.",
            },
        },
        "required": ["narrative_markdown", "cited_evidence_ids"],
    },
}

_LOCK = threading.Lock()
_ACTIVE_JOB = False


@contextmanager
def operator_scope(paths: LeaguePaths | None):
    """Temporarily point legacy operator globals at one private workspace.

    The operator module predates multi-user workspaces and intentionally keeps
    its internal helpers simple.  Jobs are serialized by _LOCK, so a scoped
    adapter lets the existing validation code keep its behavior while making
    every receipt, packet, and article land under the selected league.
    """

    if paths is None:
        yield
        return

    paths.ensure()
    replacements = {
        "ANALYSIS_DIR": paths.analysis_dir,
        "OPERATOR_INBOX_DIR": paths.operator_inbox_dir,
        "OPERATOR_OUTBOX_DIR": paths.operator_outbox_dir,
        "OPERATOR_STATUS_DIR": paths.operator_status_dir,
        "PROCESSED_DIR": paths.processed_dir,
        "SITE_DIR": paths.site_dir,
        "STATUS_PATH": paths.operator_status_dir / "operator_status.json",
        "INSIGHT_PACKET_PATH": paths.operator_inbox_dir / "front_office_insight_packet.json",
        "INSIGHT_OUTPUT_PATH": paths.operator_outbox_dir / "front_office_insight_cards.json",
        "VALIDATED_INSIGHTS_PATH": paths.analysis_dir / "validated_insight_cards.json",
        "INSIGHT_VALIDATION_PATH": paths.analysis_dir / "insight_card_validation.json",
        "DAILY_GM_BRIEF_PATH": paths.analysis_dir / "daily_gm_brief.md",
        "DAILY_GM_BRIEF_VALIDATION_PATH": paths.analysis_dir / "daily_gm_brief_validation.json",
    }
    saved = {name: globals()[name] for name in replacements}
    saved_article_processed_dir = articles.PROCESSED_DIR
    try:
        globals().update(replacements)
        articles.PROCESSED_DIR = paths.processed_dir
        yield
    finally:
        globals().update(saved)
        articles.PROCESSED_DIR = saved_article_processed_dir


def operator_enabled() -> bool:
    return bool(os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN"))


def token_valid(headers: dict[str, str]) -> bool:
    expected = os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN", "")
    if not expected:
        return False
    supplied = headers.get("x-front-office-token") or headers.get("authorization", "").replace("Bearer ", "")
    return supplied == expected


def status(paths: LeaguePaths | None = None) -> dict[str, Any]:
    if paths is not None:
        status_path = paths.operator_status_dir / "operator_status.json"
        if status_path.exists():
            try:
                payload = load_json(status_path)
                if isinstance(payload, dict):
                    return _reconcile_interrupted_status(status_path, payload)
            except (OSError, json.JSONDecodeError):
                pass
        return _base_status("idle", "Operator loop is ready.", paths=paths)
    OPERATOR_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    if STATUS_PATH.exists():
        try:
            payload = load_json(STATUS_PATH)
            if isinstance(payload, dict):
                return _reconcile_interrupted_status(STATUS_PATH, payload)
        except (OSError, json.JSONDecodeError):
            pass
    return _base_status("idle", "Operator loop is ready.")


def start_job(
    name: str,
    job: Callable[[], dict[str, Any]],
    paths: LeaguePaths | None = None,
) -> dict[str, Any]:
    global _ACTIVE_JOB
    with _LOCK:
        with operator_scope(paths):
            current = status()
            if _ACTIVE_JOB or current.get("state") == "running":
                return current | {"accepted": False, "message": "Another operator job is already running."}
            _write_status(_base_status("running", f"{name} started.", job=name))
            _ACTIVE_JOB = True
    thread = threading.Thread(target=_run_job, args=(name, job, paths), daemon=True)
    thread.start()
    return status(paths) | {"accepted": True}


def build_insight_packet(paths: LeaguePaths | None = None) -> dict[str, Any]:
    if paths is not None:
        with operator_scope(paths):
            return build_insight_packet()
    generated_at = _now()
    packet = {
        "packet_type": "front_office_insight_packet",
        "generated_at": generated_at,
        "instructions": {
            "role": "Turn deterministic fantasy football evidence into concise manager and player card insights.",
            "allowed": [
                "Summarize evidence in plain English.",
                "State tendencies as estimates, not facts.",
                "Explain why a tag matters for a decision.",
                "Use conservative confidence language.",
            ],
            "forbidden": [
                "Do not claim a trade was sent, offered, accepted, submitted, or executed.",
                "Do not claim manager intent as fact.",
                "Do not guarantee player outcomes.",
                "Do not invent facts outside the packet.",
            ],
            "output_file": str(INSIGHT_OUTPUT_PATH.as_posix()),
        },
        "required_output_schema": {
            "items": [
                {
                    "card_id": "string",
                    "entity_type": "manager|player",
                    "entity_id": "string",
                    "headline": "string",
                    "one_line_read": "string",
                    "why_it_matters": "string",
                    "watchouts": "string",
                    "confidence": "low|medium|high",
                    "cited_evidence_ids": ["string"],
                }
            ]
        },
        "evidence": _evidence_items(generated_at),
    }
    _write_json(INSIGHT_PACKET_PATH, packet)
    return {
        "state": "complete",
        "message": "Insight packet generated.",
        "packet_path": str(INSIGHT_PACKET_PATH.as_posix()),
        "evidence_count": len(packet["evidence"]),
        "generated_at": generated_at,
    }


def validate_insight_output(paths: LeaguePaths | None = None) -> dict[str, Any]:
    if paths is not None:
        with operator_scope(paths):
            return validate_insight_output()
    generated_at = _now()
    packet = _safe_json(INSIGHT_PACKET_PATH)
    output = _safe_json(INSIGHT_OUTPUT_PATH)
    evidence_ids = {str(item.get("evidence_id")) for item in packet.get("evidence", []) if item.get("evidence_id")}
    items = output.get("items", []) if isinstance(output, dict) else []
    errors: list[str] = []
    valid_items: list[dict[str, Any]] = []

    if not evidence_ids:
        errors.append("No insight packet evidence found. Build a packet before validating output.")
    if not isinstance(items, list) or not items:
        errors.append("Insight output must contain a non-empty items list.")

    for index, item in enumerate(items if isinstance(items, list) else [], start=1):
        card_id = str(item.get("card_id") or f"item-{index}")
        text = " ".join(str(item.get(field, "")) for field in ("headline", "one_line_read", "why_it_matters", "watchouts")).lower()
        missing = [
            field
            for field in ("entity_type", "entity_id", "headline", "one_line_read", "why_it_matters", "confidence", "cited_evidence_ids")
            if item.get(field) in ("", None, [])
        ]
        if missing:
            errors.append(f"{card_id} missing {','.join(missing)}")
        banned = [match.group(0) for pattern in FORBIDDEN_LANGUAGE_PATTERNS for match in pattern.finditer(text)]
        if banned:
            errors.append(f"{card_id} contains forbidden language: {','.join(banned)}")
        cited = {str(value) for value in item.get("cited_evidence_ids", [])}
        if not cited:
            errors.append(f"{card_id} has no cited evidence IDs")
        elif not cited.issubset(evidence_ids):
            errors.append(f"{card_id} cites unknown evidence IDs: {','.join(sorted(cited - evidence_ids))}")
        valid_items.append(item | {"card_id": card_id, "validated_at": generated_at})

    validation = {
        "artifact_type": "insight_card_validation",
        "generated_at": generated_at,
        "valid": not errors,
        "errors": errors,
        "item_count": len(valid_items),
    }
    _write_json(INSIGHT_VALIDATION_PATH, validation)
    if not errors:
        _write_json(
            VALIDATED_INSIGHTS_PATH,
            {
                "artifact_type": "validated_insight_cards",
                "generated_at": generated_at,
                "generation_mode": output.get("generation_mode", "operator_packet_loop") if isinstance(output, dict) else "operator_packet_loop",
                "items": valid_items,
            },
        )
    return validation


def import_insight_output(payload: dict[str, Any], paths: LeaguePaths | None = None) -> dict[str, Any]:
    if paths is not None:
        with operator_scope(paths):
            return import_insight_output(payload)
    if not isinstance(payload, dict):
        return {"state": "failed", "message": "Insight output must be a JSON object."}
    _write_json(INSIGHT_OUTPUT_PATH, payload)
    validation = validate_insight_output()
    return {
        "state": "complete" if validation.get("valid") else "failed",
        "message": "Insight output imported and validated." if validation.get("valid") else "Insight output imported but validation failed.",
        "output_path": str(INSIGHT_OUTPUT_PATH.as_posix()),
        "validation": validation,
    }


def generate_insight_output_via_llm(packet: dict[str, Any], api_key: str, model: str) -> dict[str, Any]:
    """Force a structured insight tool call through the configured provider."""
    instructions = packet.get("instructions", {})
    system_prompt = (
        f"{instructions.get('role', '')}\n\n"
        "Allowed:\n" + "\n".join(f"- {item}" for item in instructions.get("allowed", [])) + "\n\n"
        "Forbidden:\n" + "\n".join(f"- {item}" for item in instructions.get("forbidden", [])) + "\n\n"
        "Only use the evidence provided below. Every evidence item has its own \"evidence_id\" "
        "field, e.g. \"player:4984:12\" or \"manager:6:3\" -- copy that exact string "
        "character-for-character into cited_evidence_ids for the item(s) a card is based on. "
        "Never construct, reformat, or guess an ID yourself, even if you know a player's or "
        "manager's real numeric ID -- only use the literal evidence_id string given to you. "
        "Do not force a card for every evidence item -- prioritize roughly 10-20 of the most "
        "decision-relevant managers/players. Call emit_insight_cards exactly once with your "
        "complete set of cards."
    )
    tool = {
        "name": "emit_insight_cards",
        "description": "Emit validated fantasy football insight cards grounded in the provided evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "card_id": {"type": "string"},
                            "entity_type": {"type": "string", "enum": ["manager", "player"]},
                            "entity_id": {"type": "string"},
                            "headline": {"type": "string"},
                            "one_line_read": {"type": "string"},
                            "why_it_matters": {"type": "string"},
                            "watchouts": {"type": "string"},
                            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                            "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["card_id", "entity_type", "entity_id", "headline", "one_line_read", "why_it_matters", "confidence", "cited_evidence_ids"],
                    },
                }
            },
            "required": ["items"],
        },
    }
    return call_structured_tool(
        system_prompt=system_prompt,
        evidence=packet.get("evidence", []),
        api_key=api_key,
        model=model,
        tool=tool,
        request_post=requests.post,
    )


def generate_daily_gm_brief_via_llm(
    packet: dict[str, Any],
    api_key: str,
    model: str,
    writer_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sibling to generate_insight_output_via_llm() for a different output shape: one narrative
    blob instead of a list of entity cards, so it gets its own persona-carrying system prompt and
    its own forced tool rather than overloading the entity-card schema."""
    return call_structured_tool(
        system_prompt=f"{DAILY_GM_BRIEF_SYSTEM_PROMPT}\n\n{persona_prompt_block(writer_preferences, 'daily_brief')}\n\n{_SHARED_SAFETY_RULES}",
        evidence=packet.get("evidence", []),
        api_key=api_key,
        model=model,
        tool=DAILY_GM_BRIEF_TOOL,
        request_post=requests.post,
    )


def validate_daily_gm_brief_output(output: dict[str, Any]) -> dict[str, Any]:
    """Sibling to validate_insight_output() for one narrative blob instead of a card list, plus
    a structural check unique to a narrative (the three required section headers must be
    present). Citation checking is deliberately looser here than validate_insight_output()'s
    full-subset requirement: a single-entity card only ever needs to cite its own one evidence_id,
    but a narrative synthesizes dozens of evidence items across four sections, and in practice the
    model sometimes drops or misformats one citation among several correct ones. Only reject if
    NONE of the cited IDs are real -- that's the actual signal the model isn't grounded in the
    evidence at all, not a single dropped citation."""
    generated_at = _now()
    packet = _safe_json(INSIGHT_PACKET_PATH)
    evidence_ids = {str(item.get("evidence_id")) for item in packet.get("evidence", []) if item.get("evidence_id")}
    narrative = str(output.get("narrative_markdown", "")) if isinstance(output, dict) else ""
    cited = {str(value) for value in output.get("cited_evidence_ids", [])} if isinstance(output, dict) else set()
    valid_citations = cited & evidence_ids
    unknown_citations = cited - evidence_ids
    errors: list[str] = []
    warnings: list[str] = []

    if not evidence_ids:
        errors.append("No insight packet evidence found. Build a packet before validating output.")
    if not narrative.strip():
        errors.append("Daily GM Brief narrative_markdown is empty.")
    missing_headers = [header for header in DAILY_GM_BRIEF_HEADERS if header not in narrative]
    if missing_headers:
        errors.append(f"Narrative is missing required section headers: {','.join(missing_headers)}")
    banned_matches = [match.group(0) for pattern in FORBIDDEN_LANGUAGE_PATTERNS for match in pattern.finditer(narrative)]
    if banned_matches:
        errors.append(f"Narrative contains forbidden language: {','.join(banned_matches)}")
    if not cited:
        errors.append("Narrative has no cited evidence IDs")
    elif not valid_citations:
        errors.append(f"Narrative cites unknown evidence IDs: {','.join(sorted(unknown_citations))}")
    elif unknown_citations:
        warnings.append(f"Narrative cited some unknown evidence IDs (kept, at least one real citation exists): {','.join(sorted(unknown_citations))}")

    validation = {
        "artifact_type": "daily_gm_brief_validation",
        "generated_at": generated_at,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "word_count": len(narrative.split()),
    }
    _write_json(DAILY_GM_BRIEF_VALIDATION_PATH, validation)
    if not errors:
        DAILY_GM_BRIEF_PATH.write_text(_render_daily_gm_brief_markdown(narrative, generated_at), encoding="utf-8")
    return validation


def _render_daily_gm_brief_markdown(narrative: str, generated_at: str) -> str:
    existing = DAILY_GM_BRIEF_PATH.read_text(encoding="utf-8") if DAILY_GM_BRIEF_PATH.exists() else ""
    roster_id = _front_matter_value(existing, "roster_id")
    team_name = _front_matter_value(existing, "team_name") or "Unknown Team"
    front_matter = "\n".join(
        [
            "---",
            "artifact_type: daily_gm_brief",
            f"generated_at: {generated_at}",
            f"roster_id: {roster_id}",
            f"team_name: {team_name}",
            "model_mode: automatic_llm",
            "---",
        ]
    )
    return f"{front_matter}\n\n# Daily GM Brief: {team_name}\n\n{narrative.strip()}\n"


def _front_matter_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def generate_insights_automatically(paths: LeaguePaths | None = None) -> dict[str, Any]:
    """Explicit, user-triggered, cost-incurring action -- fails loud on any problem
    rather than degrading silently like the free read-only source fetches do. Runs both
    the entity-card pipeline and the narrative-brief pipeline in one action; each is
    independently wrapped so one failing never hides or blocks the other's result."""
    if paths is not None:
        with operator_scope(paths):
            return generate_insights_automatically()
    generated_at = _now()
    llm = configured_llm()
    api_key = os.environ.get(llm.api_key_env, "")
    if not api_key:
        return {
            "state": "failed",
            "message": f"{llm.api_key_env} is not set. No LLM call was attempted.",
            "generated_at": generated_at,
            "insight_cards": {"state": "skipped"},
            "daily_gm_brief": {"state": "skipped"},
        }
    model = llm.model

    build_insight_packet()
    packet = _safe_json(INSIGHT_PACKET_PATH)
    if not packet.get("evidence"):
        return {
            "state": "failed",
            "message": "No evidence available to generate insights from. Refresh data first.",
            "generated_at": generated_at,
            "insight_cards": {"state": "skipped"},
            "daily_gm_brief": {"state": "skipped"},
        }

    results: dict[str, Any] = {"generated_at": generated_at}

    try:
        card_output = generate_insight_output_via_llm(packet, api_key, model)
        card_output = dict(card_output) | {
            "generation_mode": "automatic_llm",
            "model": model,
            "provider": llm.provider,
            "reasoning_effort": llm.reasoning_effort,
        }
        import_result = import_insight_output(card_output)
        results["insight_cards"] = {
            "state": import_result["state"],
            "message": import_result["message"],
            "validation": import_result["validation"],
        }
    except Exception as exc:
        results["insight_cards"] = {"state": "failed", "message": f"Insight card generation failed: {exc}"}

    try:
        brief_output = generate_daily_gm_brief_via_llm(packet, api_key, model)
        brief_validation = validate_daily_gm_brief_output(brief_output)
        results["daily_gm_brief"] = {
            "state": "complete" if brief_validation["valid"] else "failed",
            "message": "Daily GM Brief written." if brief_validation["valid"] else "Daily GM Brief generation failed validation.",
            "validation": brief_validation,
        }
    except Exception as exc:
        results["daily_gm_brief"] = {"state": "failed", "message": f"Daily GM Brief generation failed: {exc}"}

    both_ok = results["insight_cards"]["state"] == "complete" and results["daily_gm_brief"]["state"] == "complete"
    any_ok = results["insight_cards"]["state"] == "complete" or results["daily_gm_brief"]["state"] == "complete"
    results["state"] = "complete" if both_ok else ("partial" if any_ok else "failed")
    results["message"] = (
        "Both insight cards and Daily GM Brief generated."
        if both_ok
        else (
            f"Partial success: insight_cards={results['insight_cards']['state']}, "
            f"daily_gm_brief={results['daily_gm_brief']['state']}."
            if any_ok
            else "Both insight card and Daily GM Brief generation failed."
        )
    )
    return results


# === Sprint 17: per-section article workflow ==============================================
# One focused LLM call per meaningful section instead of one mega-call that writes all the copy.
# Each article gets its own editable prompt (prompts/{key}.md) + only its own scoped evidence,
# is validated independently, and falls back to its deterministic .md on failure. This
# generalizes the Sprint 16 single-brief pipeline (which stays intact for its own tests).

ARTICLE_TOOL = {
    "name": "emit_article",
    "description": "Emit one structured section article and its markdown prose grounded in the provided evidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "A clear publication headline."},
            "dek": {"type": "string", "description": "One-sentence setup that explains why the reader should care."},
            "lede": {"type": "string", "description": "The opening read in one or two sentences."},
            "thesis": {"type": "string", "description": "The core evidence-backed point of view."},
            "what_changed": {"type": "string", "description": "What changed in the selected league snapshot."},
            "counter_evidence": {"type": "string", "description": "The strongest caveat, counter-signal, or missing evidence."},
            "action": {"type": "string", "description": "A read-only decision question or next step for the manager."},
            "risk": {"type": "string", "description": "The main risk of acting or waiting."},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"], "description": "Confidence in the interpretation, not certainty about an outcome."},
            "related_entities": {"type": "array", "items": {"type": "string"}, "description": "Evidence-backed player, team, manager, or pick identifiers/names."},
            "visual_brief": {"type": "string", "description": "Optional non-factual art direction; never put stats or claims in an image."},
            "narrative_markdown": {
                "type": "string",
                "description": "The full article as markdown prose under the requested section headers.",
            },
            "cited_evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Every evidence_id referenced by a factual claim in narrative_markdown.",
            },
        },
        "required": [
            "headline", "dek", "lede", "thesis", "what_changed", "counter_evidence",
            "action", "risk", "confidence", "related_entities", "visual_brief",
            "narrative_markdown", "cited_evidence_ids"
        ],
    },
}


# The editor receives the same canonical evidence packet as the writer, but a
# separate tool contract makes the publication decision explicit. A repaired
# draft must be a complete article, not a free-form note that can bypass the
# existing citation and forbidden-language checks.
EDITOR_TOOL = {
    "name": "review_article",
    "description": "Approve, repair, or hold one evidence-backed section article before publication.",
    "input_schema": deepcopy(ARTICLE_TOOL["input_schema"]),
}
EDITOR_TOOL["input_schema"]["properties"].update(
    {
        "decision": {
            "type": "string",
            "enum": ["approve", "modify", "hold"],
            "description": "Approve a supported draft, modify it to repair supported copy, or hold it when it cannot be made safe.",
        },
        "editor_notes": {
            "type": "string",
            "description": "Short desk note explaining the decision; never introduce a new factual claim.",
        },
        "changes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific copy repairs made or requested by the desk.",
        },
    }
)

EDITOR_TOOL["input_schema"]["required"] = list(EDITOR_TOOL["input_schema"]["properties"])

_CITATION_RULES = (
    "Every sentence containing a specific factual claim must be traceable to at least one evidence_id "
    "you cite in cited_evidence_ids. Each evidence item below has its own \"evidence_id\" field, e.g. "
    "\"player:4984:12\" or \"manager:6:3\" -- copy that exact string character-for-character into "
    "cited_evidence_ids for items you actually used. Never construct, reformat, or guess an ID yourself, "
    "even if you know a real numeric ID; only ever use the literal evidence_id strings given to you."
)


def _article_context_prompt_block(context: FantasyContext | None) -> str:
    if context is None:
        return ""
    strategy = json.dumps(context.strategy_profile or {}, ensure_ascii=False, sort_keys=True)
    manager_profiles = [
        {
            "roster_id": profile.get("roster_id"),
            "manager_name": profile.get("manager_name"),
            "trade_style": profile.get("trade_style"),
            "preferred_assets": profile.get("preferred_assets"),
            "protected_assets": profile.get("protected_assets"),
            "editor_note": profile.get("editor_note"),
        }
        for profile in context.manager_trade_profiles[:24]
        if isinstance(profile, dict)
    ]
    manager_block = ""
    if manager_profiles:
        manager_block = (
            "\nPersonal manager trade profiles (editorial context only; never treat these notes as evidence):\n"
            + json.dumps(manager_profiles, ensure_ascii=False, sort_keys=True)
        )
    return (
        "Edition context (use this only to prioritize the read; it is not evidence):\n"
        f"League: {context.league_name or context.league_id}\n"
        f"Team: {context.team_name or context.display_name or 'Unconfigured team'}\n"
        f"Strategy profile: {strategy}\n"
        "Translate this profile into relevant emphasis and actionable framing, but never invent a fact "
        "or treat profile preferences as proof of a player, manager, or market claim."
        + manager_block
    )


def _article_system_prompt(
    article: articles.Article,
    writer_preferences: dict[str, Any] | None = None,
    context: FantasyContext | None = None,
) -> str:
    context_block = _article_context_prompt_block(context)
    sections = [
        articles.load_prompt(article.prompt_filename),
        persona_prompt_block(writer_preferences, article.key),
    ]
    if context_block:
        sections.append(context_block)
    sections.append(
        "The user payload may include editorial_context. It is non-evidence: use it only to avoid repeating "
        "another desk, surface a supported disagreement, and keep this assigned lens distinct. If it conflicts with "
        "the evidence packet, the evidence packet wins, and do not cite room context as factual support."
    )
    sections.extend((_SHARED_SAFETY_RULES, _CITATION_RULES))
    return "\n\n".join(sections)


def _editorial_room_context(
    ctx: articles.ArticleContext,
    article: articles.Article,
    output_path: Path,
) -> list[dict[str, Any]]:
    """Give each writer bounded newsroom context without polluting evidence.

    The current article body is treated as the previous edition of that desk;
    completed peer articles from this run become room notes. Neither is cited
    as a source. This creates meaningful disagreement while keeping the reuse
    fingerprint dependent only on stable peer context, not on self-referential
    prior prose.
    """

    room: list[dict[str, Any]] = []
    previous = _article_narrative_from_file(output_path)
    if previous:
        reporter = persona_metadata(ctx.writer_preferences, article.key)
        room.append(
            {
                "kind": "previous_edition",
                "desk": article.key,
                "reporter": reporter["name"],
                "excerpt": _editorial_excerpt(previous),
            }
        )
    article_titles = {item.key: item.title for item in articles.ARTICLES}
    for key, narrative in ctx.section_outputs.items():
        if key == article.key or not str(narrative or "").strip():
            continue
        reporter = persona_metadata(ctx.writer_preferences, key)
        room.append(
            {
                "kind": "peer_edition",
                "desk": key,
                "reporter": reporter["name"],
                "title": article_titles.get(key, key),
                "excerpt": _editorial_excerpt(narrative),
            }
        )
    return room[:5]


def _editorial_excerpt(value: Any, limit: int = 900) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _review_evidence_boundaries(
    narrative: str,
    evidence_packets: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Check high-risk availability and horizon wording before publication.

    Writers receive the full deterministic packet and an explicit prompt, but
    prompts are not contracts.  This small seam catches the most damaging
    regression from the old product: a player with no current NFL team being
    described as if a historical PPG number were an active forecast.  The
    injury check is a warning because an article can still be useful when it
    states the limitation elsewhere in the same short paragraph.
    """

    text = str(narrative or "")
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text)
        if part.strip()
    ]
    errors: list[str] = []
    warnings: list[str] = []
    no_team_claims_reviewed = 0
    injury_baseline_warnings = 0

    for packet in evidence_packets or []:
        if not isinstance(packet, dict):
            continue
        player_name = str(packet.get("player_name") or "").strip()
        if not player_name:
            continue
        status = " ".join(
            str(packet.get(field) or "").strip().lower()
            for field in ("current_availability_status", "availability_scope", "availability_note")
        )
        no_current_team = "no_current_nfl_team" in status or "no current nfl team" in status
        injury_flag = bool(str(packet.get("injury_status") or "").strip()) or any(
            marker in status for marker in ("questionable", "out", "injury", "injured")
        )
        name_pattern = re.compile(rf"(?<!\w){re.escape(player_name)}(?!\w)", re.IGNORECASE)
        mentioned_indexes = [index for index, sentence in enumerate(sentences) if name_pattern.search(sentence)]
        if not mentioned_indexes:
            continue

        for index in mentioned_indexes:
            context = " ".join(sentences[max(0, index - 1): min(len(sentences), index + 2)])
            if no_current_team and _PROJECTION_LANGUAGE.search(context):
                no_team_claims_reviewed += 1
                if not (
                    _CONDITIONAL_AVAILABILITY_LANGUAGE.search(context)
                    or _EXPLICIT_UNAVAILABLE_LANGUAGE.search(context)
                ):
                    errors.append(
                        f"{player_name} is unavailable with no current NFL team; projection/PPG language must be conditional or explicitly unavailable."
                    )
                    break
            if injury_flag and re.search(r"\brest[- ]of[- ]season\b", context, re.IGNORECASE) and _PROJECTION_LANGUAGE.search(context):
                if not _RECOVERY_CAVEAT_LANGUAGE.search(context):
                    injury_baseline_warnings += 1
                    warnings.append(
                        f"{player_name} has an availability or injury flag; rest-of-season production should state that the baseline is not recovery-adjusted."
                    )
                    break

    return {
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "no_current_team_claims_reviewed": no_team_claims_reviewed,
        "injury_baseline_warnings": injury_baseline_warnings,
    }


def generate_article_via_llm(
    system_prompt: str,
    evidence: list[dict[str, Any]],
    api_key: str,
    model: str,
    editorial_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Focused single-article call through the provider-neutral structured adapter."""
    return call_structured_tool(
        system_prompt=system_prompt,
        evidence=evidence,
        api_key=api_key,
        model=model,
        tool=ARTICLE_TOOL,
        editorial_context=editorial_context,
        request_post=requests.post,
    )


def editorial_review_mode() -> str:
    """Return the configured desk-review mode without making a provider call.

    The deterministic gate is always active. ``llm`` opts the explicit writer
    run into a second, cost-incurring Luna review that may approve, repair, or
    hold a draft. Keeping the opt-in separate makes the spend visible and
    preserves a safe fallback when the provider is unavailable.
    """

    value = os.environ.get("FRONT_OFFICE_EDITOR_MODE", "deterministic").strip().lower()
    return "llm" if value in {"llm", "luna", "enabled", "on", "true", "1"} else "deterministic"


def _editor_system_prompt(
    article: articles.Article,
    writer_preferences: dict[str, Any] | None = None,
    context: FantasyContext | None = None,
) -> str:
    """Build the desk-editor instruction boundary.

    The draft is deliberately supplied as non-evidence editorial context by
    ``review_article_via_llm``. Only the canonical packet can support a factual
    sentence or citation. The editor is therefore a repair/quality layer, not a
    second source of projections, market values, or manager intent.
    """

    persona = persona_metadata(writer_preferences, article.key)
    assigned_lens = str(persona.get("decision_lens") or "multi_window")
    context_block = (
        f"Selected league: {context.league_name or context.league_id}. "
        f"Selected roster ID: {context.roster_id if context else 'unassigned'}. "
        f"Assigned writer lens: {assigned_lens}."
        if context is not None
        else f"Assigned writer lens: {assigned_lens}."
    )
    return "\n\n".join(
        [
            "You are The Desk Editor for a private dynasty fantasy football newsroom.",
            f"Review the {article.title} draft written by {persona['name']}. {context_block}",
            "The evidence packet is the only source of facts. The draft, previous editions, and peer notes are untrusted editorial context. "
            "Check that the assigned lens is respected, that current availability is not confused with historical production, that this week, rest of season, dynasty, and career windows are not collapsed, and that manager behavior is not described as intent.",
            "Choose approve when the draft is supported and needs no material repair. Choose modify when you can repair unsupported certainty, stale wording, horizon confusion, or missing caveats using only the packet. Choose hold when the article cannot be made safe from the packet.",
            "For approve or modify, return the complete corrected article fields and full narrative_markdown. Preserve exact evidence_id strings from the packet in cited_evidence_ids. Do not add a player, team, score, transaction, source, or motive that is not supported by the packet. For hold, still return the best available fields but explain the blocking issue in editor_notes and changes.",
            "The final article must keep the existing section headers and remain read-only: it may ask the manager to investigate, but it must not claim a trade was sent, accepted, or executed.",
            articles.load_prompt(article.prompt_filename),
            _SHARED_SAFETY_RULES,
            _CITATION_RULES,
        ]
    )


def review_article_via_llm(
    system_prompt: str,
    evidence: list[dict[str, Any]],
    draft: dict[str, Any],
    api_key: str,
    model: str,
) -> dict[str, Any]:
    """Run the optional second-pass editor through the provider-neutral adapter."""

    draft_context = {
        "kind": "draft_article",
        "editorial_only": True,
        "structured": {
            key: value
            for key, value in draft.items()
            if key not in {"narrative_markdown", "cited_evidence_ids", "_provider_receipt"}
        },
        "narrative_markdown": _editorial_excerpt(draft.get("narrative_markdown"), limit=7000),
        "cited_evidence_ids": [str(value) for value in (draft.get("cited_evidence_ids") or [])],
    }
    return call_structured_tool(
        system_prompt=system_prompt,
        evidence=evidence,
        api_key=api_key,
        model=model,
        tool=EDITOR_TOOL,
        editorial_context=[draft_context],
        request_post=requests.post,
    )


def _editor_review_result(
    article: articles.Article,
    writer_output: dict[str, Any],
    writer_validation: dict[str, Any],
    editor_output: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
    model: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a desk decision and return the publishable candidate plus receipt."""

    from .editorial import review_publication_article

    evidence_ids = {str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")}
    writer_candidate = dict(writer_output or {})
    writer_candidate.setdefault("narrative_markdown", writer_validation.get("narrative", ""))
    writer_candidate.setdefault("cited_evidence_ids", writer_validation.get("evidence_ids", []))

    if not isinstance(editor_output, dict):
        review = review_publication_article(
            article.key,
            writer_validation.get("narrative", ""),
            {
                "structured": writer_validation.get("structured") or {},
            },
            "automatic_llm",
        )
        return writer_candidate, {
            **review,
            "mode": "llm",
            "decision": "hold",
            "status": "held",
            "model": model,
            "errors": ["The editor did not return a structured review."],
            "note": "Held from publication because the editor response was incomplete.",
        }

    decision = str(editor_output.get("decision") or "hold").strip().lower()
    editor_validation = validate_article_output(
        editor_output,
        evidence_ids,
        article.headers,
        evidence,
    )
    candidate = dict(editor_output) if decision in {"approve", "modify"} else writer_candidate
    candidate_validation = editor_validation if decision in {"approve", "modify"} else writer_validation
    gate_structured = dict(candidate_validation.get("structured") or {})
    gate_structured["evidence_ids"] = candidate_validation.get("evidence_ids") or []
    gate_structured["source_ids"] = candidate_validation.get("source_ids") or []
    gate_receipt = {"structured": gate_structured}
    deterministic_gate = review_publication_article(
        article.key,
        candidate_validation.get("narrative", ""),
        gate_receipt,
        "automatic_llm",
    )
    errors = list(editor_validation.get("errors") or [])
    errors.extend(deterministic_gate.get("errors") or [])
    if decision not in {"approve", "modify", "hold"}:
        errors.append(f"unknown editor decision {decision!r}")
    if decision == "hold":
        errors.append("editor chose to hold the draft")
    status = "approved" if not errors else "held"
    if status == "held":
        candidate = writer_candidate
        candidate_validation = writer_validation
    writer_narrative = str(writer_validation.get("narrative") or "")
    editor_narrative = str(editor_validation.get("narrative") or "")
    actually_modified = bool(editor_narrative and editor_narrative.strip() != writer_narrative.strip())
    effective_decision = "modify" if status == "approved" and actually_modified else "approve" if status == "approved" else "hold"
    return candidate, {
        "editor": "The Desk Editor",
        "article_key": article.key,
        "mode": "llm",
        "model": model,
        "status": status,
        "decision": effective_decision,
        "requested_decision": decision,
        "changes": [str(value) for value in (editor_output.get("changes") or []) if str(value).strip()],
        "editor_notes": str(editor_output.get("editor_notes") or "").strip(),
        "checks": deterministic_gate.get("checks") or {},
        "errors": list(dict.fromkeys(errors)),
        "note": (
            "Approved after desk review; the editor repaired the draft using the supplied evidence."
            if effective_decision == "modify"
            else "Approved after desk review and deterministic evidence checks."
            if status == "approved"
            else "Held from the printed facade until the desk review concerns are repaired."
        ),
        "writer_validation": {
            "word_count": writer_validation.get("word_count", 0),
            "evidence_ids": writer_validation.get("evidence_ids") or [],
        },
        "editor_validation": {
            "word_count": editor_validation.get("word_count", 0),
            "evidence_ids": editor_validation.get("evidence_ids") or [],
            "warnings": editor_validation.get("warnings") or [],
        },
        "provider_receipt": editor_output.get("_provider_receipt") or {},
    }


def validate_article_output(
    output: dict[str, Any],
    evidence_ids: set[str],
    headers: tuple[str, ...],
    evidence_packets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Independent per-article validation: required headers (if any), the shared phrase-proximity
    forbidden-language scan, and lenient citation (reject only if NONE of the cited IDs are real,
    since a synthesized article can plausibly drop one citation among several correct ones)."""
    narrative = str(output.get("narrative_markdown", "")) if isinstance(output, dict) else ""
    structured = _structured_article_payload(output, headers)
    cited = {str(value) for value in output.get("cited_evidence_ids", [])} if isinstance(output, dict) else set()
    valid_citations = cited & evidence_ids
    unknown_citations = cited - evidence_ids
    errors: list[str] = []
    warnings: list[str] = []

    if not narrative.strip():
        errors.append("Article narrative_markdown is empty.")
    raw_confidence = str(output.get("confidence") or "").lower() if isinstance(output, dict) else ""
    if raw_confidence and raw_confidence not in {"low", "medium", "high"}:
        errors.append(f"Article confidence must be low, medium, or high: {raw_confidence}")
    missing_headers = [header for header in headers if header not in narrative]
    if missing_headers:
        errors.append(f"Article is missing required section headers: {','.join(missing_headers)}")
    banned_matches = [match.group(0) for pattern in FORBIDDEN_LANGUAGE_PATTERNS for match in pattern.finditer(narrative)]
    if banned_matches:
        errors.append(f"Article contains forbidden language: {','.join(banned_matches)}")
    if not cited:
        errors.append("Article has no cited evidence IDs.")
    elif not valid_citations:
        errors.append(f"Article cites only unknown evidence IDs: {','.join(sorted(unknown_citations))}")
    elif unknown_citations:
        warnings.append(f"Article cited some unknown evidence IDs (kept): {','.join(sorted(unknown_citations))}")

    boundary_checks = _review_evidence_boundaries(narrative, evidence_packets)
    errors.extend(boundary_checks["errors"])
    warnings.extend(boundary_checks["warnings"])

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "boundary_checks": boundary_checks,
        "narrative": narrative,
        "structured": structured,
        "evidence_ids": sorted(valid_citations),
        "source_ids": sorted({
            str(source_id)
            for packet in (evidence_packets or [])
            for source_id in (packet.get("source_ids") or [])
            if str(source_id).strip()
        }),
        "word_count": len(narrative.split()),
    }


def _structured_article_payload(output: dict[str, Any] | None, headers: tuple[str, ...]) -> dict[str, Any]:
    """Normalize the durable article contract while keeping old mock/fallback output valid."""

    output = output if isinstance(output, dict) else {}
    return {
        "headline": str(output.get("headline") or (headers[0].lstrip("# ") if headers else "Desk report")),
        "dek": str(output.get("dek") or "Evidence-backed read; open the receipt before acting."),
        "lede": str(output.get("lede") or ""),
        "thesis": str(output.get("thesis") or ""),
        "what_changed": str(output.get("what_changed") or ""),
        "counter_evidence": str(output.get("counter_evidence") or "Evidence is limited to the supplied packet."),
        "action": str(output.get("action") or "Open the evidence and make the final decision yourself."),
        "risk": str(output.get("risk") or "Review what could make this read wrong."),
        "confidence": str(output.get("confidence") or "medium").lower(),
        "related_entities": [str(item) for item in (output.get("related_entities") or []) if str(item).strip()],
        "visual_brief": str(output.get("visual_brief") or ""),
        "evidence_ids": [str(item) for item in (output.get("cited_evidence_ids") or []) if str(item).strip()],
    }


def _render_article_markdown(
    article: articles.Article,
    narrative: str,
    generated_at: str,
    output_path: Path,
    writer_preferences: dict[str, Any] | None = None,
    article_key: str | None = None,
    evidence_fingerprint: str = "",
    model: str = "",
    structured: dict[str, Any] | None = None,
    source_receipt: dict[str, Any] | None = None,
    editorial_review: dict[str, Any] | None = None,
) -> str:
    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    front_lines = [
        "---",
        f"artifact_type: {article.key}",
        f"generated_at: {generated_at}",
        "model_mode: automatic_llm",
        f"model: {model}",
        f"evidence_fingerprint: {evidence_fingerprint}",
        f"reporter_persona: {persona_metadata(writer_preferences, article_key)['persona_id']}",
        f"reporter_name: {persona_metadata(writer_preferences, article_key)['name']}",
        "article_payload_json: " + json.dumps(structured or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "source_receipt_json: " + json.dumps(source_receipt or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ]
    if editorial_review:
        front_lines.append(
            "editorial_review_json: "
            + json.dumps(editorial_review, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    for key in ("roster_id", "team_name"):
        value = _front_matter_value(existing, key)
        if value:
            front_lines.append(f"{key}: {value}")
    front_lines.append("---")
    headline = str((structured or {}).get("headline") or article.title)
    return "\n".join(front_lines) + f"\n\n# {headline}\n\n{narrative.strip()}\n"


def generate_articles_workflow(
    paths: LeaguePaths | None = None,
    context: FantasyContext | None = None,
    article_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Explicit, user-triggered, cost-incurring action. Generates one article per meaningful
    section (each independently validated, each falling back to its deterministic .md on failure),
    then a daily brief that synthesizes across them. Fails loud only on missing API key."""
    if paths is not None:
        with operator_scope(paths):
            return generate_articles_workflow(context=context, article_keys=article_keys)
    generated_at = _now()
    llm = configured_llm()
    api_key = os.environ.get(llm.api_key_env, "")
    if not api_key:
        return {
            "state": "failed",
            "message": f"{llm.api_key_env} is not set. No LLM call was attempted.",
            "generated_at": generated_at,
            "articles": {},
        }
    model = llm.model
    editor_mode = editorial_review_mode()

    ctx = articles.ArticleContext(
        analysis_dir=ANALYSIS_DIR,
        active_roster_id=(
            context.roster_id
            if context is not None
            else articles.resolve_active_roster_id()
        ),
        processed_dir=PROCESSED_DIR,
        user_id=context.user_id if context else None,
        league_id=context.league_id if context else "",
        season=context.season if context else "",
        team_name=context.team_name if context else "",
        writer_preferences=context.writer_preferences if context else {},
    )
    results: dict[str, Any] = {}
    article_queue = [
        article
        for article in sorted(articles.ARTICLES, key=lambda item: item.is_summary)
        if article_keys is None or article.key in article_keys
    ]
    if article_keys is not None:
        # A targeted retry still needs existing section prose available if a
        # selected summary follows an unselected desk in the same run.
        for article in sorted(articles.ARTICLES, key=lambda item: item.is_summary):
            if article.key in article_keys or article.is_summary:
                continue
            existing_narrative = _article_narrative_from_file(ANALYSIS_DIR / article.output_filename)
            if existing_narrative:
                ctx.section_outputs[article.key] = existing_narrative
    def record_progress(current_article: articles.Article | None, completed_count: int) -> None:
        _write_writer_progress(
            results,
            current_article=current_article,
            completed_count=completed_count,
            total_count=len(article_queue),
            model=model,
            reasoning_effort=llm.reasoning_effort,
            editor_mode=editor_mode,
        )

    record_progress(None, 0)

    for article_index, article in enumerate(article_queue, start=1):
        record_progress(article, article_index - 1)
        output_path = ANALYSIS_DIR / article.output_filename
        reporter = persona_metadata(ctx.writer_preferences, article.key)
        evidence_fingerprint = ""
        try:
            evidence = article.scope(ctx)
            if not article.is_summary:
                # First article to scope a player claims it; later ones get a "covered elsewhere"
                # note instead -- kills the same-player-profiled-in-three-sections repetition.
                evidence = articles.apply_entity_dedup(ctx, evidence)
            if not evidence:
                results[article.key] = {"state": "skipped", "message": "No evidence available; deterministic version kept."}
                record_progress(article, article_index)
                continue

            output_path = ANALYSIS_DIR / article.output_filename
            editorial_context = _editorial_room_context(ctx, article, output_path)
            system_prompt = _article_system_prompt(article, ctx.writer_preferences, context)
            evidence_fingerprint = _article_evidence_fingerprint(
                article, evidence, system_prompt, context, editorial_context
            )
            previous = _previous_article_artifact(context, article.key)
            if _can_reuse_article(previous, output_path, evidence_fingerprint, reporter, model, editor_mode):
                narrative = _article_narrative_from_file(output_path)
                if not narrative:
                    raise ValueError("Existing article receipt matched but its narrative is empty.")
                if not article.is_summary:
                    ctx.section_outputs[article.key] = narrative
                results[article.key] = {
                    "state": "unchanged",
                    "message": f"{article.title} unchanged; evidence and article receipt still match.",
                    "reporter": reporter,
                    "evidence_fingerprint": evidence_fingerprint,
                    "content_hash": _content_hash(output_path),
                }
                record_progress(article, article_index)
                continue

            output = generate_article_via_llm(
                system_prompt,
                evidence,
                api_key,
                model,
                editorial_context=editorial_context,
            )
            evidence_ids = {str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")}
            validation = validate_article_output(output, evidence_ids, article.headers, evidence)
            if validation["valid"]:
                final_output = output
                final_validation = validation
                editorial_review: dict[str, Any] | None = None
                if editor_mode == "llm":
                    editor_failure = ""
                    try:
                        editor_output = review_article_via_llm(
                            _editor_system_prompt(article, ctx.writer_preferences, context),
                            evidence,
                            output,
                            api_key,
                            model,
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve the writer draft as an explicit held receipt.
                        editor_output = None
                        editor_failure = f"The desk editor request failed: {type(exc).__name__}."
                    final_output, editorial_review = _editor_review_result(
                        article,
                        output,
                        validation,
                        editor_output,
                        evidence,
                        model,
                    )
                    if editor_failure:
                        editorial_review.update(
                            {
                                "status": "held",
                                "decision": "hold",
                                "errors": list(dict.fromkeys([*(editorial_review.get("errors") or []), editor_failure])),
                                "note": "Held from publication because the desk editor request failed; retry the editor pass before printing this report.",
                            }
                        )
                    final_validation = validate_article_output(
                        final_output,
                        evidence_ids,
                        article.headers,
                        evidence,
                    )
                    # The editor's decision is authoritative only after the
                    # same independent article validator accepts its complete
                    # replacement. A held review keeps the valid writer draft
                    # in the receipt, but the reader facade will suppress it.
                    if editorial_review.get("status") != "approved":
                        final_validation = validation
                structured = final_validation["structured"] | {
                    "evidence_ids": final_validation.get("evidence_ids") or [],
                    "source_ids": final_validation.get("source_ids") or [],
                    "source_count": len(final_validation.get("source_ids") or []),
                    "source_quality": (
                        "multi_source" if len(final_validation.get("source_ids") or []) > 1
                        else "single_source" if final_validation.get("source_ids")
                        else "unattributed"
                    ),
                    "boundary_checks": final_validation.get("boundary_checks") or {},
                }
                output_path.write_text(
                    _render_article_markdown(
                        article,
                        final_validation["narrative"],
                        generated_at,
                        output_path,
                        ctx.writer_preferences,
                        article.key,
                        evidence_fingerprint,
                        model,
                        structured,
                        source_receipt={
                            "scope": "validated_article_evidence",
                            "evidence_fingerprint": evidence_fingerprint,
                            "source_count": len(final_validation.get("source_ids") or []),
                            "source_ids": final_validation.get("source_ids") or [],
                        },
                        editorial_review=editorial_review,
                    ),
                    encoding="utf-8",
                )
                content_hash = _content_hash(output_path)
                publication_status = (
                    "held"
                    if editorial_review and editorial_review.get("status") != "approved"
                    else "generated"
                )
                editor_errors = editorial_review.get("errors") if editorial_review else []
                _record_article_artifact(
                    context,
                    article,
                    output_path,
                    final_validation,
                    evidence_fingerprint=evidence_fingerprint,
                    content_hash=content_hash,
                    reporter=reporter,
                    model=model,
                    generation_metadata={
                        "writer": output.get("_provider_receipt") if isinstance(output, dict) else {},
                        "editor": (editorial_review or {}).get("provider_receipt", {}) if editorial_review else {},
                        "editor_mode": editor_mode,
                        "cost_known": False,
                    },
                    status=publication_status,
                    fallback_reason="; ".join(str(value) for value in (editor_errors or []) if str(value).strip()),
                    editorial_review=editorial_review,
                )
                if not article.is_summary and publication_status == "generated":
                    ctx.section_outputs[article.key] = final_validation["narrative"]
                results[article.key] = {
                    "state": "complete" if publication_status == "generated" else "held",
                    "message": (
                        f"{article.title} written and desk-approved."
                        if publication_status == "generated" and editorial_review
                        else f"{article.title} written."
                        if publication_status == "generated"
                        else f"{article.title} held by The Desk Editor."
                    ),
                    "warnings": final_validation["warnings"],
                    "editorial_review": editorial_review or {"mode": "deterministic", "status": "pending_llm_review"},
                    "reporter": reporter,
                    "evidence_fingerprint": evidence_fingerprint,
                    "content_hash": content_hash,
                }
                record_progress(article, article_index)
            else:
                _record_article_artifact(
                    context,
                    article,
                    output_path,
                    validation,
                    evidence_fingerprint=evidence_fingerprint,
                    content_hash=_content_hash(output_path) if output_path.exists() else "",
                    reporter=reporter,
                    model=model,
                    status="failed",
                    fallback_reason="; ".join(validation["errors"]),
                )
                results[article.key] = {"state": "failed", "message": f"{article.title} failed validation.", "errors": validation["errors"]}
                record_progress(article, article_index)
        except Exception as exc:  # noqa: BLE001 - one article failing must not sink the rest.
            _record_article_artifact(
                context,
                article,
                output_path,
                {"valid": False, "errors": [str(exc)]},
                evidence_fingerprint=evidence_fingerprint,
                content_hash=_content_hash(output_path) if output_path.exists() else "",
                reporter=reporter,
                model=model,
                status="failed",
                fallback_reason=str(exc),
            )
            results[article.key] = {"state": "failed", "message": f"{article.title} generation failed: {exc}"}
            record_progress(article, article_index)

    attempted = [state for state in results.values() if state["state"] != "skipped"]
    completed = [state for state in attempted if state["state"] in {"complete", "unchanged"}]
    held = [state for state in attempted if state["state"] == "held"]
    failed = [state for state in attempted if state["state"] == "failed"]
    if attempted and len(completed) == len(attempted):
        state = "complete"
    elif completed or held:
        state = "partial"
    else:
        state = "failed"
    return {
        "state": state,
        "message": (
            f"Articles published: {len(completed)} current, {len(held)} held by the desk editor, "
            f"{len(failed)} failed, {len(results) - len(attempted)} skipped."
        ),
        "generated_at": generated_at,
        "provider": llm.provider,
        "model": model,
        "reasoning_effort": llm.reasoning_effort,
        "editor_mode": editor_mode,
        "reporter_persona": persona_metadata(ctx.writer_preferences, "daily_brief"),
        "articles": results,
    }


def plan_articles_workflow(
    paths: LeaguePaths | None = None,
    context: FantasyContext | None = None,
) -> dict[str, Any]:
    """Describe the next writer run without making a provider request.

    The plan deliberately uses the same article scopes, prompt fingerprints,
    reporter identities, and reuse predicate as ``generate_articles_workflow``.
    It is therefore an inspectable cost gate rather than a second estimation
    model.  No secret, filesystem path, article body, or provider call is
    returned or performed.
    """
    if paths is not None:
        with operator_scope(paths):
            return plan_articles_workflow(context=context)

    generated_at = _now()
    llm = configured_llm()
    writer_config = writer_api_configuration()
    editor_mode = editorial_review_mode()
    ctx = articles.ArticleContext(
        analysis_dir=ANALYSIS_DIR,
        active_roster_id=(
            context.roster_id
            if context is not None
            else articles.resolve_active_roster_id()
        ),
        processed_dir=PROCESSED_DIR,
        user_id=context.user_id if context else None,
        league_id=context.league_id if context else "",
        season=context.season if context else "",
        team_name=context.team_name if context else "",
        writer_preferences=context.writer_preferences if context else {},
    )

    entries: dict[str, Any] = {}
    counts = {
        "generate": 0,
        "reuse": 0,
        "skipped": 0,
        "blocked": 0,
        "unavailable": 0,
    }
    planned_summary_inputs_changed = False
    for article in sorted(articles.ARTICLES, key=lambda item: item.is_summary):
        reporter = persona_metadata(ctx.writer_preferences, article.key)
        entry: dict[str, Any] = {
            "article": article.key,
            "title": article.title,
            "section": article.section,
            "reporter": reporter,
            "provider": llm.provider,
            "model": llm.model,
            "reasoning_effort": llm.reasoning_effort,
            "editor_mode": editor_mode,
            "state": "unavailable",
            "decision": "fallback",
            "reason": "The article plan could not inspect this desk.",
            "evidence_count": 0,
            "source_count": 0,
            "evidence_fingerprint": "",
            "current_content_hash": "",
            "current_receipt_status": "",
            "current_receipt_model": "",
        }
        try:
            evidence = article.scope(ctx)
            if not article.is_summary:
                evidence = articles.apply_entity_dedup(ctx, evidence)
            entry["evidence_count"] = len(evidence)
            entry["source_count"] = len(
                {
                    str(item.get("source_trace") or "").strip()
                    for item in evidence
                    if str(item.get("source_trace") or "").strip()
                }
            )
            if article.is_summary and planned_summary_inputs_changed and writer_config["configured"]:
                entry.update(
                    state="ready",
                    decision="generate",
                    summary_inputs_changed=True,
                    reason="A preceding desk is planned to change; the summary must be regenerated after its new prose exists.",
                )
                counts["generate"] += 1
                entries[article.key] = entry
                continue
            if not evidence:
                entry.update(
                    state="skipped",
                    decision="keep_fallback",
                    reason="No validated evidence is available for this desk.",
                )
                counts["skipped"] += 1
                entries[article.key] = entry
                continue

            output_path = ANALYSIS_DIR / article.output_filename
            editorial_context = _editorial_room_context(ctx, article, output_path)
            system_prompt = _article_system_prompt(article, ctx.writer_preferences, context)
            evidence_fingerprint = _article_evidence_fingerprint(
                article, evidence, system_prompt, context, editorial_context
            )
            previous = _previous_article_artifact(context, article.key)
            entry["evidence_fingerprint"] = evidence_fingerprint
            entry["current_content_hash"] = _content_hash(output_path)
            if previous:
                entry["current_receipt_status"] = str(previous.get("status") or "")
                entry["current_receipt_model"] = str(previous.get("model") or "")

            if _can_reuse_article(previous, output_path, evidence_fingerprint, reporter, llm.model, editor_mode):
                entry.update(
                    state="unchanged",
                    decision="reuse",
                    reason="Evidence, article content, reporter, and configured model still match.",
                )
                counts["reuse"] += 1
                if not article.is_summary:
                    narrative = _article_narrative_from_file(output_path)
                    if narrative:
                        # The summary scope consumes the section narratives.
                        # Replaying reused inputs keeps its no-cost fingerprint
                        # identical to the real workflow.
                        ctx.section_outputs[article.key] = narrative
            elif not writer_config["configured"]:
                entry.update(
                    state="blocked",
                    decision="generate",
                    reason=f"{writer_config['api_key_env']} is not configured; no provider request would be attempted.",
                )
                counts["blocked"] += 1
            else:
                reasons = []
                if not previous:
                    reasons.append("no current receipt")
                elif previous.get("status") != "generated":
                    reasons.append(f"receipt status is {previous.get('status') or 'unknown'}")
                elif previous.get("evidence_fingerprint") != evidence_fingerprint:
                    reasons.append("evidence changed")
                elif previous.get("content_hash") != entry["current_content_hash"]:
                    reasons.append("article content hash changed")
                elif previous.get("reporter_id") != str(reporter.get("persona_id") or ""):
                    reasons.append("reporter changed")
                elif previous.get("model") != llm.model:
                    reasons.append("configured model changed")
                entry.update(
                    state="ready",
                    decision="generate",
                    reason="; ".join(reasons) or "Current article receipt does not match the selected evidence.",
                )
                counts["generate"] += 1
                if not article.is_summary:
                    # A later daily brief cannot know the newly generated
                    # prose during a no-cost preview. It must be generated
                    # after any upstream desk changes, rather than being
                    # falsely reported as reusable from incomplete context.
                    planned_summary_inputs_changed = True
        except Exception as exc:  # noqa: BLE001 - plan must show a local seam failure, not hide it.
            entry.update(
                state="unavailable",
                decision="keep_fallback",
                # Do not echo exception text: local paths and provider details
                # do not belong in an authenticated browser receipt.
                reason=f"Evidence scope failed: {type(exc).__name__}.",
            )
            counts["unavailable"] += 1
        entries[article.key] = entry

    state = "ready" if writer_config["configured"] else "blocked"
    if counts["unavailable"] and not counts["generate"] and not counts["reuse"]:
        state = "unavailable"
    return {
        "state": state,
        "message": (
            f"Writer plan: {counts['generate']} generation call(s), "
            f"{counts['reuse']} reuse(s), {counts['skipped']} evidence-limited desk(s), "
            f"{counts['blocked']} blocked, {counts['unavailable']} unavailable. "
            "No provider request was made."
        ),
        "generated_at": generated_at,
        "scope": (
            f"{context.league_id}:{context.season}:{context.roster_id or 'unassigned'}"
            if context
            else "legacy"
        ),
        "provider": llm.provider,
        "model": llm.model,
        "reasoning_effort": llm.reasoning_effort,
        "editor_mode": editor_mode,
        "writer_api_configured": bool(writer_config["configured"]),
        "writer_api_key_env": writer_config["api_key_env"],
        "counts": counts,
        "articles": entries,
    }


def _record_article_artifact(
    context: FantasyContext | None,
    article: articles.Article,
    output_path: Path,
    validation: dict[str, Any],
    *,
    evidence_fingerprint: str = "",
    content_hash: str = "",
    reporter: dict[str, Any] | None = None,
    model: str = "",
    status: str = "generated",
    fallback_reason: str = "",
    generation_metadata: dict[str, Any] | None = None,
    editorial_review: dict[str, Any] | None = None,
) -> None:
    if context is None or context.user_id is None:
        return
    try:
        from app import db as app_db

        reporter = reporter or persona_metadata(context.writer_preferences, article.key)
        app_db.record_content_artifact(
            int(context.user_id),
            context.league_id,
            context.season,
            "article",
            article.key,
            str(output_path),
            source={
                "mode": "automatic_llm",
                "valid": bool(validation.get("valid")),
                "writer_preferences": context.writer_preferences,
                "reporter_persona": persona_metadata(context.writer_preferences, article.key),
                "llm": writer_api_configuration(),
                "editor_mode": editorial_review.get("mode", "deterministic") if editorial_review else "deterministic",
                "editorial_review": editorial_review or {},
            },
            article_id=f"article:{context.league_id}:{context.season}:{article.key}",
            section=article.section,
            roster_id=context.roster_id,
            source_receipt={
                "scope": "selected_league_validated_evidence",
                "evidence_fingerprint": evidence_fingerprint,
                "source_count": len(validation.get("source_ids") or []),
                "source_ids": validation.get("source_ids") or [],
            },
            generation_metadata=generation_metadata or {
                "provider": writer_api_configuration().get("provider"),
                "model": model,
                "reasoning_effort": writer_api_configuration().get("reasoning_effort"),
                "cost_known": False,
            },
            status=status,
            evidence_fingerprint=evidence_fingerprint,
            content_hash=content_hash,
            reporter_id=str(reporter.get("persona_id") or ""),
            writer_mode="automatic_llm",
            fallback_reason=fallback_reason,
            model=model,
        )
    except (TypeError, ValueError, OSError):
        # Artifact indexing must not erase a successfully written article.
        return


def _article_evidence_fingerprint(
    article: articles.Article,
    evidence: list[dict[str, Any]],
    system_prompt: str,
    context: FantasyContext | None,
    editorial_context: list[dict[str, Any]] | None = None,
) -> str:
    """Stable receipt for the exact evidence and editorial contract used by an article.

    Peer and previous-edition prose is deliberately excluded from this receipt.
    It is bounded, non-evidence context for a paid call, but it is not a stable
    factual input: during one run a peer may be newly generated after the
    read-only plan was calculated. Keeping it out of the reuse key makes the
    protected plan and the real workflow agree while still allowing a newly
    generated article to read the newsroom context.
    """
    del editorial_context
    payload = {
        "fingerprint_version": "article_evidence_v2",
        "article": article.key,
        "reporter": persona_metadata(context.writer_preferences if context else {}, article.key),
        "league_id": context.league_id if context else "",
        "season": context.season if context else "",
        "roster_id": context.roster_id if context else "",
        "team_name": context.team_name if context else "",
        "system_prompt": system_prompt,
        "evidence": evidence,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _content_hash(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 64), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _previous_article_artifact(context: FantasyContext | None, article_key: str) -> dict[str, Any] | None:
    if context is None or context.user_id is None:
        return None
    try:
        from app import db as app_db

        return app_db.get_content_artifact(
            int(context.user_id), context.league_id, context.season, article_key, artifact_type="article"
        )
    except (TypeError, ValueError, OSError):
        return None


def _can_reuse_article(
    previous: dict[str, Any] | None,
    output_path: Path,
    evidence_fingerprint: str,
    reporter: dict[str, Any],
    model: str,
    editor_mode: str = "deterministic",
) -> bool:
    if not previous or previous.get("status") != "generated" or not output_path.exists():
        return False
    if previous.get("evidence_fingerprint") != evidence_fingerprint:
        return False
    if previous.get("content_hash") != _content_hash(output_path):
        return False
    if previous.get("reporter_id") != str(reporter.get("persona_id") or ""):
        return False
    if previous.get("model") != model or previous.get("writer_mode") != "automatic_llm":
        return False
    source = previous.get("source") if isinstance(previous.get("source"), dict) else {}
    previous_editor_mode = str(source.get("editor_mode") or "deterministic").strip().lower()
    return previous_editor_mode == str(editor_mode or "deterministic").strip().lower()


def _article_narrative_from_file(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, text = text.partition("\n---")
    lines = [line for line in text.splitlines() if not line.startswith("# ")]
    return "\n".join(lines).strip()


def build_chat_context_markdown(paths: LeaguePaths | None = None) -> dict[str, Any]:
    """Renders the current evidence packet as clean markdown instead of raw JSON --
    a better hand-off for pasting into an ad-hoc chat than the manual copy-paste loop."""
    if paths is not None:
        with operator_scope(paths):
            return build_chat_context_markdown()
    build_insight_packet()
    packet = _safe_json(INSIGHT_PACKET_PATH)
    evidence = packet.get("evidence", [])
    managers = [item for item in evidence if item.get("entity_type") == "manager"]
    players = [item for item in evidence if item.get("entity_type") == "player"]

    lines = ["# Dynasty League Context", "", f"Generated {packet.get('generated_at', '')}", ""]
    for label, items in (("Managers", managers), ("Players", players)):
        if not items:
            continue
        lines.append(f"## {label}")
        for item in items:
            tags = item.get("tags", "")
            text = item.get("analysis_text", "")
            evidence_str = item.get("evidence", "")
            lines.append(f"- **{item.get('entity_name', '')}**: {tags}. {text} (evidence: {evidence_str})")
        lines.append("")

    return {"state": "complete", "markdown": "\n".join(lines).strip(), "generated_at": packet.get("generated_at", "")}


def rebuild_browser(
    paths: LeaguePaths | None = None,
    league_type: str = "dynasty",
    league_id: str = "",
) -> dict[str, Any]:
    if paths is not None:
        with operator_scope(paths):
            return rebuild_browser(league_type=league_type, league_id=paths.league_id)
    path = build_browser_site(
        SITE_DIR,
        PROCESSED_DIR,
        ANALYSIS_DIR,
        league_type=league_type,
        league_id=league_id,
    )
    return {"state": "complete", "message": "Browser bundle rebuilt.", "site_path": str(path.as_posix()), "generated_at": _now()}


def _run_job(
    name: str,
    job: Callable[[], dict[str, Any]],
    paths: LeaguePaths | None = None,
) -> None:
    global _ACTIVE_JOB
    with _LOCK:
        with operator_scope(paths):
            try:
                result = job()
                _write_status(_base_status("complete", result.get("message", f"{name} complete."), job=name) | result)
            except Exception as exc:  # pragma: no cover - status path is the behavior under test.
                _write_status(
                    _base_status("failed", f"{name} failed: {exc}", job=name)
                    | {"traceback": traceback.format_exc()}
                )
            finally:
                _ACTIVE_JOB = False


def _evidence_items(generated_at: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for artifact_name, entity_type, entity_key in (
        ("manager_dossiers.json", "manager", "roster_id"),
        ("player_dossiers.json", "player", "player_id"),
    ):
        payload = _safe_json(ANALYSIS_DIR / artifact_name)
        for index, item in enumerate(payload.get("items", [])[:80], start=1):
            entity_id = str(item.get(entity_key, ""))
            evidence_id = f"{entity_type}:{entity_id}:{index}"
            items.append(
                {
                    "evidence_id": evidence_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "entity_name": item.get("team_name") if entity_type == "manager" else item.get("player_name"),
                    "tags": item.get("tags", ""),
                    "confidence": item.get("confidence", ""),
                    "risk": item.get("risk", ""),
                    "analysis_text": item.get("analysis_text", ""),
                    "evidence": item.get("evidence", ""),
                    "source_trace": item.get("source_trace", ""),
                    "generated_at": generated_at,
                }
            )
    return items


def _write_writer_progress(
    results: dict[str, Any],
    *,
    current_article: articles.Article | None,
    completed_count: int,
    total_count: int,
    model: str,
    reasoning_effort: str,
    editor_mode: str,
) -> None:
    """Persist a safe, per-desk receipt while the newsroom is still running.

    A writer run is deliberately asynchronous and can spend several minutes
    across refresh, six desk calls, and optional editor calls. The old status
    receipt stayed at ``running`` with no indication of whether work was
    advancing. Keep the payload private and compact: enough for the reader to
    explain progress, never enough to expose evidence, prose, or host paths.
    """

    article_receipts: dict[str, dict[str, Any]] = {}
    for key, result in results.items():
        reporter = result.get("reporter") if isinstance(result, dict) else {}
        article_receipts[key] = {
            "state": result.get("state", "unknown") if isinstance(result, dict) else "unknown",
            "message": result.get("message", "") if isinstance(result, dict) else "",
            "reporter": {
                "persona_id": reporter.get("persona_id", "") if isinstance(reporter, dict) else "",
                "name": reporter.get("name", "") if isinstance(reporter, dict) else "",
            },
        }
    current_label = current_article.title if current_article is not None else "Preparing the newsroom"
    if current_article is not None:
        current_label = f"{current_article.title} ({completed_count}/{total_count})"
    _write_status(
        _base_status(
            "running",
            f"{current_label} is in progress.",
            job="generate-insights",
        )
        | {
            "provider": writer_api_configuration().get("provider", ""),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "editor_mode": editor_mode,
            "completed_count": completed_count,
            "total_count": total_count,
            "current_article": current_article.key if current_article is not None else "",
            "current_reporter": (
                persona_metadata({}, current_article.key)
                if current_article is not None
                else {}
            ),
            "articles": article_receipts,
        },
    )


def _base_status(
    state: str,
    message: str,
    job: str = "",
    paths: LeaguePaths | None = None,
) -> dict[str, Any]:
    packet_path = paths.operator_inbox_dir / "front_office_insight_packet.json" if paths else INSIGHT_PACKET_PATH
    output_path = paths.operator_outbox_dir / "front_office_insight_cards.json" if paths else INSIGHT_OUTPUT_PATH
    validated_path = paths.analysis_dir / "validated_insight_cards.json" if paths else VALIDATED_INSIGHTS_PATH
    return {
        "state": state,
        "job": job,
        "message": message,
        "updated_at": _now(),
        "owner_pid": os.getpid(),
        "operator_enabled": operator_enabled(),
        "packet_path": str(packet_path.as_posix()),
        "output_path": str(output_path.as_posix()),
        "validated_path": str(validated_path.as_posix()),
    }


def _reconcile_interrupted_status(status_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when a daemon job left a running receipt after process exit."""

    if payload.get("state") != "running" or _ACTIVE_JOB:
        return payload
    recovered = dict(payload)
    recovered.update(
        {
            "state": "failed",
            "message": "The previous operator job was interrupted before completion; retry the run.",
            "updated_at": _now(),
            "recovered_from_restart": True,
        }
    )
    _write_json(status_path, recovered)
    return recovered


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = load_json(path)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_status(payload: dict[str, Any]) -> None:
    _write_json(STATUS_PATH, payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
