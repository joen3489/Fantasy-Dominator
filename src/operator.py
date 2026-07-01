from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

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
        banned = [term for term in FORBIDDEN_TERMS if term in text]
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
        "Only use the evidence provided below. Every card's cited_evidence_ids must be real "
        "evidence_id values from that evidence list. Do not force a card for every evidence "
        "item -- prioritize roughly 10-20 of the most decision-relevant managers/players. "
        "Call emit_insight_cards exactly once with your complete set of cards."
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
            "max_tokens": 4096,
            "system": system_prompt,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "emit_insight_cards"},
            "messages": [{"role": "user", "content": json.dumps({"evidence": packet.get("evidence", [])})}],
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit_insight_cards":
            return block.get("input", {})
    raise ValueError("Anthropic response did not include an emit_insight_cards tool call.")


def generate_insights_automatically() -> dict[str, Any]:
    """Explicit, user-triggered, cost-incurring action -- fails loud on any problem
    rather than degrading silently like the free read-only source fetches do."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"state": "failed", "message": "ANTHROPIC_API_KEY is not set. Insight generation requires a real API key."}
    model = os.environ.get("FRONT_OFFICE_INSIGHT_MODEL", DEFAULT_INSIGHT_MODEL)

    build_insight_packet()
    packet = _safe_json(INSIGHT_PACKET_PATH)
    if not packet.get("evidence"):
        return {"state": "failed", "message": "No evidence available to generate insights from. Refresh data first."}

    try:
        output = generate_insight_output_via_llm(packet, api_key, model)
    except Exception as exc:
        return {"state": "failed", "message": f"LLM insight generation failed: {exc}"}

    output = dict(output) | {"generation_mode": "automatic_llm", "model": model}
    return import_insight_output(output)


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
