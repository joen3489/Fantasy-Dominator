from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
