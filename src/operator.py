from __future__ import annotations

import json
import os
import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from . import articles
from .browser_site import build_browser_site
from .utils import (
    ANALYSIS_DIR,
    OPERATOR_INBOX_DIR,
    OPERATOR_OUTBOX_DIR,
    OPERATOR_STATUS_DIR,
    PROCESSED_DIR,
    SITE_DIR,
    ensure_dirs,
    load_json,
)


STATUS_PATH = OPERATOR_STATUS_DIR / "operator_status.json"
INSIGHT_PACKET_PATH = OPERATOR_INBOX_DIR / "front_office_insight_packet.json"
INSIGHT_OUTPUT_PATH = OPERATOR_OUTBOX_DIR / "front_office_insight_cards.json"
VALIDATED_INSIGHTS_PATH = ANALYSIS_DIR / "validated_insight_cards.json"
INSIGHT_VALIDATION_PATH = ANALYSIS_DIR / "insight_card_validation.json"
DAILY_GM_BRIEF_PATH = ANALYSIS_DIR / "daily_gm_brief.md"
DAILY_GM_BRIEF_VALIDATION_PATH = ANALYSIS_DIR / "daily_gm_brief_validation.json"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_INSIGHT_MODEL = "claude-haiku-4-5-20251001"

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


def operator_enabled() -> bool:
    return bool(os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN"))


def token_valid(headers: dict[str, str]) -> bool:
    expected = os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN", "")
    if not expected:
        return False
    supplied = headers.get("x-front-office-token") or headers.get("authorization", "").replace("Bearer ", "")
    return supplied == expected


def status() -> dict[str, Any]:
    ensure_dirs()
    if STATUS_PATH.exists():
        try:
            payload = load_json(STATUS_PATH)
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return _base_status("idle", "Operator loop is ready.")


def start_job(name: str, job: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    with _LOCK:
        current = status()
        if current.get("state") == "running":
            return current | {"accepted": False, "message": "Another operator job is already running."}
        _write_status(_base_status("running", f"{name} started.", job=name))
    thread = threading.Thread(target=_run_job, args=(name, job), daemon=True)
    thread.start()
    return status() | {"accepted": True}


def build_insight_packet() -> dict[str, Any]:
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


def validate_insight_output() -> dict[str, Any]:
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


def import_insight_output(payload: dict[str, Any]) -> dict[str, Any]:
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
    """Call the Anthropic Messages API with the packet's own instructions/evidence,
    forcing a tool call so the response is reliably structured JSON matching
    required_output_schema -- far more robust than parsing freeform text."""
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
    response = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 8192,
            "system": system_prompt,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "emit_insight_cards"},
            "messages": [{"role": "user", "content": json.dumps({"evidence": packet.get("evidence", [])})}],
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("stop_reason") == "max_tokens":
        raise ValueError("Anthropic response was truncated at the token limit before finishing the insight cards.")
    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit_insight_cards":
            return block.get("input", {})
    raise ValueError("Anthropic response did not include an emit_insight_cards tool call.")


def generate_daily_gm_brief_via_llm(packet: dict[str, Any], api_key: str, model: str) -> dict[str, Any]:
    """Sibling to generate_insight_output_via_llm() for a different output shape: one narrative
    blob instead of a list of entity cards, so it gets its own persona-carrying system prompt and
    its own forced tool rather than overloading the entity-card schema."""
    response = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2048,
            "system": DAILY_GM_BRIEF_SYSTEM_PROMPT,
            "tools": [DAILY_GM_BRIEF_TOOL],
            "tool_choice": {"type": "tool", "name": "emit_daily_gm_brief"},
            "messages": [{"role": "user", "content": json.dumps({"evidence": packet.get("evidence", [])})}],
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("stop_reason") == "max_tokens":
        raise ValueError("Anthropic response was truncated at the token limit before finishing the narrative.")
    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit_daily_gm_brief":
            return block.get("input", {})
    raise ValueError("Anthropic response did not include an emit_daily_gm_brief tool call.")


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


def generate_insights_automatically() -> dict[str, Any]:
    """Explicit, user-triggered, cost-incurring action -- fails loud on any problem
    rather than degrading silently like the free read-only source fetches do. Runs both
    the entity-card pipeline and the narrative-brief pipeline in one action; each is
    independently wrapped so one failing never hides or blocks the other's result."""
    generated_at = _now()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "state": "failed",
            "message": "ANTHROPIC_API_KEY is not set. No LLM call was attempted.",
            "generated_at": generated_at,
            "insight_cards": {"state": "skipped"},
            "daily_gm_brief": {"state": "skipped"},
        }
    model = os.environ.get("FRONT_OFFICE_INSIGHT_MODEL", DEFAULT_INSIGHT_MODEL)

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
        card_output = dict(card_output) | {"generation_mode": "automatic_llm", "model": model}
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
    "description": "Emit one section article as markdown prose grounded in the provided evidence.",
    "input_schema": {
        "type": "object",
        "properties": {
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
        "required": ["narrative_markdown", "cited_evidence_ids"],
    },
}

_CITATION_RULES = (
    "Every sentence containing a specific factual claim must be traceable to at least one evidence_id "
    "you cite in cited_evidence_ids. Each evidence item below has its own \"evidence_id\" field, e.g. "
    "\"player:4984:12\" or \"manager:6:3\" -- copy that exact string character-for-character into "
    "cited_evidence_ids for items you actually used. Never construct, reformat, or guess an ID yourself, "
    "even if you know a real numeric ID; only ever use the literal evidence_id strings given to you."
)


def _article_system_prompt(article: articles.Article) -> str:
    return f"{articles.load_prompt(article.prompt_filename)}\n\n{_SHARED_SAFETY_RULES}\n\n{_CITATION_RULES}"


def generate_article_via_llm(system_prompt: str, evidence: list[dict[str, Any]], api_key: str, model: str) -> dict[str, Any]:
    """Focused single-article call. Small output (one section, a few hundred words) so a 4096
    ceiling has ample headroom and truncation is a non-issue, unlike the old all-cards-at-once call."""
    response = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "tools": [ARTICLE_TOOL],
            "tool_choice": {"type": "tool", "name": "emit_article"},
            "messages": [{"role": "user", "content": json.dumps({"evidence": evidence})}],
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("stop_reason") == "max_tokens":
        raise ValueError("Anthropic response was truncated at the token limit before finishing the article.")
    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit_article":
            return block.get("input", {})
    raise ValueError("Anthropic response did not include an emit_article tool call.")


def validate_article_output(output: dict[str, Any], evidence_ids: set[str], headers: tuple[str, ...]) -> dict[str, Any]:
    """Independent per-article validation: required headers (if any), the shared phrase-proximity
    forbidden-language scan, and lenient citation (reject only if NONE of the cited IDs are real,
    since a synthesized article can plausibly drop one citation among several correct ones)."""
    narrative = str(output.get("narrative_markdown", "")) if isinstance(output, dict) else ""
    cited = {str(value) for value in output.get("cited_evidence_ids", [])} if isinstance(output, dict) else set()
    valid_citations = cited & evidence_ids
    unknown_citations = cited - evidence_ids
    errors: list[str] = []
    warnings: list[str] = []

    if not narrative.strip():
        errors.append("Article narrative_markdown is empty.")
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

    return {"valid": not errors, "errors": errors, "warnings": warnings, "narrative": narrative, "word_count": len(narrative.split())}


def _render_article_markdown(article: articles.Article, narrative: str, generated_at: str, output_path: Path) -> str:
    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    front_lines = [
        "---",
        f"artifact_type: {article.key}",
        f"generated_at: {generated_at}",
        "model_mode: automatic_llm",
    ]
    for key in ("roster_id", "team_name"):
        value = _front_matter_value(existing, key)
        if value:
            front_lines.append(f"{key}: {value}")
    front_lines.append("---")
    return "\n".join(front_lines) + f"\n\n# {article.title}\n\n{narrative.strip()}\n"


def generate_articles_workflow() -> dict[str, Any]:
    """Explicit, user-triggered, cost-incurring action. Generates one article per meaningful
    section (each independently validated, each falling back to its deterministic .md on failure),
    then a daily brief that synthesizes across them. Fails loud only on missing API key."""
    generated_at = _now()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"state": "failed", "message": "ANTHROPIC_API_KEY is not set. No LLM call was attempted.", "generated_at": generated_at, "articles": {}}
    model = os.environ.get("FRONT_OFFICE_INSIGHT_MODEL", DEFAULT_INSIGHT_MODEL)

    ctx = articles.ArticleContext(analysis_dir=ANALYSIS_DIR, active_roster_id=articles.resolve_active_roster_id())
    results: dict[str, Any] = {}

    for article in sorted(articles.ARTICLES, key=lambda item: item.is_summary):
        try:
            evidence = article.scope(ctx)
            if not article.is_summary:
                # First article to scope a player claims it; later ones get a "covered elsewhere"
                # note instead -- kills the same-player-profiled-in-three-sections repetition.
                evidence = articles.apply_entity_dedup(ctx, evidence)
            if not evidence:
                results[article.key] = {"state": "skipped", "message": "No evidence available; deterministic version kept."}
                continue
            output = generate_article_via_llm(_article_system_prompt(article), evidence, api_key, model)
            evidence_ids = {str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")}
            validation = validate_article_output(output, evidence_ids, article.headers)
            if validation["valid"]:
                output_path = ANALYSIS_DIR / article.output_filename
                output_path.write_text(_render_article_markdown(article, validation["narrative"], generated_at, output_path), encoding="utf-8")
                if not article.is_summary:
                    ctx.section_outputs[article.key] = validation["narrative"]
                results[article.key] = {"state": "complete", "message": f"{article.title} written.", "warnings": validation["warnings"]}
            else:
                results[article.key] = {"state": "failed", "message": f"{article.title} failed validation.", "errors": validation["errors"]}
        except Exception as exc:  # noqa: BLE001 - one article failing must not sink the rest.
            results[article.key] = {"state": "failed", "message": f"{article.title} generation failed: {exc}"}

    attempted = [state for state in results.values() if state["state"] != "skipped"]
    completed = [state for state in attempted if state["state"] == "complete"]
    if attempted and len(completed) == len(attempted):
        state = "complete"
    elif completed:
        state = "partial"
    else:
        state = "failed"
    return {
        "state": state,
        "message": f"Articles generated: {len(completed)} complete, {len(attempted) - len(completed)} failed, {len(results) - len(attempted)} skipped.",
        "generated_at": generated_at,
        "articles": results,
    }


def build_chat_context_markdown() -> dict[str, Any]:
    """Renders the current evidence packet as clean markdown instead of raw JSON --
    a better hand-off for pasting into an ad-hoc chat than the manual copy-paste loop."""
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


def rebuild_browser() -> dict[str, Any]:
    path = build_browser_site(SITE_DIR, PROCESSED_DIR, ANALYSIS_DIR)
    return {"state": "complete", "message": "Browser bundle rebuilt.", "site_path": str(path.as_posix()), "generated_at": _now()}


def _run_job(name: str, job: Callable[[], dict[str, Any]]) -> None:
    try:
        result = job()
        _write_status(_base_status("complete", result.get("message", f"{name} complete."), job=name) | result)
    except Exception as exc:  # pragma: no cover - status path is the behavior under test.
        _write_status(
            _base_status("failed", f"{name} failed: {exc}", job=name)
            | {"traceback": traceback.format_exc()}
        )


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


def _base_status(state: str, message: str, job: str = "") -> dict[str, Any]:
    return {
        "state": state,
        "job": job,
        "message": message,
        "updated_at": _now(),
        "operator_enabled": operator_enabled(),
        "packet_path": str(INSIGHT_PACKET_PATH.as_posix()),
        "output_path": str(INSIGHT_OUTPUT_PATH.as_posix()),
        "validated_path": str(VALIDATED_INSIGHTS_PATH.as_posix()),
    }


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
