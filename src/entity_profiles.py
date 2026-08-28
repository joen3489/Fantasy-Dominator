"""Canonical, scope-bound LLM profiles over deterministic fantasy evidence.

Profiles are interpretation artifacts.  They never write into processed fact
tables, and every current profile retains the exact entity evidence fingerprint
that was validated at import time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .context import FantasyContext
from .league_paths import LeaguePaths
from .llm import configured_llm


PROFILE_PACKET_SCHEMA_VERSION = "codex_entity_profile_packet_v1"
PROFILE_INDEX_SCHEMA_VERSION = "canonical_entity_profiles_v1"
PROFILE_IMPORT_SCHEMA_VERSION = "codex_entity_profile_import_v1"
PROFILE_PACKET_FILENAME = "codex_entity_profile_packet.json"
PROFILE_INDEX_FILENAME = "canonical_entity_profiles.json"
PROFILE_IMPORT_FILENAME = "codex_entity_profile_import.json"

PROFILE_TOOL = {
    "name": "emit_entity_profile",
    "description": "Emit one league-scoped player or manager profile grounded only in the supplied evidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "current_state": {"type": "string"},
            "role_or_behavior": {"type": "string"},
            "market_or_trade_lane": {"type": "string"},
            "availability": {"type": "string"},
            "team_fit": {"type": "string"},
            "recommended_action": {"type": "string"},
            "counter_evidence": {"type": "string"},
            "risk": {"type": "string"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "reconsideration_trigger": {"type": "string"},
            "narrative_markdown": {"type": "string"},
            "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "headline",
            "summary",
            "current_state",
            "role_or_behavior",
            "market_or_trade_lane",
            "availability",
            "team_fit",
            "recommended_action",
            "counter_evidence",
            "risk",
            "confidence",
            "reconsideration_trigger",
            "narrative_markdown",
            "cited_evidence_ids",
        ],
        "additionalProperties": False,
    },
}

_PLAYER_SOURCES = (
    "roster_players",
    "player_dossiers",
    "player_signal_scores",
    "player_opportunity_scores",
    "player_horizon_market_scores",
    "available_player_horizon_scores",
    "action_recommendations",
    "league_news_impact",
    "team_fit_scores",
    "team_asset_inventory",
)
_MANAGER_SOURCES = (
    "manager_behavior_signals",
    "manager_cycle_profiles",
)
_FORBIDDEN_PATTERNS = (
    re.compile(r"\b(?:trade|offer|deal)\b.{0,40}\b(?:accepted|executed|sent|submitted)\b", re.I),
    re.compile(r"\bguaranteed\b", re.I),
    re.compile(r"\bwill\s+(?:accept|trade|sell|buy|overpay)\b", re.I),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error):
        return []


def _scope_rows(rows: Iterable[Mapping[str, Any]], context: FantasyContext) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        league_id = str(row.get("league_id") or "")
        season = str(row.get("season") or "")
        if league_id and league_id != str(context.league_id):
            continue
        if season and season != str(context.season):
            continue
        output.append(dict(row))
    return output


def _rank_value(row: Mapping[str, Any]) -> tuple[float, float]:
    def number(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    return (
        -number(row.get("market_rank") or row.get("action_rank"), 999999),
        number(row.get("market_value") or row.get("action_score") or row.get("news_impact"), 0),
    )


def _name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _source_ids(row: Mapping[str, Any], source_name: str) -> list[str]:
    values: list[str] = []
    raw = row.get("source_ids") or row.get("source_trace") or row.get("source") or source_name
    if isinstance(raw, (list, tuple, set)):
        pieces = raw
    else:
        pieces = re.split(r"[;|,]", str(raw or ""))
    for value in pieces:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return values or [source_name]


def _verified(context: FantasyContext) -> None:
    if context.user_id is None or not context.league_id or not context.season or context.roster_id is None:
        raise ValueError("Canonical profiles require a user, league, season, and exact roster_id.")
    if str(context.identity_status or "").lower() not in {"verified", "verified_roster_match"}:
        raise ValueError("Canonical profiles require a verified Clerk-to-Sleeper roster identity.")


def _stable_hash(value: Mapping[str, Any], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    stable = {str(key): item for key, item in value.items() if str(key) not in excluded}
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _eligible_cohort(paths: LeaguePaths, context: FantasyContext) -> list[dict[str, Any]]:
    tables = {
        name: _scope_rows(_rows(paths.processed_dir / f"{name}.csv"), context)
        for name in {*_PLAYER_SOURCES, *_MANAGER_SOURCES, "players", "player_market_values"}
    }
    reasons: dict[tuple[str, str], set[str]] = {}
    names: dict[tuple[str, str], str] = {}

    def include(entity_type: str, entity_id: Any, name: Any, reason: str) -> None:
        key = (entity_type, str(entity_id or "").strip())
        if not key[1]:
            return
        reasons.setdefault(key, set()).add(reason)
        if str(name or "").strip():
            names[key] = str(name).strip()

    for row in tables["roster_players"]:
        if str(row.get("roster_id") or "") == str(context.roster_id):
            include("player", row.get("player_id"), row.get("player_name"), "selected_roster")
    # The manager-facing waiver room intentionally shows only five names, but
    # that top five changes with roster need and clock coverage. Keep a wider
    # bounded available-market bench eligible so the surfaced decision cards
    # are not stranded without a canonical profile.
    for row in sorted(tables["available_player_horizon_scores"], key=_rank_value, reverse=True)[:25]:
        include("player", row.get("player_id"), row.get("player_name"), "top_available_market")
    roster_player_ids = {str(row.get("player_id") or "") for row in tables["roster_players"] if row.get("player_id")}
    roster_player_names = {_name_key(row.get("player_name")) for row in tables["roster_players"] if row.get("player_name")}
    canonical_by_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in tables["players"]:
        canonical_by_name.setdefault(
            (_name_key(row.get("player_name") or row.get("full_name")), str(row.get("position") or "").upper()),
            [],
        ).append(row)
    available_market_count = 0
    for row in sorted(tables["player_market_values"], key=_rank_value, reverse=True):
        if _number(row.get("market_value")) <= 0:
            continue
        player_id = str(row.get("player_id") or "").strip()
        player_name = str(row.get("player_name") or "").strip()
        position = str(row.get("position") or "").upper()
        if not player_id:
            matches = canonical_by_name.get((_name_key(player_name), position), [])
            if len(matches) == 1:
                player_id = str(matches[0].get("player_id") or "").strip()
        if not player_id or player_id in roster_player_ids or _name_key(player_name) in roster_player_names:
            continue
        if ("player", player_id) not in reasons:
            include("player", player_id, player_name, "reader_waiver_market")
        available_market_count += 1
        if available_market_count >= 25:
            break
    action_rows = [row for row in tables["action_recommendations"] if str(row.get("roster_id") or "") == str(context.roster_id)]
    for row in sorted(action_rows, key=_rank_value, reverse=True)[:10]:
        include("player", row.get("player_id"), row.get("player_name"), "active_recommendation")
    for row in sorted(tables["league_news_impact"], key=lambda item: str(item.get("published_at") or ""), reverse=True)[:10]:
        include("player", row.get("player_id"), row.get("player_name"), "material_news")

    for filename, reason in (("target_theses.json", "active_target"), ("sell_theses.json", "active_shop_candidate")):
        payload = _load_json(paths.analysis_dir / filename)
        for row in (payload.get("items") or [])[:10]:
            if isinstance(row, Mapping):
                include("player", row.get("player_id"), row.get("player_name"), reason)
    trade_payload = _load_json(paths.analysis_dir / "trade_theses.json")
    for row in (trade_payload.get("items") or [])[:10]:
        if not isinstance(row, Mapping):
            continue
        include(
            "manager",
            row.get("target_manager_roster_id"),
            row.get("target_manager_name") or row.get("target_team"),
            "active_trade_counterparty",
        )

    return [
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_key": f"{entity_type}:{entity_id}",
            "entity_name": names.get((entity_type, entity_id), f"{entity_type.title()} {entity_id}"),
            "eligibility_reasons": sorted(entity_reasons),
        }
        for (entity_type, entity_id), entity_reasons in sorted(reasons.items())
    ]


def _entity_evidence(paths: LeaguePaths, context: FantasyContext, entity: Mapping[str, Any]) -> list[dict[str, Any]]:
    entity_type = str(entity.get("entity_type") or "")
    entity_id = str(entity.get("entity_id") or "")
    packets: list[dict[str, Any]] = []

    def add(source_name: str, row: Mapping[str, Any]) -> None:
        packets.append(
            {
                "evidence_id": f"profile:{entity_type}:{entity_id}:{source_name}:{len(packets) + 1}",
                "source_table": source_name,
                "source_ids": _source_ids(row, source_name),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "facts": deepcopy(dict(row)),
            }
        )

    if entity_type == "player":
        for source_name in _PLAYER_SOURCES:
            for row in _scope_rows(_rows(paths.processed_dir / f"{source_name}.csv"), context):
                row_id = str(row.get("player_id") or row.get("asset_id") or "")
                if row_id == entity_id:
                    add(source_name, row)
                    if len(packets) >= 18:
                        return packets
        for filename in ("player_dossiers.json", "target_theses.json", "sell_theses.json"):
            payload = _load_json(paths.analysis_dir / filename)
            for row in payload.get("items") or []:
                if isinstance(row, Mapping) and str(row.get("player_id") or "") == entity_id:
                    add(filename.removesuffix(".json"), row)
    else:
        for source_name in _MANAGER_SOURCES:
            for row in _scope_rows(_rows(paths.processed_dir / f"{source_name}.csv"), context):
                if str(row.get("roster_id") or "") == entity_id:
                    add(source_name, row)
        for filename, id_field in (("manager_dossiers.json", "roster_id"), ("trade_theses.json", "target_manager_roster_id")):
            payload = _load_json(paths.analysis_dir / filename)
            for row in payload.get("items") or []:
                if isinstance(row, Mapping) and str(row.get(id_field) or "") == entity_id:
                    add(filename.removesuffix(".json"), row)
    return packets[:18]


def _profile_system_prompt(entity: Mapping[str, Any], context: FantasyContext) -> str:
    entity_type = str(entity.get("entity_type") or "")
    boundary = (
        "For a manager, describe observed behavior and possible conversation lanes only. Never claim intent or predict acceptance."
        if entity_type == "manager"
        else "For a player, separate current role, market, availability, team fit, and the manager's next decision. Missing waiver price or availability evidence must stay visibly missing."
    )
    return (
        "You are the Fantasy Dominator profile analyst. Write one useful, candid profile for the exact selected league and roster. "
        "Deterministic evidence owns every fact. Your job is interpretation, prioritization, and clear uncertainty—not invention. "
        f"{boundary} Cite only literal evidence_id values from the packet. Do not imply that a waiver claim, offer, message, trade, or lineup change happened. "
        f"Selected league={context.league_id}; season={context.season}; roster_id={context.roster_id}; entity={entity.get('entity_key')}."
    )


def build_profile_packet(
    paths: LeaguePaths,
    context: FantasyContext,
    entity_keys: set[str] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    _verified(context)
    paths.ensure()
    explicit_selection = bool(entity_keys)
    current_index = _load_json(paths.analysis_dir / PROFILE_INDEX_FILENAME)
    current = {
        str(item.get("entity_key") or ""): item
        for item in (current_index.get("items") or [])
        if isinstance(item, Mapping)
    }
    cohort = _eligible_cohort(paths, context)
    if entity_keys:
        requested = {str(value).strip() for value in entity_keys if str(value).strip()}
        known = {str(item.get("entity_key") or "") for item in cohort}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError("Unknown or ineligible profile entity key(s): " + ", ".join(unknown))
        cohort = [item for item in cohort if item["entity_key"] in requested]
    llm = configured_llm()
    generation_items: list[dict[str, Any]] = []
    reused: list[str] = []
    blocked: list[dict[str, str]] = []
    for entity in cohort:
        evidence = _entity_evidence(paths, context, entity)
        if not evidence:
            blocked.append({"entity_key": entity["entity_key"], "reason": "No entity-scoped deterministic evidence is available."})
            continue
        item = {
            **entity,
            "system_prompt": _profile_system_prompt(entity, context),
            "evidence": evidence,
            "output_tool": deepcopy(PROFILE_TOOL),
            "model": llm.model,
            "reasoning_effort": llm.reasoning_effort,
        }
        item["evidence_fingerprint"] = _stable_hash(
            {
                "schema_version": PROFILE_PACKET_SCHEMA_VERSION,
                "scope": {
                    "league_id": context.league_id,
                    "season": context.season,
                    "roster_id": context.roster_id,
                },
                "entity": entity,
                "system_prompt": item["system_prompt"],
                "evidence": evidence,
            }
        )
        existing = current.get(entity["entity_key"])
        if (
            isinstance(existing, Mapping)
            and existing.get("status") == "current"
            and existing.get("writer_mode") == "codex_task"
            and existing.get("evidence_fingerprint") == item["evidence_fingerprint"]
        ):
            reused.append(entity["entity_key"])
        else:
            generation_items.append(item)
    packet = {
        "schema_version": PROFILE_PACKET_SCHEMA_VERSION,
        "generated_at": _now(),
        "state": "ready" if generation_items else "unchanged" if reused and not blocked else "blocked" if not cohort else "partial",
        "writer_mode": "codex_task",
        "scope": {
            "user_id": str(context.user_id),
            "league_id": str(context.league_id),
            "season": str(context.season),
            "roster_id": int(context.roster_id),
            "identity_status": str(context.identity_status),
        },
        "cohort": cohort,
        "cohort_scope": "explicit_entities" if explicit_selection else "full_cohort",
        "cohort_entity_keys": [item["entity_key"] for item in cohort],
        "entity_keys": [item["entity_key"] for item in generation_items],
        "reused_entity_keys": reused,
        "blocked": blocked,
        "profiles": generation_items,
    }
    packet["packet_fingerprint"] = _stable_hash(packet, {"generated_at", "packet_fingerprint"})
    if persist:
        _write_json(paths.operator_inbox_dir / PROFILE_PACKET_FILENAME, packet)
    return packet


def _validate_output(output: Mapping[str, Any], packet_item: Mapping[str, Any]) -> dict[str, Any]:
    required = list(PROFILE_TOOL["input_schema"]["required"])
    errors = [f"missing required field {field}" for field in required if field not in output]
    for field in required:
        if field == "cited_evidence_ids":
            continue
        if not str(output.get(field) or "").strip() and field not in {"availability", "team_fit"}:
            errors.append(f"field {field} is empty")
    if str(output.get("confidence") or "").lower() not in {"low", "medium", "high"}:
        errors.append("confidence must be low, medium, or high")
    narrative = str(output.get("narrative_markdown") or "")
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(narrative):
            errors.append("profile contains forbidden certainty or transaction language")
            break
    allowed_ids = {
        str(item.get("evidence_id") or "")
        for item in (packet_item.get("evidence") or [])
        if isinstance(item, Mapping)
    }
    cited = {str(value) for value in (output.get("cited_evidence_ids") or []) if str(value).strip()}
    if not cited:
        errors.append("profile has no cited evidence IDs")
    unknown = sorted(cited - allowed_ids)
    if unknown:
        errors.append("profile cites unknown evidence IDs: " + ", ".join(unknown))
    if str(packet_item.get("entity_type")) == "player" and not str(output.get("availability") or "").strip():
        errors.append("player profile does not state the availability boundary")
    source_ids = sorted({
        str(source_id)
        for evidence in (packet_item.get("evidence") or [])
        if isinstance(evidence, Mapping)
        for source_id in (evidence.get("source_ids") or [])
        if str(source_id).strip()
    })
    if not source_ids:
        errors.append("profile has no deterministic source receipt")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "cited_evidence_ids": sorted(cited & allowed_ids),
        "source_ids": source_ids,
    }


def import_profile_output(
    payload: Mapping[str, Any],
    paths: LeaguePaths,
    context: FantasyContext,
) -> dict[str, Any]:
    _verified(context)
    stored = _load_json(paths.operator_inbox_dir / PROFILE_PACKET_FILENAME)
    expected_fingerprint = str(stored.get("packet_fingerprint") or "")
    if stored.get("schema_version") != PROFILE_PACKET_SCHEMA_VERSION or not expected_fingerprint:
        raise ValueError("No current canonical profile packet exists for this league scope.")
    if expected_fingerprint != _stable_hash(stored, {"generated_at", "packet_fingerprint"}):
        raise ValueError("The stored canonical profile packet receipt is invalid.")
    if str(payload.get("packet_fingerprint") or "") != expected_fingerprint:
        raise ValueError("The submitted profile packet_fingerprint is stale or belongs to another scope.")
    scope = stored.get("scope") if isinstance(stored.get("scope"), Mapping) else {}
    if (
        str(scope.get("user_id")) != str(context.user_id)
        or str(scope.get("league_id")) != str(context.league_id)
        or str(scope.get("season")) != str(context.season)
        or str(scope.get("roster_id")) != str(context.roster_id)
    ):
        raise ValueError("The canonical profile packet scope does not match the selected roster.")
    current_packet = build_profile_packet(
        paths,
        context,
        None
        if stored.get("cohort_scope") == "full_cohort"
        else {str(key) for key in (stored.get("cohort_entity_keys") or stored.get("entity_keys") or [])},
        persist=False,
    )
    if str(current_packet.get("packet_fingerprint") or "") != expected_fingerprint:
        raise ValueError("Entity evidence changed after export; export a new canonical profile packet.")
    raw_profiles = payload.get("profiles")
    submitted = raw_profiles if isinstance(raw_profiles, Mapping) else {}
    expected_keys = {str(key) for key in (stored.get("entity_keys") or [])}
    if set(map(str, submitted)) != expected_keys:
        raise ValueError("Profile import must contain every changed entity exactly once.")
    packet_items = {
        str(item.get("entity_key") or ""): item
        for item in (stored.get("profiles") or [])
        if isinstance(item, Mapping)
    }
    prepared = []
    errors: dict[str, list[str]] = {}
    for entity_key in sorted(expected_keys):
        item = submitted.get(entity_key)
        item = item if isinstance(item, Mapping) else {}
        packet_item = packet_items.get(entity_key) or {}
        if str(item.get("evidence_fingerprint") or "") != str(packet_item.get("evidence_fingerprint") or ""):
            errors[entity_key] = ["evidence_fingerprint does not match the entity packet"]
            continue
        output = item.get("output") if isinstance(item.get("output"), Mapping) else {}
        validation = _validate_output(output, packet_item)
        if not validation["valid"]:
            errors[entity_key] = validation["errors"]
            continue
        prepared.append((entity_key, packet_item, dict(output), validation))
    if errors:
        receipt = {
            "schema_version": PROFILE_IMPORT_SCHEMA_VERSION,
            "state": "rejected",
            "imported_at": _now(),
            "packet_fingerprint": expected_fingerprint,
            "errors": errors,
            "written_entity_keys": [],
        }
        _write_json(paths.operator_status_dir / PROFILE_IMPORT_FILENAME, receipt)
        return receipt

    index_path = paths.analysis_dir / PROFILE_INDEX_FILENAME
    existing_index = _load_json(index_path)
    current = {
        str(item.get("entity_key") or ""): dict(item)
        for item in (existing_index.get("items") or [])
        if isinstance(item, Mapping)
    }
    imported_at = _now()
    model = str(payload.get("model") or configured_llm().model or "gpt-5.6-luna")
    for entity_key, packet_item, output, validation in prepared:
        profile = {
            "schema_version": PROFILE_INDEX_SCHEMA_VERSION,
            "profile_id": f"profile:{context.league_id}:{context.season}:{context.roster_id}:{entity_key}",
            "entity_key": entity_key,
            "entity_type": packet_item.get("entity_type"),
            "entity_id": packet_item.get("entity_id"),
            "entity_name": packet_item.get("entity_name"),
            "eligibility_reasons": packet_item.get("eligibility_reasons") or [],
            "scope": dict(scope),
            "status": "current",
            "writer_mode": "codex_task",
            "model": model,
            "generated_at": imported_at,
            "evidence_fingerprint": packet_item.get("evidence_fingerprint"),
            "packet_fingerprint": expected_fingerprint,
            "validation": validation,
            "profile": output,
        }
        profile_path = paths.analysis_dir / "entity_profiles" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", entity_key) + ".json")
        _write_json(profile_path, profile)
        current[entity_key] = profile
        try:
            from app import db as app_db

            content_hash = hashlib.sha256(profile_path.read_bytes()).hexdigest()
            app_db.record_content_artifact(
                int(context.user_id),
                context.league_id,
                context.season,
                "entity_profile",
                entity_key,
                str(profile_path),
                source={"mode": "codex_task", "valid": True},
                article_id=profile["profile_id"],
                section="entity-profile",
                roster_id=context.roster_id,
                source_receipt={
                    "source_ids": validation["source_ids"],
                    "evidence_ids": validation["cited_evidence_ids"],
                    "packet_fingerprint": expected_fingerprint,
                },
                generation_metadata={"provider": "codex", "model": model, "cost_known": False},
                status="generated",
                evidence_fingerprint=str(packet_item.get("evidence_fingerprint") or ""),
                content_hash=content_hash,
                reporter_id="profile_analyst",
                writer_mode="codex_task",
                model=model,
            )
        except (OSError, TypeError, ValueError):
            pass
    if stored.get("cohort_scope") == "full_cohort":
        cohort_keys = {str(item.get("entity_key") or "") for item in (stored.get("cohort") or []) if isinstance(item, Mapping)}
        for entity_key, profile in current.items():
            if entity_key not in cohort_keys and profile.get("status") == "current":
                profile["status"] = "historical"
    index = {
        "schema_version": PROFILE_INDEX_SCHEMA_VERSION,
        "generated_at": imported_at,
        "scope": dict(scope),
        "items": sorted(current.values(), key=lambda item: str(item.get("entity_key") or "")),
    }
    _write_json(index_path, index)
    receipt = {
        "schema_version": PROFILE_IMPORT_SCHEMA_VERSION,
        "state": "complete",
        "imported_at": imported_at,
        "packet_fingerprint": expected_fingerprint,
        "model": model,
        "writer_mode": "codex_task",
        "written_entity_keys": [item[0] for item in prepared],
        "reused_entity_keys": stored.get("reused_entity_keys") or [],
        "errors": {},
    }
    _write_json(paths.operator_status_dir / PROFILE_IMPORT_FILENAME, receipt)
    return receipt
