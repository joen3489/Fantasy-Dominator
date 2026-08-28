from __future__ import annotations

import hashlib
import csv
import json
import os
import re
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import requests

from . import articles
from .browser_site import build_browser_site
from .context import FantasyContext
from .league_paths import LeaguePaths
from .llm import call_structured_tool, configured_llm, llm_timeout_seconds, writer_api_configuration
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
CODEX_EDITORIAL_PACKET_PATH = OPERATOR_INBOX_DIR / "codex_editorial_packet.json"
CODEX_EDITORIAL_IMPORT_RECEIPT_PATH = OPERATOR_STATUS_DIR / "codex_editorial_import.json"
VALIDATED_INSIGHTS_PATH = ANALYSIS_DIR / "validated_insight_cards.json"
INSIGHT_VALIDATION_PATH = ANALYSIS_DIR / "insight_card_validation.json"
DAILY_GM_BRIEF_PATH = ANALYSIS_DIR / "daily_gm_brief.md"
DAILY_GM_BRIEF_VALIDATION_PATH = ANALYSIS_DIR / "daily_gm_brief_validation.json"
EDITION_EXECUTION_RECEIPT_SCHEMA_VERSION = "edition_execution_receipt_v1"
CODEX_EDITORIAL_PACKET_SCHEMA_VERSION = "codex_editorial_packet_v1"
CODEX_EDITORIAL_IMPORT_SCHEMA_VERSION = "codex_editorial_import_v1"

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


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


class EditionLeaseLost(RuntimeError):
    """Raised when a worker can no longer safely publish its edition."""


class EditionInputChanged(RuntimeError):
    """Raised when a resumable edition no longer has its frozen evidence inputs."""


def _article_execution_sort_key(article: articles.Article) -> tuple[bool, bool]:
    """Run the long-view specialist before the final daily-brief synthesis."""

    # ``is_summary`` is retained for the older registry contract, but the only
    # true issue synthesis is daily_brief. Horizon Watch is an upstream desk
    # whose output should be available to the final front-page writer.
    return (article.key == "daily_brief", article.is_summary)


def writer_concurrency() -> int:
    """Return the bounded specialist fan-out width for one edition.

    Three concurrent provider calls is the deliberately conservative default:
    it shortens a six-desk run without turning a personal Railway service into
    an unbounded token or rate-limit fan-out.  The upper bound keeps an env
    typo from silently changing the cost model.
    """

    try:
        requested = int(os.environ.get("FRONT_OFFICE_WRITER_CONCURRENCY", "3"))
    except (TypeError, ValueError):
        requested = 3
    return max(1, min(requested, 3))


def max_edition_attempts() -> int:
    """Return the bounded retry budget used by queued newsroom runs."""

    try:
        requested = int(os.environ.get("FRONT_OFFICE_MAX_ATTEMPTS", "2"))
    except (TypeError, ValueError):
        requested = 2
    return max(1, min(requested, 5))


def worker_lease_seconds() -> int:
    """Keep a worker lease longer than the bounded provider timeout."""

    try:
        requested = int(os.environ.get("FRONT_OFFICE_WORKER_LEASE_SECONDS", "900"))
    except (TypeError, ValueError):
        requested = 900
    return max(300, min(requested, 3600))


_SUPPORTED_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


def article_reasoning_effort(article_key: str, default: str = "max") -> str:
    """Resolve an optional per-desk effort override without changing the Luna default.

    Desk-specific effort is deliberately an opt-in cost/latency control. The
    override is part of the article receipt and reuse decision, so changing it
    cannot silently reuse a draft produced under a different provider setting.
    """

    suffix = re.sub(r"[^A-Za-z0-9]+", "_", str(article_key or "").strip()).strip("_").upper()
    override = os.environ.get(
        f"FRONT_OFFICE_LLM_REASONING_EFFORT_{suffix}" if suffix else "",
        "",
    ).strip().lower() if suffix else ""
    fallback = str(default).strip().lower() if default is not None else ""
    if not fallback:
        return ""
    if override in _SUPPORTED_REASONING_EFFORTS:
        return override
    if fallback in _SUPPORTED_REASONING_EFFORTS:
        return fallback
    return "max"


def _provider_cache_key(context: FantasyContext | None, article_key: str, phase: str) -> str:
    """Return a privacy-safe, stable cache bucket for one scoped desk phase."""

    if context is None or getattr(context, "user_id", None) is None or not getattr(context, "league_id", ""):
        return ""
    scope = "|".join(
        (
            str(context.user_id),
            str(context.league_id),
            str(context.season or ""),
            str(context.roster_id or ""),
            str(article_key or ""),
            str(phase or "writer"),
        )
    )
    return "fd:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()[:48]


def _provider_safety_identifier(context: FantasyContext | None) -> str:
    """Return a stable hashed user identifier for provider safety bucketing."""

    if context is None or getattr(context, "user_id", None) is None:
        return ""
    raw = f"fantasy-dominator:user:{context.user_id}"
    return "fd:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def _client_request_id(run_id: str, article_key: str, phase: str) -> str:
    """Return a stable, privacy-safe internal ID for one durable desk phase.

    This is deliberately stored for traceability only.  The provider response
    ID is a separate receipt, and no unsupported idempotency header is sent.
    Retries of the same run/article/phase therefore remain correlated without
    implying that a provider de-duplicated the request.
    """

    if not str(run_id or "").strip():
        return ""
    scope = "|".join((str(run_id), str(article_key or ""), str(phase or "writer")))
    return "fdjob:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()[:48]

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
_CLEAR_AVAILABILITY_LANGUAGE = re.compile(
    r"\b(?:active|available|healthy|no\s+current\s+sleeper\s+injury\s+flag|no\s+injury\s+flag)\b",
    re.IGNORECASE,
)
_ACTION_LANGUAGE = re.compile(
    r"\b(?:buy|sell|start|sit|target|shop|add|drop|stash|trade|move|act|pursue|recommend|hold)\w*\b",
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

# These fields are safe operational metadata. They let a failed or restarted
# daemon retain the useful part of a long newsroom checkpoint without copying
# prose, evidence packets, secrets, tracebacks, or host filesystem paths into
# the reader-facing status response.
_STATUS_CONTEXT_FIELDS = (
    "run_id",
    "started_at",
    "stage",
    "last_stage",
    "league_id",
    "league_name",
    "provider",
    "model",
    "reasoning_effort",
    "editor_mode",
    "timeout_seconds",
    "completed_count",
    "total_count",
    "current_article",
    "current_reporter",
    "articles",
)


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
        "CODEX_EDITORIAL_PACKET_PATH": paths.operator_inbox_dir / "codex_editorial_packet.json",
        "CODEX_EDITORIAL_IMPORT_RECEIPT_PATH": paths.operator_status_dir / "codex_editorial_import.json",
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
            _write_status(
                _base_status("running", f"{name} started.", job=name)
                | {
                    "run_id": uuid.uuid4().hex,
                    "started_at": _now(),
                    "stage": "queued",
                }
            )
            _ACTIVE_JOB = True
    thread = threading.Thread(target=_run_job, args=(name, job, paths), daemon=True)
    thread.start()
    return status(paths) | {"accepted": True}


def begin_edition_run(
    context: FantasyContext | None,
    *,
    operator_run_id: str = "",
    article_keys: set[str] | None = None,
    initial_state: str = "running",
    initial_stage: str = "refreshing",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a durable league edition receipt when an operator run enters the newsroom."""

    if context is None or getattr(context, "user_id", None) is None or not getattr(context, "league_id", ""):
        return ""
    try:
        from app import db as app_db

        requested_keys = (
            sorted(article_keys)
            if article_keys is not None
            else [article.key for article in articles.ARTICLES]
        )
        receipt = app_db.start_edition_run(
            int(context.user_id),
            context.league_id,
            getattr(context, "season", ""),
            roster_id=getattr(context, "roster_id", None),
            operator_run_id=operator_run_id,
            article_keys=requested_keys,
            metadata={
                "requested_mode": "targeted" if article_keys is not None else "full_edition",
                "article_contract": "article_contract_v2",
                "editor_mode": editorial_review_mode(),
                **(metadata or {}),
            },
            initial_state=initial_state,
            initial_stage=initial_stage,
            max_attempts=max_edition_attempts(),
        )
        return str(receipt.get("run_id") or "")
    except Exception:  # noqa: BLE001 - optional ledger failure must not erase a good run.
        # The JSON operator receipt remains the compatibility fallback. A
        # missing optional ledger must never erase a successful article run.
        return ""


def _edition_run_checkpoint(
    run_id: str,
    *,
    stage: str | None = None,
    state: str | None = None,
    completed_count: int | None = None,
    total_count: int | None = None,
    complete: bool = False,
    failure_class: str = "",
    failure_message: str = "",
    worker_id: str = "",
) -> None:
    if not run_id:
        return
    try:
        from app import db as app_db

        app_db.update_edition_run(
            run_id,
            stage=stage,
            state=state,
            completed_count=completed_count,
            total_count=total_count,
            complete=complete,
            failure_class=failure_class or None,
            failure_message=failure_message or None,
            worker_id=worker_id or None,
        )
    except Exception:  # noqa: BLE001 - optional ledger failure must not erase a good run.
        return


def _edition_run_heartbeat(run_id: str, worker_id: str) -> bool:
    """Renew a worker lease and report whether ownership is still valid."""

    if not run_id or not worker_id:
        return True
    try:
        from app import db as app_db

        app_db.heartbeat_newsroom_worker(worker_id, state="working", run_id=run_id)
        return bool(app_db.heartbeat_edition_run(run_id, worker_id, lease_seconds=worker_lease_seconds()))
    except Exception:  # noqa: BLE001 - the caller will fail closed on the next checkpoint.
        return False


def _edition_run_cancelled(run_id: str) -> bool:
    if not run_id:
        return False
    try:
        from app import db as app_db

        return app_db.edition_run_cancel_requested(run_id)
    except Exception:  # noqa: BLE001 - optional ledger failure cannot invent cancellation.
        return False


EDITION_PACKET_SCHEMA_VERSION = "edition_packet_v1"
_EDITION_PACKET_PROCESSED_FILES = (
    "refresh_metadata.csv",
    "source_freshness.csv",
    "news_source_freshness.csv",
    "projection_source_freshness.csv",
    "roster_players.csv",
    "teams.csv",
    "matchups.csv",
    "trades.csv",
    "waivers.csv",
    "player_dossiers.csv",
    "player_horizon_market_scores.csv",
    "available_player_horizon_scores.csv",
    "player_signal_scores.csv",
    "horizon_market_movements.csv",
    "horizon_score_accuracy.csv",
    "manager_profiles.csv",
    "manager_behavior_signals.csv",
    "team_asset_inventory.csv",
    "news_events.csv",
    "league_news_impact.csv",
    "nfl_schedule.csv",
)
_EDITION_PACKET_ANALYSIS_FILES = (
    "reality_check.json",
    "target_theses.json",
    "sell_theses.json",
    "trade_theses.json",
    "manager_dossiers.json",
    "player_dossiers.json",
    "horizon_market_movements.csv",
)


def _edition_packet_path(run_id: str) -> Path:
    """Return a run-scoped packet path without accepting path fragments."""

    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(run_id or "").strip())
    if not safe_id:
        raise ValueError("edition run ID is required for a frozen packet")
    return ANALYSIS_DIR / "edition_runs" / f"{safe_id}.json"


def _packet_file_receipt(root: Path, filenames: Iterable[str]) -> list[dict[str, Any]]:
    """Hash only bounded, named inputs; never expose host paths in a receipt."""

    receipts: list[dict[str, Any]] = []
    for filename in filenames:
        path = root / filename
        if not path.is_file():
            receipts.append({"file": filename, "status": "missing", "sha256": "", "size": 0})
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            receipts.append({"file": filename, "status": "unreadable", "sha256": "", "size": 0})
            continue
        receipts.append(
            {
                "file": filename,
                "status": "present",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    return receipts


def _packet_csv_receipt(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """Keep source freshness in the packet while dropping arbitrary row payloads."""

    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [
                {field: str(row.get(field) or "").strip() for field in fields}
                for row in csv.DictReader(handle)
            ]
    except (OSError, csv.Error, UnicodeError):
        return []


def _edition_packet_payload(
    ctx: FantasyContext,
    run_id: str,
    article_keys: Iterable[str],
    reality_check_packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the immutable receipt for the exact deterministic inputs of a run."""

    refresh_rows = _packet_csv_receipt(
        PROCESSED_DIR / "refresh_metadata.csv",
        (
            "generated_at",
            "current_season",
            "refresh_mode",
            "requested_week_end",
            "historical_refresh_scope",
            "league_id",
            "roster_id",
        ),
    )
    source_rows: list[dict[str, str]] = []
    for filename, fields in (
        (
            "source_freshness.csv",
            ("source", "dataset", "status", "row_count", "checked_at", "generated_at"),
        ),
        (
            "news_source_freshness.csv",
            ("source", "dataset", "status", "row_count", "checked_at", "generated_at"),
        ),
        (
            "projection_source_freshness.csv",
            ("source", "dataset", "status", "row_count", "checked_at", "generated_at"),
        ),
    ):
        for row in _packet_csv_receipt(PROCESSED_DIR / filename, fields):
            source_rows.append({"file": filename, **row})
    source_rows.sort(key=lambda row: json.dumps(row, sort_keys=True))
    reality_summary = {
        key: reality_check_packet.get(key)
        for key in (
            "schema_version",
            "status",
            "fingerprint",
            "generated_at",
            "roster_rows_checked",
            "actionable_player_rows_checked",
            "severity_counts",
        )
        if reality_check_packet.get(key) not in (None, "", [], {})
    }
    packet = {
        "artifact_type": "edition_packet",
        "schema_version": EDITION_PACKET_SCHEMA_VERSION,
        "run_id": str(run_id),
        "created_at": _now(),
        "scope": {
            "user_id": str(ctx.user_id or ""),
            "league_id": str(ctx.league_id or ""),
            "season": str(ctx.season or ""),
            "roster_id": ctx.roster_id,
            "team_name": str(ctx.team_name or ""),
        },
        "requested_article_keys": sorted({str(key).strip() for key in article_keys if str(key).strip()}),
        "refresh_receipt": refresh_rows[0] if refresh_rows else {},
        "source_freshness": source_rows,
        "input_files": {
            "processed": _packet_file_receipt(PROCESSED_DIR, _EDITION_PACKET_PROCESSED_FILES),
            "analysis": _packet_file_receipt(ANALYSIS_DIR, _EDITION_PACKET_ANALYSIS_FILES),
        },
        "reality_check": reality_summary,
    }
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    packet["edition_fingerprint"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    packet["source_receipt"] = {
        "scope": "selected_league_immutable_edition_packet",
        "artifact": f"analysis/edition_runs/{re.sub(r'[^A-Za-z0-9_-]', '', str(run_id))}.json",
        "refresh": packet["refresh_receipt"],
        "source_freshness": packet["source_freshness"],
        "reality_check": packet["reality_check"],
        "input_file_count": sum(
            len(value)
            for value in packet["input_files"].values()
            if isinstance(value, list)
        ),
    }
    return packet


def _edition_packet_fingerprint(packet: Mapping[str, Any]) -> str:
    """Recompute the immutable packet hash without trusting its stored hash."""

    immutable = {
        key: packet.get(key)
        for key in (
            "artifact_type",
            "schema_version",
            "run_id",
            "created_at",
            "scope",
            "requested_article_keys",
            "refresh_receipt",
            "source_freshness",
            "input_files",
            "reality_check",
        )
    }
    encoded = json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _edition_packet_matches_current(packet: Mapping[str, Any]) -> bool:
    """Compare the frozen packet's named file hashes with the current workspace."""

    if str(packet.get("edition_fingerprint") or "") != _edition_packet_fingerprint(packet):
        return False

    scope = packet.get("scope") if isinstance(packet.get("scope"), Mapping) else {}
    current = {
        "artifact_type": "edition_packet",
        "schema_version": EDITION_PACKET_SCHEMA_VERSION,
        "run_id": str(packet.get("run_id") or ""),
        "created_at": packet.get("created_at") or "",
        "scope": dict(scope),
        "requested_article_keys": packet.get("requested_article_keys") or [],
        "refresh_receipt": packet.get("refresh_receipt") or {},
        "source_freshness": packet.get("source_freshness") or [],
        "input_files": {
            "processed": _packet_file_receipt(PROCESSED_DIR, _EDITION_PACKET_PROCESSED_FILES),
            "analysis": _packet_file_receipt(ANALYSIS_DIR, _EDITION_PACKET_ANALYSIS_FILES),
        },
        "reality_check": packet.get("reality_check") or {},
    }
    # File receipts are the immutable part; generated_at is deliberately not
    # reconstructed because it describes when the packet was frozen.
    frozen_inputs = packet.get("input_files") if isinstance(packet.get("input_files"), Mapping) else {}
    return current["input_files"] == frozen_inputs


def _freeze_edition_packet(
    ctx: FantasyContext | None,
    run_id: str,
    article_keys: Iterable[str],
    reality_check_packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Create once, then verify; never silently replace a run's evidence packet."""

    if ctx is None or ctx.user_id is None or not run_id:
        return {}
    path = _edition_packet_path(run_id)
    existing = _safe_json(path)
    if existing:
        if str(existing.get("schema_version") or "") != EDITION_PACKET_SCHEMA_VERSION:
            raise EditionInputChanged("The edition packet schema is older than this writer run.")
        expected_scope = {
            "user_id": str(ctx.user_id or ""),
            "league_id": str(ctx.league_id or ""),
            "season": str(ctx.season or ""),
            "roster_id": ctx.roster_id,
            "team_name": str(ctx.team_name or ""),
        }
        if existing.get("scope") != expected_scope:
            raise EditionInputChanged("The edition packet identity no longer matches this selected league.")
        expected_keys = sorted({str(key).strip() for key in article_keys if str(key).strip()})
        if list(existing.get("requested_article_keys") or []) != expected_keys:
            raise EditionInputChanged("The edition packet article scope no longer matches this run.")
        if not _edition_packet_matches_current(existing):
            raise EditionInputChanged("The deterministic inputs changed after this edition was frozen.")
        try:
            _write_json(ANALYSIS_DIR / "edition_packet.json", existing)
        except OSError:
            pass
        return existing
    packet = _edition_packet_payload(ctx, run_id, article_keys, reality_check_packet)
    _write_json(path, packet)
    # This pointer is reader convenience only.  The run-scoped file above is
    # immutable; replacing this latest-edition pointer must never rewrite a
    # historical packet or change the run's fingerprint.
    try:
        _write_json(ANALYSIS_DIR / "edition_packet.json", packet)
    except OSError:
        pass
    return packet


def _record_edition_packet(run_id: str, packet: Mapping[str, Any]) -> None:
    if not run_id or not isinstance(packet, Mapping):
        return
    try:
        from app import db as app_db

        source_receipt = dict(packet.get("source_receipt") or {}) if isinstance(packet.get("source_receipt"), Mapping) else {}
        source_receipt["edition_fingerprint"] = str(packet.get("edition_fingerprint") or "")
        existing = app_db.get_edition_run(run_id) or {}
        metadata = dict(existing.get("metadata") or {}) if isinstance(existing.get("metadata"), Mapping) else {}
        metadata["edition_packet_schema"] = EDITION_PACKET_SCHEMA_VERSION
        app_db.update_edition_run(
            run_id,
            edition_fingerprint=str(packet.get("edition_fingerprint") or ""),
            source_receipt=source_receipt,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - the file packet remains the source receipt fallback.
        return


def write_edition_execution_receipt(run_id: str) -> dict[str, Any]:
    """Persist safe run/job telemetry separately from the immutable input packet.

    The edition packet proves what evidence was frozen.  This receipt proves
    what happened while the jobs ran.  Keeping them separate prevents a
    mutable progress update from changing the input fingerprint while still
    making slow calls, retries, holds, and publication states inspectable.
    """

    if not run_id:
        return {}
    try:
        from app import db as app_db

        run = app_db.get_edition_run(str(run_id)) or {}
    except Exception:  # noqa: BLE001 - the operator status remains the fallback.
        return {}
    jobs: list[dict[str, Any]] = []
    for raw in run.get("jobs") if isinstance(run.get("jobs"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), Mapping) else {}
        usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
        duration_ms = metadata.get("elapsed_ms")
        if duration_ms in (None, "") and raw.get("started_at") and raw.get("completed_at"):
            try:
                started = datetime.fromisoformat(str(raw["started_at"]).replace("Z", "+00:00"))
                completed = datetime.fromisoformat(str(raw["completed_at"]).replace("Z", "+00:00"))
                duration_ms = max(0, round((completed - started).total_seconds() * 1000))
            except (TypeError, ValueError, OverflowError):
                duration_ms = None
        job = {
            "job_id": raw.get("id"),
            "article_key": str(raw.get("article_key") or ""),
            "phase": str(raw.get("phase") or "writer"),
            "state": str(raw.get("state") or ""),
            "attempt": int(raw.get("attempt") or 0),
            "started_at": raw.get("started_at") or "",
            "completed_at": raw.get("completed_at") or "",
            "evidence_fingerprint": str(raw.get("evidence_fingerprint") or ""),
            "prompt_version": str(raw.get("prompt_version") or ""),
            "provider": str(raw.get("provider") or ""),
            "model": str(raw.get("model") or ""),
            "reasoning_effort": str(raw.get("reasoning_effort") or ""),
            "client_request_id": str(raw.get("client_request_id") or ""),
            "provider_request_id": str(raw.get("provider_request_id") or ""),
            "usage": dict(usage),
            "cached_tokens": _safe_nonnegative_int(metadata.get("cached_tokens")),
            "prompt_cache_key_present": bool(str(metadata.get("prompt_cache_key") or "").strip()),
            "duration_ms": duration_ms,
            "processing_ms": metadata.get("processing_ms"),
            "error_class": str(raw.get("error_class") or ""),
            "error_message": str(raw.get("error_message") or ""),
        }
        jobs.append(job)
    receipt = {
        "artifact_type": "edition_execution_receipt",
        "schema_version": EDITION_EXECUTION_RECEIPT_SCHEMA_VERSION,
        "run_id": str(run_id),
        "generated_at": _now(),
        "state": str(run.get("state") or "unknown"),
        "stage": str(run.get("stage") or "unknown"),
        "scope": {
            "user_id": str(run.get("user_id") or ""),
            "league_id": str(run.get("league_id") or ""),
            "season": str(run.get("season") or ""),
            "roster_id": run.get("roster_id"),
        },
        "edition_fingerprint": str(run.get("edition_fingerprint") or ""),
        "jobs": jobs,
    }
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(run_id).strip())
    if not safe_id:
        return receipt
    try:
        _write_json(ANALYSIS_DIR / "edition_runs" / f"{safe_id}.receipt.json", receipt)
        _write_json(ANALYSIS_DIR / "edition_receipt.json", receipt)
    except OSError:
        return receipt
    return receipt


def _edition_packet_result(packet: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a safe packet receipt for operator status and article results."""

    if not isinstance(packet, Mapping) or not packet:
        return {"status": "not_recorded", "schema_version": EDITION_PACKET_SCHEMA_VERSION}
    source_receipt = packet.get("source_receipt") if isinstance(packet.get("source_receipt"), Mapping) else {}
    return {
        "status": "frozen",
        "schema_version": str(packet.get("schema_version") or EDITION_PACKET_SCHEMA_VERSION),
        "run_id": str(packet.get("run_id") or ""),
        "edition_fingerprint": str(packet.get("edition_fingerprint") or ""),
        "scope": packet.get("scope") if isinstance(packet.get("scope"), Mapping) else {},
        "requested_article_keys": list(packet.get("requested_article_keys") or []),
        "source_receipt": dict(source_receipt),
    }


def _close_cancelled_edition(run_id: str, worker_id: str = "") -> None:
    if not run_id:
        return
    try:
        from app import db as app_db

        app_db.cancel_edition_run(run_id, worker_id=worker_id or None)
        write_edition_execution_receipt(run_id)
    except Exception:  # noqa: BLE001 - cancellation remains visible in the caller's status receipt.
        return


def _edition_job_start(
    run_id: str,
    article_key: str,
    *,
    phase: str,
    provider: str,
    model: str,
    reasoning_effort: str,
    evidence_fingerprint: str = "",
    worker_id: str = "",
) -> dict[str, Any] | None:
    if not run_id:
        return {"state": "running"}
    try:
        from app import db as app_db

        if worker_id:
            return app_db.claim_edition_job(
                run_id,
                article_key,
                worker_id,
                phase=phase,
                evidence_fingerprint=evidence_fingerprint,
                prompt_version="article_contract_v2",
                provider=provider,
                model=model,
                reasoning_effort=reasoning_effort,
                client_request_id=_client_request_id(run_id, article_key, phase),
                lease_seconds=worker_lease_seconds(),
            )
        return app_db.start_edition_job(
            run_id,
            article_key,
            phase=phase,
            evidence_fingerprint=evidence_fingerprint,
            prompt_version="article_contract_v2",
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            client_request_id=_client_request_id(run_id, article_key, phase),
        )
    except Exception:  # noqa: BLE001 - optional ledger failure must not erase a good run.
        return None


def _edition_job_finish(
    run_id: str,
    article_key: str,
    *,
    phase: str,
    state: str,
    provider_receipt: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    error: Exception | None = None,
    worker_id: str = "",
) -> None:
    if not run_id:
        return
    receipt = provider_receipt if isinstance(provider_receipt, dict) else {}
    usage = receipt.get("usage") if isinstance(receipt.get("usage"), dict) else {}
    try:
        from app import db as app_db

        app_db.finish_edition_job(
            run_id,
            article_key,
            phase=phase,
            state=state,
            provider_request_id=str(receipt.get("request_id") or ""),
            usage=usage,
            metadata={
                **(metadata or {}),
                "attempts": receipt.get("attempts"),
                "elapsed_ms": receipt.get("elapsed_ms"),
                "processing_ms": receipt.get("processing_ms"),
                "cached_tokens": receipt.get("cached_tokens", 0),
                "prompt_cache_key": str(receipt.get("prompt_cache_key") or ""),
                "reasoning_effort": str(receipt.get("reasoning_effort") or ""),
            },
            error_class=type(error).__name__ if error else "",
            error_message=(f"{type(error).__name__} during the {phase} phase." if error else ""),
            worker_id=worker_id or None,
        )
    except Exception:  # noqa: BLE001 - optional ledger failure must not erase a good run.
        return


def edition_resume_article_keys(
    edition_run: Mapping[str, Any] | None,
    available_article_keys: Iterable[str] | None = None,
) -> set[str]:
    """Return only article desks that still need work on an interrupted run.

    A completed writer receipt is deliberately excluded even if the operator
    JSON status was lost.  That is the important idempotency boundary: a resume
    request may re-enter the workflow, but it cannot spend another provider call
    for a desk whose durable receipt already reached a terminal success state.
    """

    if not isinstance(edition_run, Mapping):
        return set()
    requested = edition_run.get("requested_article_keys")
    keys = {
        str(value).strip()
        for value in (requested if isinstance(requested, list) else (available_article_keys or ()))
        if str(value).strip()
    }
    if not keys:
        keys = {article.key for article in articles.ARTICLES}
    jobs = edition_run.get("jobs") if isinstance(edition_run.get("jobs"), list) else []
    by_phase: dict[tuple[str, str], Mapping[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        key = str(job.get("article_key") or "").strip()
        phase = str(job.get("phase") or "writer").strip().lower()
        if key:
            by_phase[(key, phase)] = job
    writer_success = {"published", "reused", "skipped"}
    editor_failure = {"failed", "interrupted", "running"}
    metadata = edition_run.get("metadata")
    editor_required = (
        isinstance(metadata, Mapping)
        and str(metadata.get("editor_mode") or "").strip().lower() == "llm"
    )
    retry: set[str] = set()
    for key in keys:
        writer = by_phase.get((key, "writer"), {})
        editor = by_phase.get((key, "editor"), {})
        writer_state = str(writer.get("state") or "").strip().lower()
        editor_state = str(editor.get("state") or "").strip().lower()
        if writer_state not in writer_success or editor_state in editor_failure or (editor_required and editor_state != "reviewed"):
            retry.add(key)
    return retry


def write_job_progress(
    *,
    stage: str,
    message: str,
    league_id: str = "",
    league_name: str = "",
) -> dict[str, Any]:
    """Persist a safe stage checkpoint for the currently running job.

    The helper is intentionally a no-op unless the durable receipt already
    says that a job is running. This keeps direct/unit-test calls from
    creating a phantom run while ensuring refresh, writing, and publication
    stages survive a slow provider call or a process restart.
    """

    current = _safe_json(STATUS_PATH)
    if not current or current.get("state") != "running":
        return current
    payload = dict(current)
    payload.update(
        {
            "state": "running",
            "stage": str(stage or "working"),
            "message": str(message or "Operator work is in progress."),
            "updated_at": _now(),
        }
    )
    if league_id:
        payload["league_id"] = str(league_id)
    if league_name:
        payload["league_name"] = str(league_name)
    _write_status(payload)
    return payload


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
            "claim_positions": {
                "type": "array",
                "description": "Structured positions that let the editor compare the same subject and decision window across desks.",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject_key": {"type": "string", "description": "Stable entity key copied from the evidence, such as a player_id or manager roster_id."},
                        "subject_label": {"type": "string", "description": "Human-readable subject label from the evidence."},
                        "decision_window": {"type": "string", "enum": ["next_game", "rest_of_season", "dynasty", "career_window", "multi_window", "availability", "market", "manager", "other"], "description": "Decision window or question being addressed."},
                        "stance": {"type": "string", "enum": ["positive", "negative", "conditional", "mixed", "unknown"], "description": "The bounded position, not certainty about an outcome."},
                        "summary": {"type": "string", "description": "One short sentence describing the position without adding facts."},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}, "description": "Exact evidence IDs supporting this position."},
                    },
                },
            },
            "related_entities": {"type": "array", "items": {"type": "string"}, "description": "Evidence-backed player, team, manager, or pick identifiers/names."},
            "visual_brief": {"type": "string", "description": "Optional non-factual art direction; never put stats or claims in an image."},
            "room_move": {
                "type": "string",
                "enum": ["supports", "disputes", "extends", "asks", "supersedes", "held_because", ""],
                "description": "Optional editorial relationship to the prior desk; use extends when the desk adds a new lens without claiming factual disagreement.",
            },
            "reply_to": {"type": "string", "description": "Optional prior article key this desk is responding to; copy only a key named in the room context."},
            "room_question": {"type": "string", "description": "Optional reader-facing question this desk adds to the running conversation."},
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
            "action", "risk", "confidence", "claim_positions", "related_entities", "visual_brief",
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
        "the evidence packet, the evidence packet wins, and do not cite room context as factual support. "
        "An evidence item marked editorial_only is the same kind of room context even when it appears inside the "
        "evidence array: it has no claim candidates and must never be upgraded into a source-backed fact. "
        "When a peer note is present, use room_move, reply_to, and room_question to make the relationship explicit: "
        "use extends for a new lens, disputes only when the supplied evidence supports a real counter-signal, and asks "
        "when the next desk should investigate an open question. These fields describe editorial structure, not facts. "
        "If an evidence item contains a reality_check receipt, inherit its limitation in the local sentence: do not "
        "turn a high-severity no-team, injury, or availability-conditioned row into a current action without stating "
        "the condition or that the signal is unavailable. For each material position, emit a bounded claim_positions "
        "entry with the exact subject_key copied from the evidence (usually player_id, roster_id, or entity_id), "
        "a decision_window, stance, short summary, and the exact cited evidence_ids. Use an empty array when the "
        "packet does not support a structured position; never invent a subject key. This register is used to compare "
        "the same question across desks, so keep one entry per subject and window rather than restating prose."
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
        structured = _article_front_matter_json(output_path, "article_payload_json")
        room.append(
            {
                "kind": "previous_edition",
                "desk": article.key,
                "reporter": reporter["name"],
                "excerpt": _editorial_excerpt(previous),
                "structured": _room_structured_context(structured),
            }
        )
    article_titles = {item.key: item.title for item in articles.ARTICLES}
    article_registry = {item.key: item for item in articles.ARTICLES}
    current_peer_keys = set(ctx.section_outputs)
    for key, narrative in ctx.section_outputs.items():
        if key == article.key or not str(narrative or "").strip():
            continue
        reporter = persona_metadata(ctx.writer_preferences, key)
        peer_article = article_registry.get(key)
        peer_path = ctx.analysis_dir / peer_article.output_filename if peer_article else Path()
        structured = _article_front_matter_json(peer_path, "article_payload_json") if peer_article else {}
        room.append(
            {
                "kind": "peer_edition",
                "desk": key,
                "reporter": reporter["name"],
                "title": article_titles.get(key, key),
                "excerpt": _editorial_excerpt(narrative),
                "structured": _room_structured_context(structured),
            }
        )
    for key, narrative in ctx.prior_section_outputs.items():
        if key == article.key or key in current_peer_keys or not str(narrative or "").strip():
            continue
        reporter = persona_metadata(ctx.writer_preferences, key)
        peer_article = article_registry.get(key)
        peer_path = ctx.analysis_dir / peer_article.output_filename if peer_article else Path()
        structured = _article_front_matter_json(peer_path, "article_payload_json") if peer_article else {}
        room.append(
            {
                "kind": "previous_peer_edition",
                "desk": key,
                "reporter": reporter["name"],
                "title": article_titles.get(key, key),
                "excerpt": _editorial_excerpt(narrative),
                "structured": _room_structured_context(structured),
            }
        )
    return room[:5]


def _seed_prior_specialist_context(
    ctx: articles.ArticleContext,
    requested_article_keys: set[str] | None = None,
) -> None:
    """Make the last specialist edition available as bounded peer context.

    Fan-out deliberately starts independent specialist calls before the new
    room has prose. Seeding the prior edition gives those calls continuity
    without serializing the paid work or treating old copy as evidence. The
    current run's summary desks are excluded so the daily brief remains a
    synthesis of specialist work rather than a peer source for it.
    """

    requested = {str(key) for key in (requested_article_keys or set())}
    for article in sorted(articles.ARTICLES, key=_article_execution_sort_key):
        if article.is_summary or article.key in requested or article.key in ctx.section_outputs or article.key in ctx.prior_section_outputs:
            continue
        existing_narrative = _article_narrative_from_file(ctx.analysis_dir / article.output_filename)
        if existing_narrative:
            ctx.prior_section_outputs[article.key] = existing_narrative


def _editorial_excerpt(value: Any, limit: int = 900) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _article_front_matter_json(path: Path, field: str) -> dict[str, Any]:
    """Read one bounded JSON receipt from an article without treating prose as data."""

    if not path or not path.exists():
        return {}
    prefix = f"{field}:"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith(prefix):
                continue
            value = json.loads(line.split(":", 1)[1].strip())
            return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return {}


def _room_structured_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep peer context useful while making its non-evidence status obvious."""

    if not isinstance(value, Mapping):
        return {}
    raw_claim_positions = value.get("claim_positions") if isinstance(value.get("claim_positions"), list) else []
    claim_positions = []
    for item in raw_claim_positions[:8]:
        if not isinstance(item, Mapping):
            continue
        claim_positions.append(
            {
                "subject_key": str(item.get("subject_key") or "").strip(),
                "subject_label": _editorial_excerpt(item.get("subject_label"), 80),
                "decision_window": str(item.get("decision_window") or "").strip().lower(),
                "stance": str(item.get("stance") or "").strip().lower(),
                "summary": _editorial_excerpt(item.get("summary"), 180),
                "evidence_ids": [str(value).strip() for value in (item.get("evidence_ids") or []) if str(value).strip()][:8],
            }
        )
    return {
        "editorial_only": True,
        "headline": str(value.get("headline") or ""),
        "thesis": _editorial_excerpt(value.get("thesis"), 280),
        "counter_evidence": _editorial_excerpt(value.get("counter_evidence"), 280),
        "room_move": str(value.get("room_move") or "").strip().lower(),
        "room_question": _editorial_excerpt(value.get("room_question"), 180),
        "claim_positions": claim_positions,
        "evidence_count": len(value.get("evidence_ids") or []) if isinstance(value.get("evidence_ids"), list) else 0,
    }


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
        raw_injury_status = str(packet.get("injury_status") or "").strip().lower()
        clear_injury_statuses = {"", "active", "available", "healthy", "no injury flag", "no current sleeper injury flag"}
        injury_flag = raw_injury_status not in clear_injury_statuses
        if not injury_flag:
            injury_flag = bool(
                re.search(r"\b(?:questionable|out|injured|injury|ir|pup)\b", status, re.IGNORECASE)
                and not _CLEAR_AVAILABILITY_LANGUAGE.search(status)
            )
        name_pattern = re.compile(rf"(?<!\w){re.escape(player_name)}(?!\w)", re.IGNORECASE)
        mentioned_indexes = [index for index, sentence in enumerate(sentences) if name_pattern.search(sentence)]
        if not mentioned_indexes:
            continue

        for index in mentioned_indexes:
            context = " ".join(sentences[max(0, index - 1): min(len(sentences), index + 2)])
            # A player's display name is evidence identity, not caveat
            # language. Remove it before checking for words such as
            # "conditional" or "out" so a name like "Conditional Veteran"
            # cannot accidentally launder an unsupported claim.
            claim_context = name_pattern.sub("", context)
            if no_current_team and _PROJECTION_LANGUAGE.search(context):
                no_team_claims_reviewed += 1
                if not (
                    _CONDITIONAL_AVAILABILITY_LANGUAGE.search(claim_context)
                    or _EXPLICIT_UNAVAILABLE_LANGUAGE.search(claim_context)
                ):
                    errors.append(
                        f"{player_name} is unavailable with no current NFL team; projection/PPG language must be conditional or explicitly unavailable."
                    )
                    break
            if injury_flag and re.search(r"\brest[- ]of[- ]season\b", context, re.IGNORECASE) and _PROJECTION_LANGUAGE.search(context):
                if not _RECOVERY_CAVEAT_LANGUAGE.search(claim_context):
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


def _reality_check_boundaries(
    narrative: str,
    structured: Mapping[str, Any] | None,
    evidence_packets: list[dict[str, Any]] | None,
    reality_check_packet: Mapping[str, Any] | None,
    *,
    article_key: str = "",
) -> dict[str, Any]:
    """Bind deterministic limitation checks to the article publication seam.

    Reality Check is broader than a roster warning: market, waiver, horizon,
    and trade packets can contain players who are not on the selected roster.
    A matched high-severity check therefore holds a story only when the story
    turns that player into an actionable or projection claim without a local
    caveat. A purely descriptive mention remains printable, but its receipt
    tells the reader that action should wait for verification.
    """

    packet = reality_check_packet if isinstance(reality_check_packet, Mapping) else {}
    checks = [check for check in (packet.get("checks") or []) if isinstance(check, Mapping)]
    if not checks:
        return {
            "status": "unavailable",
            "publication_gate": "not_run",
            "matched_checks": [],
            "high_checks_matched": 0,
            "errors": [],
            "warnings": ["No Reality Check packet was available for this article run."],
        }

    evidence_entities: set[str] = set()
    evidence_names: set[str] = set()
    for evidence in evidence_packets or []:
        if not isinstance(evidence, Mapping):
            continue
        entity_id = str(evidence.get("entity_id") or "").strip()
        if entity_id:
            evidence_entities.add(entity_id)
        for key in ("player_name", "name"):
            normalized = _normalize_reality_name(evidence.get(key))
            if normalized:
                evidence_names.add(normalized)

    matched: list[dict[str, Any]] = []
    for check in checks:
        entity_id = str(check.get("entity_id") or "").strip()
        entity_name = str(check.get("entity_name") or "").strip()
        if (
            not entity_id
            or entity_id not in evidence_entities
        ) and (
            not entity_name
            or _normalize_reality_name(entity_name) not in evidence_names
        ):
            continue
        matched.append(
            {
                "check_id": str(check.get("check_id") or ""),
                "severity": str(check.get("severity") or "medium").lower(),
                "entity_id": entity_id,
                "entity_name": entity_name,
                "title": str(check.get("title") or "Reality Check limitation"),
                "detail": str(check.get("detail") or "Verify the source receipt before acting."),
                "scope": str(check.get("scope") or "selected_roster"),
                "evidence_ids": [str(value) for value in (check.get("evidence_ids") or []) if str(value).strip()],
            }
        )

    if not matched:
        return {
            "status": "clear",
            "publication_gate": "clear",
            "matched_checks": [],
            "high_checks_matched": 0,
            "errors": [],
            "warnings": [],
        }

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", str(narrative or ""))
        if part.strip()
    ]
    structured_action = str((structured or {}).get("action") or "")
    errors: list[str] = []
    warnings: list[str] = []
    high_count = 0
    action_desks = {"team_report", "market_watch", "horizon_watch", "trade_desk", "daily_brief"}
    for check in matched:
        severity = check["severity"]
        if severity == "high":
            high_count += 1
        name = check["entity_name"]
        name_pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE) if name else None
        contexts = [
            " ".join(sentences[max(0, index - 1): min(len(sentences), index + 2)])
            for index, sentence in enumerate(sentences)
            if name_pattern and name_pattern.search(sentence)
        ]
        context = " ".join(contexts)
        action_context = context or structured_action
        projection_or_action = bool(
            _PROJECTION_LANGUAGE.search(action_context)
            or (article_key in action_desks and _ACTION_LANGUAGE.search(action_context))
        )
        caveated = bool(
            _CONDITIONAL_AVAILABILITY_LANGUAGE.search(context)
            or _EXPLICIT_UNAVAILABLE_LANGUAGE.search(context)
            or _RECOVERY_CAVEAT_LANGUAGE.search(context)
        )
        if severity == "high" and projection_or_action and not caveated:
            errors.append(
                f"{name} has a high-severity Reality Check limitation ({check['title']}); the article must make the signal conditional or explicitly unavailable before presenting an action."
            )
        elif severity in {"high", "medium"}:
            warnings.append(
                f"{name} carries a Reality Check limitation ({check['title']}); verify the receipt before acting."
            )

    return {
        "status": "held" if errors else "warning",
        "publication_gate": "hold" if errors else "warning",
        "matched_checks": matched,
        "high_checks_matched": high_count,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _normalize_reality_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _attach_reality_check_receipts(
    evidence_packets: list[dict[str, Any]],
    reality_check_packet: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Give each writer the matched limitation receipt beside its evidence row."""

    matches = _reality_check_boundaries(
        "",
        {},
        evidence_packets,
        reality_check_packet,
    ).get("matched_checks") or []
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for check in matches:
        if check.get("entity_id"):
            by_id.setdefault(str(check["entity_id"]), []).append(dict(check))
        normalized_name = _normalize_reality_name(check.get("entity_name"))
        if normalized_name:
            by_name.setdefault(normalized_name, []).append(dict(check))

    output: list[dict[str, Any]] = []
    for evidence in evidence_packets:
        item = dict(evidence)
        receipts = list(by_id.get(str(item.get("entity_id") or ""), []))
        name = _normalize_reality_name(item.get("player_name") or item.get("name"))
        for check in by_name.get(name, []):
            if check not in receipts:
                receipts.append(check)
        if receipts:
            item["reality_check"] = receipts
            permitted = list(item.get("permitted_interpretation") or [])
            permitted.append("Honor the matched Reality Check receipt before presenting this entity as an action.")
            item["permitted_interpretation"] = list(dict.fromkeys(permitted))
        output.append(item)
    return output


def generate_article_via_llm(
    system_prompt: str,
    evidence: list[dict[str, Any]],
    api_key: str,
    model: str,
    editorial_context: list[dict[str, Any]] | None = None,
    reasoning_effort: str | None = None,
    prompt_cache_key: str | None = None,
    safety_identifier: str | None = None,
) -> dict[str, Any]:
    """Focused single-article call through the provider-neutral structured adapter."""
    return call_structured_tool(
        system_prompt=system_prompt,
        evidence=evidence,
        api_key=api_key,
        model=model,
        tool=ARTICLE_TOOL,
        editorial_context=editorial_context,
        reasoning_effort=reasoning_effort,
        prompt_cache_key=prompt_cache_key,
        safety_identifier=safety_identifier,
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
            "Any reality_check receipt attached to an evidence item is a binding limitation from the deterministic verification packet. Preserve its caveat or hold the article; do not upgrade a limited row into a current action.",
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
    reasoning_effort: str | None = None,
    prompt_cache_key: str | None = None,
    safety_identifier: str | None = None,
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
        reasoning_effort=reasoning_effort,
        prompt_cache_key=prompt_cache_key,
        safety_identifier=safety_identifier,
        request_post=requests.post,
    )


def _editor_review_result(
    article: articles.Article,
    writer_output: dict[str, Any],
    writer_validation: dict[str, Any],
    editor_output: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
    model: str,
    reality_check_packet: Mapping[str, Any] | None = None,
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
        reality_check_packet=reality_check_packet,
        article_key=article.key,
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
        "reality_check": candidate_validation.get("reality_check") or {},
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
    *,
    reality_check_packet: Mapping[str, Any] | None = None,
    article_key: str = "",
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
    room_move = str(output.get("room_move") or "").strip().lower() if isinstance(output, dict) else ""
    if room_move and room_move not in {"supports", "disputes", "extends", "asks", "supersedes", "held_because"}:
        errors.append(f"Article room_move is not a supported relationship: {room_move}")
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
    claim_position_checks = _validate_claim_positions(
        structured.get("claim_positions") or [],
        evidence_ids,
        cited,
        evidence_packets,
    )
    errors.extend(claim_position_checks["errors"])
    warnings.extend(claim_position_checks["warnings"])
    reality_checks = _reality_check_boundaries(
        narrative,
        structured,
        evidence_packets,
        reality_check_packet,
        article_key=article_key,
    )
    errors.extend(reality_checks["errors"])
    warnings.extend(reality_checks["warnings"])

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "boundary_checks": boundary_checks,
        "claim_position_checks": claim_position_checks,
        "reality_check": reality_checks,
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
    claim_positions: list[dict[str, Any]] = []
    raw_claim_positions = output.get("claim_positions")
    if isinstance(raw_claim_positions, list):
        for item in raw_claim_positions:
            if not isinstance(item, Mapping):
                claim_positions.append({"invalid": item})
                continue
            claim_positions.append(
                {
                    "subject_key": str(item.get("subject_key") or "").strip(),
                    "subject_label": str(item.get("subject_label") or "").strip(),
                    "decision_window": str(item.get("decision_window") or "").strip().lower(),
                    "stance": str(item.get("stance") or "").strip().lower(),
                    "summary": str(item.get("summary") or "").strip(),
                    "evidence_ids": [str(value).strip() for value in (item.get("evidence_ids") or []) if str(value).strip()],
                }
            )
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
        "claim_positions": claim_positions,
        "related_entities": [str(item) for item in (output.get("related_entities") or []) if str(item).strip()],
        "visual_brief": str(output.get("visual_brief") or ""),
        "room_move": str(output.get("room_move") or "").strip().lower(),
        "reply_to": str(output.get("reply_to") or "").strip(),
        "room_question": str(output.get("room_question") or "").strip(),
        "evidence_ids": [str(item) for item in (output.get("cited_evidence_ids") or []) if str(item).strip()],
    }


CLAIM_POSITION_WINDOWS = {
    "next_game",
    "rest_of_season",
    "dynasty",
    "career_window",
    "multi_window",
    "availability",
    "market",
    "manager",
    "other",
}
CLAIM_POSITION_STANCES = {"positive", "negative", "conditional", "mixed", "unknown"}


def _validate_claim_positions(
    claim_positions: list[Any],
    evidence_ids: set[str],
    cited_evidence_ids: set[str],
    evidence_packets: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Validate the bounded claim register used for cross-desk comparison.

    The register is deliberately additive. Older deterministic artifacts may
    have no entries; when a writer supplies entries, every position must be
    tied to the article's real evidence boundary before it can appear as a
    room conflict.
    """

    errors: list[str] = []
    warnings: list[str] = []
    allowed_subjects: set[str] = set()
    for packet in evidence_packets or []:
        if not isinstance(packet, Mapping):
            continue
        for field in ("entity_id", "player_id", "manager_id", "roster_id", "player_name", "name"):
            value = str(packet.get(field) or "").strip().lower()
            if value:
                allowed_subjects.add(value)

    normalized_count = 0
    for index, claim in enumerate(claim_positions):
        if not isinstance(claim, Mapping) or claim.get("invalid") is not None:
            errors.append(f"claim_positions[{index}] is not an object")
            continue
        subject_key = str(claim.get("subject_key") or "").strip()
        subject_label = str(claim.get("subject_label") or "").strip()
        window = str(claim.get("decision_window") or "").strip().lower()
        stance = str(claim.get("stance") or "").strip().lower()
        summary = str(claim.get("summary") or "").strip()
        claim_evidence = {
            str(value).strip()
            for value in (claim.get("evidence_ids") or [])
            if str(value).strip()
        }
        if not subject_key:
            errors.append(f"claim_positions[{index}] has no subject_key")
        elif allowed_subjects and subject_key.lower() not in allowed_subjects:
            warnings.append(f"claim_positions[{index}] subject_key is not an exact evidence entity: {subject_key}")
        if not subject_label:
            errors.append(f"claim_positions[{index}] has no subject_label")
        if window not in CLAIM_POSITION_WINDOWS:
            errors.append(f"claim_positions[{index}] has unsupported decision_window: {window or 'blank'}")
        if stance not in CLAIM_POSITION_STANCES:
            errors.append(f"claim_positions[{index}] has unsupported stance: {stance or 'blank'}")
        if not summary:
            errors.append(f"claim_positions[{index}] has no summary")
        if not claim_evidence:
            errors.append(f"claim_positions[{index}] has no evidence_ids")
        unknown = sorted(claim_evidence - evidence_ids)
        if unknown:
            errors.append(f"claim_positions[{index}] cites unknown evidence IDs: {','.join(unknown[:5])}")
        uncited = sorted(claim_evidence - cited_evidence_ids)
        if uncited:
            errors.append(f"claim_positions[{index}] evidence is not included in cited_evidence_ids: {','.join(uncited[:5])}")
        if not unknown and claim_evidence and subject_key and subject_label and window in CLAIM_POSITION_WINDOWS and stance in CLAIM_POSITION_STANCES and summary:
            normalized_count += 1
    return {
        "valid": not errors,
        "count": normalized_count,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "status": "scored" if normalized_count else "not_provided",
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
    evidence_manifest: list[dict[str, Any]] | None = None,
    editorial_review: dict[str, Any] | None = None,
    editor_mode: str = "deterministic",
    writer_mode: str = "automatic_llm",
) -> str:
    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    front_lines = [
        "---",
        f"artifact_type: {article.key}",
        f"generated_at: {generated_at}",
        f"model_mode: {str(writer_mode or 'automatic_llm').strip().lower()}",
        f"model: {model}",
        f"editor_mode: {str(editor_mode or 'deterministic').strip().lower()}",
        f"evidence_fingerprint: {evidence_fingerprint}",
        f"reporter_persona: {persona_metadata(writer_preferences, article_key)['persona_id']}",
        f"reporter_name: {persona_metadata(writer_preferences, article_key)['name']}",
        "article_payload_json: " + json.dumps(structured or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "source_receipt_json: " + json.dumps(source_receipt or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "evidence_manifest_schema: " + articles.EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "evidence_manifest_json: " + json.dumps(evidence_manifest or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
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


def _prepare_fanout_article(
    ctx: articles.ArticleContext,
    article: articles.Article,
    context: FantasyContext | None,
    *,
    model: str,
    editor_mode: str,
    reasoning_effort: str,
    reality_check_packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze one specialist's evidence and reuse decision before fan-out."""

    output_path = ANALYSIS_DIR / article.output_filename
    reporter = persona_metadata(ctx.writer_preferences, article.key)
    evidence = article.scope(ctx)
    if article.key != "daily_brief":
        evidence = articles.apply_entity_dedup(ctx, evidence)
    evidence = _attach_reality_check_receipts(evidence, reality_check_packet)
    editorial_context = _editorial_room_context(ctx, article, output_path)
    system_prompt = _article_system_prompt(article, ctx.writer_preferences, context)
    evidence_fingerprint = _article_evidence_fingerprint(
        article, evidence, system_prompt, context, editorial_context
    ) if evidence else ""
    previous = _previous_article_artifact(context, article.key)
    prompt_cache_key = _provider_cache_key(context, article.key, "writer")
    safety_identifier = _provider_safety_identifier(context)
    return {
        "article": article,
        "output_path": output_path,
        "reporter": reporter,
        "evidence": evidence,
        "editorial_context": editorial_context,
        "system_prompt": system_prompt,
        "evidence_fingerprint": evidence_fingerprint,
        "reasoning_effort": reasoning_effort,
        "prompt_cache_key": prompt_cache_key,
        "safety_identifier": safety_identifier,
        "previous": previous,
        "reuse_article": bool(
            evidence
            and _can_reuse_article(
                previous, output_path, evidence_fingerprint, reporter, model, editor_mode, reasoning_effort
            )
        ),
        "reuse_writer_draft": bool(
            evidence
            and not _can_reuse_article(
                previous, output_path, evidence_fingerprint, reporter, model, editor_mode, reasoning_effort
            )
            and _can_reuse_writer_draft(
                previous, output_path, evidence_fingerprint, reporter, model, editor_mode, reasoning_effort
            )
        ),
    }


def _require_verified_editorial_context(context: FantasyContext | None) -> FantasyContext:
    """Fail closed before private evidence is exported or imported."""

    if context is None or context.user_id is None:
        raise ValueError("A user-scoped fantasy context is required for Codex editorial work.")
    if not str(context.league_id or "").strip() or not str(context.season or "").strip():
        raise ValueError("A league and season are required for Codex editorial work.")
    if context.roster_id is None:
        raise ValueError("A verified roster_id is required for Codex editorial work.")
    if str(context.identity_status or "").strip().lower() not in {"verified", "verified_roster_match"}:
        raise ValueError("The Clerk-to-Sleeper roster identity is not verified.")
    return context


def _editorial_packet_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash the exact Codex input contract without its clock or stored hash."""

    stable = {
        str(key): value
        for key, value in payload.items()
        if str(key) not in {"generated_at", "packet_fingerprint", "packet_path"}
    }
    encoded = json.dumps(
        stable,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_codex_editorial_packet(
    paths: LeaguePaths | None = None,
    context: FantasyContext | None = None,
    article_keys: set[str] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Export the one canonical evidence contract used by Codex and API writers.

    The packet contains private league evidence, so callers must already have
    authenticated operator access.  It is stored only inside the selected
    user's private league workspace and never under the repository data root.
    Daily Brief is intentionally a second-stage export: by default the packet
    contains the five specialist desks, whose imported output can then become
    bounded room context for a targeted ``daily_brief`` packet.
    """

    if paths is not None:
        with operator_scope(paths):
            return build_codex_editorial_packet(
                context=context,
                article_keys=article_keys,
                persist=persist,
            )
    context = _require_verified_editorial_context(context)
    registry = {article.key: article for article in articles.ARTICLES}
    requested = (
        {str(key).strip() for key in article_keys if str(key).strip()}
        if article_keys
        else {key for key in registry if key != "daily_brief"}
    )
    unknown = sorted(requested - set(registry))
    if unknown:
        raise ValueError(f"Unknown editorial article key(s): {', '.join(unknown)}")

    reality_check_path = ANALYSIS_DIR / "reality_check.json"
    try:
        raw_reality_check = load_json(reality_check_path) if reality_check_path.is_file() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        raw_reality_check = {}
    reality_check = raw_reality_check if isinstance(raw_reality_check, Mapping) else {}
    llm = configured_llm()
    ctx = articles.ArticleContext(
        analysis_dir=ANALYSIS_DIR,
        active_roster_id=context.roster_id,
        processed_dir=PROCESSED_DIR,
        user_id=context.user_id,
        league_id=context.league_id,
        season=context.season,
        team_name=context.team_name,
        writer_preferences=context.writer_preferences,
    )
    _seed_prior_specialist_context(ctx, requested)
    packet_articles: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for article in sorted(articles.ARTICLES, key=_article_execution_sort_key):
        if article.key not in requested:
            continue
        output_path = ANALYSIS_DIR / article.output_filename
        evidence = article.scope(ctx)
        if article.key != "daily_brief":
            evidence = articles.apply_entity_dedup(ctx, evidence)
        evidence = _attach_reality_check_receipts(evidence, reality_check)
        if not evidence:
            blocked.append({"article_key": article.key, "reason": "No scoped deterministic evidence is available."})
            continue
        system_prompt = _article_system_prompt(article, ctx.writer_preferences, context)
        editorial_context = _editorial_room_context(ctx, article, output_path)
        evidence_fingerprint = _article_evidence_fingerprint(
            article,
            evidence,
            system_prompt,
            context,
            editorial_context,
        )
        reporter = persona_metadata(ctx.writer_preferences, article.key)
        packet_articles.append(
            {
                "article_key": article.key,
                "title": article.title,
                "section": article.section,
                "reporter": reporter,
                "required_headers": list(article.headers),
                "system_prompt": system_prompt,
                "editorial_context": editorial_context,
                "evidence": evidence,
                "evidence_manifest": articles.build_evidence_manifest(evidence),
                "evidence_fingerprint": evidence_fingerprint,
                "output_tool": {
                    "name": ARTICLE_TOOL["name"],
                    "description": ARTICLE_TOOL["description"],
                    "input_schema": deepcopy(ARTICLE_TOOL["input_schema"]),
                },
                "model": llm.model,
                "reasoning_effort": article_reasoning_effort(article.key, llm.reasoning_effort),
            }
        )
    packet = {
        "schema_version": CODEX_EDITORIAL_PACKET_SCHEMA_VERSION,
        "generated_at": _now(),
        "state": "complete" if packet_articles and not blocked else "partial" if packet_articles else "blocked",
        "writer_mode": "codex_task",
        "scope": {
            "user_id": str(context.user_id),
            "league_id": str(context.league_id),
            "league_name": str(context.league_name or ""),
            "season": str(context.season),
            "roster_id": int(context.roster_id),
            "team_name": str(context.team_name or context.display_name or ""),
            "sleeper_user_id": str(context.sleeper_user_id or ""),
            "identity_status": str(context.identity_status),
            "identity_checked_at": str(context.identity_checked_at or ""),
        },
        "requested_article_keys": [
            article.key
            for article in sorted(articles.ARTICLES, key=_article_execution_sort_key)
            if article.key in requested
        ],
        "article_keys": [item["article_key"] for item in packet_articles],
        "blocked": blocked,
        "articles": packet_articles,
        "workflow": {
            "facts_owner": "deterministic_data_layer",
            "interpretation_owner": "codex_task",
            "api_role": "fallback_only",
            "publication_rule": "Import the complete structured output through the validated editorial seam; never write article markdown directly.",
            "daily_brief_rule": "Import specialist desks first, then export daily_brief so it can synthesize their bounded room context.",
        },
    }
    packet["packet_fingerprint"] = _editorial_packet_fingerprint(packet)
    if persist:
        _write_json(CODEX_EDITORIAL_PACKET_PATH, packet)
    return packet


def import_codex_editorial_output(
    payload: Mapping[str, Any],
    paths: LeaguePaths | None = None,
    context: FantasyContext | None = None,
) -> dict[str, Any]:
    """Validate and atomically publish structured Codex article output."""

    if paths is not None:
        with operator_scope(paths):
            return import_codex_editorial_output(payload, context=context)
    context = _require_verified_editorial_context(context)
    submitted = dict(payload) if isinstance(payload, Mapping) else {}
    stored_packet = _safe_json(CODEX_EDITORIAL_PACKET_PATH)
    if stored_packet.get("schema_version") != CODEX_EDITORIAL_PACKET_SCHEMA_VERSION:
        raise ValueError("No current Codex editorial packet exists for this league scope.")
    expected_packet_fingerprint = str(stored_packet.get("packet_fingerprint") or "")
    if not expected_packet_fingerprint or expected_packet_fingerprint != _editorial_packet_fingerprint(stored_packet):
        raise ValueError("The stored Codex editorial packet receipt is invalid.")
    if str(submitted.get("packet_fingerprint") or "") != expected_packet_fingerprint:
        raise ValueError("The submitted packet_fingerprint does not match the current exported packet.")

    scope = stored_packet.get("scope") if isinstance(stored_packet.get("scope"), Mapping) else {}
    expected_scope = (
        str(context.user_id),
        str(context.league_id),
        str(context.season),
        int(context.roster_id),
    )
    stored_scope = (
        str(scope.get("user_id") or ""),
        str(scope.get("league_id") or ""),
        str(scope.get("season") or ""),
        int(scope.get("roster_id")) if str(scope.get("roster_id") or "").isdigit() else None,
    )
    if stored_scope != expected_scope:
        raise ValueError("The exported packet does not belong to the selected user, league, season, and roster_id.")

    packet_keys = [str(key) for key in (stored_packet.get("article_keys") or []) if str(key).strip()]
    current_packet = build_codex_editorial_packet(
        context=context,
        article_keys=set(stored_packet.get("requested_article_keys") or packet_keys),
        persist=False,
    )
    if str(current_packet.get("packet_fingerprint") or "") != expected_packet_fingerprint:
        raise ValueError("Deterministic evidence or bounded editorial context changed after export; export a new packet.")

    raw_articles = submitted.get("articles")
    submitted_articles = raw_articles if isinstance(raw_articles, Mapping) else {}
    submitted_keys = {str(key) for key in submitted_articles}
    if submitted_keys != set(packet_keys):
        missing = sorted(set(packet_keys) - submitted_keys)
        unknown = sorted(submitted_keys - set(packet_keys))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unexpected " + ", ".join(unknown))
        raise ValueError("Codex import must contain every packet article exactly once: " + "; ".join(detail))

    registry = {article.key: article for article in articles.ARTICLES}
    packet_by_key = {
        str(item.get("article_key") or ""): item
        for item in (stored_packet.get("articles") or [])
        if isinstance(item, Mapping)
    }
    model = str(submitted.get("model") or configured_llm().model or "gpt-5.6-luna").strip()
    prepared: list[dict[str, Any]] = []
    validation_errors: dict[str, list[str]] = {}
    from .editorial import review_publication_article

    for article_key in packet_keys:
        article = registry.get(article_key)
        packet_article = packet_by_key.get(article_key) or {}
        item = submitted_articles.get(article_key)
        item = item if isinstance(item, Mapping) else {}
        output = item.get("output") if isinstance(item.get("output"), Mapping) else {}
        fingerprint = str(packet_article.get("evidence_fingerprint") or "")
        if str(item.get("evidence_fingerprint") or "") != fingerprint:
            validation_errors.setdefault(article_key, []).append("evidence_fingerprint does not match the exported article packet")
            continue
        evidence = [dict(row) for row in (packet_article.get("evidence") or []) if isinstance(row, Mapping)]
        evidence_ids = {str(row.get("evidence_id")) for row in evidence if row.get("evidence_id")}
        validation = validate_article_output(
            dict(output),
            evidence_ids,
            article.headers if article else tuple(packet_article.get("required_headers") or []),
            evidence,
            article_key=article_key,
        )
        structured = dict(validation.get("structured") or {}) | {
            "evidence_ids": validation.get("evidence_ids") or [],
            "source_ids": validation.get("source_ids") or [],
            "source_count": len(validation.get("source_ids") or []),
            "source_quality": (
                "multi_source" if len(validation.get("source_ids") or []) > 1
                else "single_source" if validation.get("source_ids")
                else "unattributed"
            ),
            "boundary_checks": validation.get("boundary_checks") or {},
            "reality_check": validation.get("reality_check") or {},
        }
        gate = review_publication_article(
            article_key,
            str(validation.get("narrative") or ""),
            {"structured": structured},
            "codex_task",
        )
        errors = list(validation.get("errors") or []) + list(gate.get("errors") or [])
        if not article:
            errors.append("article is not registered")
        if gate.get("status") != "approved":
            errors.append("deterministic publication gate did not approve the article")
        if errors:
            validation_errors[article_key] = list(dict.fromkeys(str(error) for error in errors if str(error).strip()))
            continue
        prepared.append(
            {
                "article": article,
                "packet_article": packet_article,
                "validation": validation,
                "structured": structured,
                "gate": gate,
                "evidence": evidence,
                "evidence_fingerprint": fingerprint,
            }
        )
    if validation_errors:
        receipt = {
            "schema_version": CODEX_EDITORIAL_IMPORT_SCHEMA_VERSION,
            "state": "rejected",
            "imported_at": _now(),
            "packet_fingerprint": expected_packet_fingerprint,
            "scope": dict(scope),
            "errors": validation_errors,
            "written_article_keys": [],
        }
        _write_json(CODEX_EDITORIAL_IMPORT_RECEIPT_PATH, receipt)
        return receipt

    imported_at = _now()
    written: list[str] = []
    for item in prepared:
        article = item["article"]
        validation = item["validation"]
        output_path = ANALYSIS_DIR / article.output_filename
        reporter = item["packet_article"].get("reporter") or persona_metadata(context.writer_preferences, article.key)
        source_receipt = {
            "scope": "selected_league_validated_evidence",
            "evidence_fingerprint": item["evidence_fingerprint"],
            "source_count": len(validation.get("source_ids") or []),
            "source_ids": validation.get("source_ids") or [],
            "packet_fingerprint": expected_packet_fingerprint,
            "reality_check": validation.get("reality_check") or {},
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            _render_article_markdown(
                article,
                validation["narrative"],
                imported_at,
                output_path,
                context.writer_preferences,
                article.key,
                item["evidence_fingerprint"],
                model,
                item["structured"],
                source_receipt=source_receipt,
                evidence_manifest=articles.build_evidence_manifest(item["evidence"]),
                editorial_review=item["gate"],
                writer_mode="codex_task",
            ),
            encoding="utf-8",
        )
        content_hash = _content_hash(output_path)
        _record_article_artifact(
            context,
            article,
            output_path,
            validation,
            evidence_fingerprint=item["evidence_fingerprint"],
            content_hash=content_hash,
            reporter=reporter,
            model=model,
            generation_metadata={
                "provider": "codex",
                "model": model,
                "writer_mode": "codex_task",
                "packet_fingerprint": expected_packet_fingerprint,
                "cost_known": False,
            },
            editorial_review=item["gate"],
            writer_mode="codex_task",
        )
        written.append(article.key)
    receipt = {
        "schema_version": CODEX_EDITORIAL_IMPORT_SCHEMA_VERSION,
        "state": "complete",
        "imported_at": imported_at,
        "packet_fingerprint": expected_packet_fingerprint,
        "scope": dict(scope),
        "model": model,
        "writer_mode": "codex_task",
        "article_keys": written,
        "written_article_keys": written,
        "errors": {},
    }
    _write_json(CODEX_EDITORIAL_IMPORT_RECEIPT_PATH, receipt)
    return receipt


def _fanout_writer_drafts(
    prepared: list[dict[str, Any]],
    *,
    api_key: str,
    model: str,
    worker_id: str = "",
    edition_run_id: str = "",
    provider: str = "",
    reasoning_effort: str = "",
) -> dict[str, dict[str, Any]]:
    """Run independent specialist writer calls with a bounded concurrency cap.

    Evidence scoping and file/database persistence remain outside the thread
    pool.  Only provider calls fan out, so entity de-duplication, article
    ordering, and the final synthesis stay deterministic and serialized.
    """

    candidates = [
        item for item in prepared
        if item.get("evidence")
        and not item.get("reuse_article")
        and not item.get("reuse_writer_draft")
    ]
    if not candidates:
        return {}

    def run_one(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        article = item["article"]
        desk_effort = str(item.get("reasoning_effort") or reasoning_effort or "")
        receipt = _edition_job_start(
            edition_run_id,
            article.key,
            phase="writer",
            provider=provider,
            model=model,
            reasoning_effort=desk_effort,
            evidence_fingerprint=str(item.get("evidence_fingerprint") or ""),
            worker_id=worker_id,
        )
        if worker_id and not receipt:
            return article.key, {
                "job_started": False,
                "error": RuntimeError("The worker could not claim this desk job."),
            }
        if receipt and str(receipt.get("state") or "").lower() in {"dead_letter", "cancelled"}:
            return article.key, {"job_started": False, "job_receipt": receipt}
        try:
            provider_controls = (
                {
                    "reasoning_effort": desk_effort,
                    "prompt_cache_key": item.get("prompt_cache_key"),
                    "safety_identifier": item.get("safety_identifier"),
                }
                if str(provider or "").strip().lower() == "openai"
                else {}
            )
            output = generate_article_via_llm(
                item["system_prompt"],
                item["evidence"],
                api_key,
                model,
                editorial_context=item["editorial_context"],
                **provider_controls,
            )
        except Exception as exc:  # noqa: BLE001 - the serial phase records the desk failure.
            return article.key, {"job_started": bool(receipt), "job_receipt": receipt, "error": exc}
        return article.key, {"job_started": bool(receipt), "job_receipt": receipt, "output": output}

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(writer_concurrency(), len(candidates))) as pool:
        futures = {pool.submit(run_one, item): item["article"].key for item in candidates}
        for future in as_completed(futures):
            key = futures[future]
            try:
                _, result = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve a per-desk failure receipt.
                result = {"job_started": False, "error": exc}
            results[key] = result
    return results


def generate_articles_workflow(
    paths: LeaguePaths | None = None,
    context: FantasyContext | None = None,
    article_keys: set[str] | None = None,
    edition_run_id: str = "",
    worker_id: str = "",
) -> dict[str, Any]:
    """Explicit, user-triggered, cost-incurring action. Generates one article per meaningful
    section (each independently validated, each falling back to its deterministic .md on failure),
    then a daily brief that synthesizes across them. Fails loud only on missing API key."""
    if paths is not None:
        with operator_scope(paths):
            return generate_articles_workflow(
                context=context,
                article_keys=article_keys,
                edition_run_id=edition_run_id,
                worker_id=worker_id,
            )
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
    reality_check_path = ANALYSIS_DIR / "reality_check.json"
    try:
        raw_reality_check_packet = load_json(reality_check_path) if reality_check_path.is_file() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        # A damaged optional packet must be visible in the article receipt,
        # but it must not turn a provider timeout into a misleading traceback.
        raw_reality_check_packet = {}
    reality_check_packet = (
        raw_reality_check_packet
        if isinstance(raw_reality_check_packet, Mapping)
        else {}
    )

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
        for article in sorted(articles.ARTICLES, key=_article_execution_sort_key)
        if article_keys is None or article.key in article_keys
    ]
    # Existing specialist articles are editorial room context for both a full
    # edition and a targeted retry. The selected desk is excluded so its own
    # prior edition remains represented by _editorial_room_context's dedicated
    # previous_edition note, while summary desks stay synthesis outputs rather
    # than peer evidence for a new specialist call.
    _seed_prior_specialist_context(ctx, article_keys)

    if not edition_run_id:
        current_operator_status = status()
        edition_run_id = begin_edition_run(
            context,
            operator_run_id=str(current_operator_status.get("run_id") or ""),
            article_keys=article_keys,
        )
    durable_total_count = len(article_queue)
    durable_completed_base = 0
    durable_run: dict[str, Any] = {}
    if edition_run_id:
        try:
            from app import db as app_db

            durable_run = app_db.get_edition_run(edition_run_id) or {}
            requested_keys = durable_run.get("requested_article_keys")
            if isinstance(requested_keys, list) and requested_keys:
                durable_total_count = len(requested_keys)
            queue_keys = {article.key for article in article_queue}
            durable_jobs = durable_run.get("jobs") if isinstance(durable_run.get("jobs"), list) else []
            successful_keys = {
                str(job.get("article_key") or "")
                for job in durable_jobs
                if isinstance(job, Mapping)
                and str(job.get("phase") or "writer") == "writer"
                and str(job.get("state") or "").lower() in {"published", "reused", "skipped"}
            }
            durable_completed_base = len(successful_keys - queue_keys)
        except Exception:  # noqa: BLE001 - the JSON receipt remains the compatibility fallback.
            durable_total_count = len(article_queue)
            durable_completed_base = 0
    edition_packet: dict[str, Any] = {}
    if edition_run_id and context is not None:
        packet_keys = (
            durable_run.get("requested_article_keys")
            if isinstance(durable_run.get("requested_article_keys"), list) and durable_run.get("requested_article_keys")
            else [article.key for article in article_queue]
        )
        try:
            edition_packet = _freeze_edition_packet(
                context,
                edition_run_id,
                packet_keys,
                reality_check_packet,
            )
            _record_edition_packet(edition_run_id, edition_packet)
        except EditionInputChanged as exc:
            _edition_run_checkpoint(
                edition_run_id,
                stage="blocked",
                state="failed",
                failure_class="edition_input_changed",
                failure_message="The edition's frozen evidence inputs changed; start a new edition run.",
                complete=True,
                worker_id=worker_id,
            )
            write_edition_execution_receipt(edition_run_id)
            return {
                "state": "blocked",
                "message": str(exc),
                "generated_at": generated_at,
                "edition_run_id": edition_run_id,
                "edition_packet": {"status": "changed", "publication_gate": "hold"},
                "articles": {},
            }
    _edition_run_checkpoint(
        edition_run_id,
        stage="writing",
        total_count=durable_total_count,
        completed_count=durable_completed_base,
        worker_id=worker_id,
    )

    def record_progress(current_article: articles.Article | None, completed_count: int) -> None:
        if worker_id and not _edition_run_heartbeat(edition_run_id, worker_id):
            raise EditionLeaseLost("The newsroom worker lost its edition lease.")
        _write_writer_progress(
            results,
            current_article=current_article,
            completed_count=durable_completed_base + completed_count,
            total_count=durable_total_count,
            model=model,
            reasoning_effort=llm.reasoning_effort,
            editor_mode=editor_mode,
            writer_preferences=ctx.writer_preferences,
            edition_run_id=edition_run_id,
        )
        _edition_run_checkpoint(
            edition_run_id,
            stage="writing",
            completed_count=durable_completed_base + completed_count,
            total_count=durable_total_count,
            worker_id=worker_id,
        )
        write_edition_execution_receipt(edition_run_id)

    record_progress(None, 0)

    prepared_by_key: dict[str, dict[str, Any]] = {}
    prefetched_writer_results: dict[str, dict[str, Any]] = {}
    specialist_queue = [article for article in article_queue if article.key != "daily_brief"]
    if writer_concurrency() > 1 and len(specialist_queue) > 1:
        if _edition_run_cancelled(edition_run_id):
            _close_cancelled_edition(edition_run_id, worker_id)
            return {
                "state": "cancelled",
                "message": "The edition was cancelled before specialist desk calls began.",
                "generated_at": generated_at,
                "edition_run_id": edition_run_id,
                "edition_packet": _edition_packet_result(edition_packet),
                "articles": {},
            }
        if worker_id and not _edition_run_heartbeat(edition_run_id, worker_id):
            raise RuntimeError("The newsroom worker lost its edition lease before fan-out.")
        for article in specialist_queue:
            try:
                prepared_by_key[article.key] = _prepare_fanout_article(
                    ctx,
                    article,
                    context,
                    model=model,
                    editor_mode=editor_mode,
                    reasoning_effort=article_reasoning_effort(article.key, llm.reasoning_effort),
                    reality_check_packet=reality_check_packet,
                )
            except Exception as exc:  # noqa: BLE001 - the serial loop records this desk failure.
                prepared_by_key[article.key] = {
                    "article": article,
                    "output_path": ANALYSIS_DIR / article.output_filename,
                    "reporter": persona_metadata(ctx.writer_preferences, article.key),
                    "prepare_error": exc,
                }
        prefetched_writer_results = _fanout_writer_drafts(
            list(prepared_by_key.values()),
            api_key=api_key,
            model=model,
            worker_id=worker_id,
            edition_run_id=edition_run_id,
            provider=llm.provider,
            reasoning_effort=llm.reasoning_effort,
        )
        if _edition_run_cancelled(edition_run_id):
            _close_cancelled_edition(edition_run_id, worker_id)
            return {
                "state": "cancelled",
                "message": "The edition was cancelled while specialist desks were writing.",
                "generated_at": generated_at,
                "edition_run_id": edition_run_id,
                "edition_packet": _edition_packet_result(edition_packet),
                "articles": {},
            }

    for article_index, article in enumerate(article_queue, start=1):
        record_progress(article, article_index - 1)
        if _edition_run_cancelled(edition_run_id):
            _close_cancelled_edition(edition_run_id, worker_id)
            return {
                "state": "cancelled",
                "message": "The edition was cancelled before publication.",
                "generated_at": generated_at,
                "edition_run_id": edition_run_id,
                "edition_packet": _edition_packet_result(edition_packet),
                "articles": results,
            }
        if worker_id and not _edition_run_heartbeat(edition_run_id, worker_id):
            raise RuntimeError("The newsroom worker lost its edition lease.")
        output_path = ANALYSIS_DIR / article.output_filename
        reporter = persona_metadata(ctx.writer_preferences, article.key)
        article_effort = article_reasoning_effort(article.key, llm.reasoning_effort)
        evidence_fingerprint = ""
        prepared = prepared_by_key.get(article.key)
        try:
            if prepared is not None:
                if prepared.get("prepare_error") is not None:
                    raise prepared["prepare_error"]
                evidence = prepared.get("evidence") or []
                output_path = prepared.get("output_path") or output_path
                reporter = prepared.get("reporter") or reporter
                evidence_fingerprint = str(prepared.get("evidence_fingerprint") or "")
                article_effort = str(prepared.get("reasoning_effort") or article_effort)
                editorial_context = prepared.get("editorial_context") or []
                system_prompt = str(prepared.get("system_prompt") or "")
                previous = prepared.get("previous") or {}
            else:
                # A targeted summary retry may have no current specialist
                # output in this process. Let it synthesize the prior desk
                # reports, but keep those rows out of the specialist room
                # context and out of a normal full-run summary.
                if article.key == "daily_brief" and article_keys is not None:
                    for key, narrative in ctx.prior_section_outputs.items():
                        ctx.section_outputs.setdefault(key, narrative)
                evidence = article.scope(ctx)
                if article.key != "daily_brief":
                # First article to scope a player claims it; later ones get a "covered elsewhere"
                # note instead -- kills the same-player-profiled-in-three-sections repetition.
                    evidence = articles.apply_entity_dedup(ctx, evidence)
                evidence = _attach_reality_check_receipts(evidence, reality_check_packet)
            if not evidence:
                results[article.key] = {"state": "skipped", "message": "No evidence available; deterministic version kept."}
                _edition_job_start(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    provider=llm.provider,
                    model=model,
                    reasoning_effort=article_effort,
                    worker_id=worker_id,
                )
                _edition_job_finish(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    state="skipped",
                    metadata={"reason": "no_validated_evidence"},
                    worker_id=worker_id,
                )
                record_progress(article, article_index)
                continue

            if prepared is None:
                output_path = ANALYSIS_DIR / article.output_filename
                editorial_context = _editorial_room_context(ctx, article, output_path)
                system_prompt = _article_system_prompt(article, ctx.writer_preferences, context)
                evidence_fingerprint = _article_evidence_fingerprint(
                    article, evidence, system_prompt, context, editorial_context
                )
                previous = _previous_article_artifact(context, article.key)
            reuse_article = bool(
                prepared.get("reuse_article") if prepared is not None
                else _can_reuse_article(
                    previous, output_path, evidence_fingerprint, reporter, model, editor_mode, article_effort
                )
            )
            prefetched = prefetched_writer_results.get(article.key)
            if prefetched is None:
                job_receipt = _edition_job_start(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    provider=llm.provider,
                    model=model,
                    reasoning_effort=article_effort,
                    evidence_fingerprint=evidence_fingerprint,
                    worker_id=worker_id,
                )
                if worker_id and not job_receipt:
                    raise RuntimeError("The newsroom worker could not claim the desk job.")
            else:
                job_receipt = prefetched.get("job_receipt")
                if prefetched.get("error") is not None:
                    raise prefetched["error"]
            if job_receipt and str(job_receipt.get("state") or "").lower() in {"dead_letter", "cancelled"}:
                results[article.key] = {
                    "state": str(job_receipt.get("state") or "failed").lower(),
                    "message": f"{article.title} was not run: {job_receipt.get('error_message') or 'desk job unavailable.'}",
                    "reporter": reporter,
                }
                record_progress(article, article_index)
                continue
            if reuse_article:
                narrative = _article_narrative_from_file(output_path)
                if not narrative:
                    raise ValueError("Existing article receipt matched but its narrative is empty.")
                if article.key != "daily_brief":
                    ctx.section_outputs[article.key] = narrative
                results[article.key] = {
                    "state": "unchanged",
                    "message": f"{article.title} unchanged; evidence and article receipt still match.",
                    "reporter": reporter,
                    "evidence_fingerprint": evidence_fingerprint,
                    "content_hash": _content_hash(output_path),
                }
                _edition_job_finish(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    state="reused",
                    metadata={"content_hash": results[article.key]["content_hash"]},
                    worker_id=worker_id,
                )
                record_progress(article, article_index)
                continue

            writer_draft_reused = bool(
                prepared.get("reuse_writer_draft") if prepared is not None
                else _can_reuse_writer_draft(
                    previous,
                    output_path,
                    evidence_fingerprint,
                    reporter,
                    model,
                    editor_mode,
                    article_effort,
                )
            )
            prefetched = prefetched_writer_results.get(article.key)
            output = (
                _existing_article_writer_output(output_path)
                if writer_draft_reused
                else prefetched.get("output") if prefetched is not None else None
            )
            if prefetched is not None and prefetched.get("error") is not None:
                raise prefetched["error"]
            if prefetched is not None and not isinstance(output, dict):
                raise RuntimeError("The specialist fan-out returned no writer output.")
            if not isinstance(output, dict):
                writer_draft_reused = False
                provider_controls = (
                    {
                        "reasoning_effort": article_effort,
                        "prompt_cache_key": (
                            prepared.get("prompt_cache_key")
                            if prepared is not None
                            else _provider_cache_key(context, article.key, "writer")
                        ),
                        "safety_identifier": (
                            prepared.get("safety_identifier")
                            if prepared is not None
                            else _provider_safety_identifier(context)
                        ),
                    }
                    if llm.provider == "openai"
                    else {}
                )
                output = generate_article_via_llm(
                    system_prompt,
                    evidence,
                    api_key,
                    model,
                    editorial_context=editorial_context,
                    **provider_controls,
                )
            evidence_ids = {str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")}
            validation = validate_article_output(
                output,
                evidence_ids,
                article.headers,
                evidence,
                reality_check_packet=reality_check_packet,
                article_key=article.key,
            )
            if validation["valid"]:
                _edition_job_finish(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    state="reused" if writer_draft_reused else "drafted",
                    provider_receipt=output.get("_provider_receipt") if isinstance(output, dict) else {},
                    metadata={"writer_draft_reused": writer_draft_reused},
                    worker_id=worker_id,
                )
                final_output = output
                final_validation = validation
                editorial_review: dict[str, Any] | None = None
                if editor_mode == "llm":
                    _edition_job_start(
                        edition_run_id,
                        article.key,
                        phase="editor",
                        provider=llm.provider,
                        model=model,
                        reasoning_effort=article_effort,
                        evidence_fingerprint=evidence_fingerprint,
                        worker_id=worker_id,
                    )
                    editor_failure = ""
                    try:
                        editor_controls = (
                            {
                                "reasoning_effort": article_effort,
                                "prompt_cache_key": _provider_cache_key(context, article.key, "editor"),
                                "safety_identifier": _provider_safety_identifier(context),
                            }
                            if llm.provider == "openai"
                            else {}
                        )
                        editor_output = review_article_via_llm(
                            _editor_system_prompt(article, ctx.writer_preferences, context),
                            evidence,
                            output,
                            api_key,
                            model,
                            **editor_controls,
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve the writer draft as an explicit held receipt.
                        editor_output = None
                        editor_failure = f"The desk editor request failed: {type(exc).__name__}."
                        _edition_job_finish(
                            edition_run_id,
                            article.key,
                            phase="editor",
                            state="failed",
                            error=exc,
                            worker_id=worker_id,
                        )
                    else:
                        _edition_job_finish(
                            edition_run_id,
                            article.key,
                            phase="editor",
                            state="reviewed",
                            provider_receipt=editor_output.get("_provider_receipt") if isinstance(editor_output, dict) else {},
                            worker_id=worker_id,
                        )
                    final_output, editorial_review = _editor_review_result(
                        article,
                        output,
                        validation,
                        editor_output,
                        evidence,
                        model,
                        reality_check_packet,
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
                        reality_check_packet=reality_check_packet,
                        article_key=article.key,
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
                    "reality_check": final_validation.get("reality_check") or {},
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
                            "reality_check": final_validation.get("reality_check") or {},
                        },
                        evidence_manifest=articles.build_evidence_manifest(evidence),
                        editorial_review=editorial_review,
                        editor_mode=editor_mode,
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
                        "reasoning_effort": article_effort,
                        "reality_check": final_validation.get("reality_check") or {},
                        "cost_known": False,
                    },
                    status=publication_status,
                    fallback_reason="; ".join(str(value) for value in (editor_errors or []) if str(value).strip()),
                    editorial_review=editorial_review,
                )
                if article.key != "daily_brief" and publication_status == "generated":
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
                    "reality_check": final_validation.get("reality_check") or {},
                    "editorial_review": editorial_review or {"mode": "deterministic", "status": "pending_llm_review"},
                    "reporter": reporter,
                    "evidence_fingerprint": evidence_fingerprint,
                    "content_hash": content_hash,
                }
                _edition_job_finish(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    state="published" if publication_status == "generated" else "held",
                    provider_receipt=output.get("_provider_receipt") if isinstance(output, dict) else {},
                    metadata={"publication_status": publication_status, "content_hash": content_hash},
                    worker_id=worker_id,
                )
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
                    reasoning_effort=article_effort,
                    status="failed",
                    fallback_reason="; ".join(validation["errors"]),
                )
                results[article.key] = {
                    "state": "held" if (validation.get("reality_check") or {}).get("publication_gate") == "hold" else "failed",
                    "message": (
                        f"{article.title} held by Reality Check before publication."
                        if (validation.get("reality_check") or {}).get("publication_gate") == "hold"
                        else f"{article.title} failed validation."
                    ),
                    "errors": validation["errors"],
                    "reality_check": validation.get("reality_check") or {},
                }
                _edition_job_finish(
                    edition_run_id,
                    article.key,
                    phase="writer",
                    state="held" if results[article.key]["state"] == "held" else "failed",
                    metadata={"validation_errors": validation["errors"]},
                    worker_id=worker_id,
                )
                record_progress(article, article_index)
        except EditionLeaseLost:
            raise
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
                reasoning_effort=article_effort,
                status="failed",
                fallback_reason=str(exc),
            )
            results[article.key] = {"state": "failed", "message": f"{article.title} generation failed: {exc}"}
            _edition_job_finish(
                edition_run_id,
                article.key,
                phase="writer",
                state="failed",
                error=exc,
                worker_id=worker_id,
            )
            record_progress(article, article_index)

    attempted = [state for state in results.values() if state["state"] != "skipped"]
    completed = [state for state in attempted if state["state"] in {"complete", "unchanged"}]
    held = [state for state in attempted if state["state"] == "held"]
    failed = [state for state in attempted if state["state"] == "failed"]
    dead_lettered = [state for state in attempted if state["state"] == "dead_letter"]
    cancelled = [state for state in attempted if state["state"] == "cancelled"]
    if attempted and len(completed) == len(attempted):
        state = "complete"
    elif cancelled and not completed and not held:
        state = "cancelled"
    elif completed or held:
        state = "partial"
    else:
        state = "failed"
    _edition_run_checkpoint(
        edition_run_id,
        stage="desk_complete",
        state="pending_publication",
        completed_count=durable_completed_base + len(completed),
        total_count=durable_total_count,
        complete=False,
        worker_id=worker_id,
    )
    execution_receipt = write_edition_execution_receipt(edition_run_id)
    return {
        "state": state,
        "message": (
            f"Articles published: {len(completed)} current, {len(held)} held by the desk editor, "
            f"{len(failed)} failed, {len(dead_lettered)} dead-lettered, {len(cancelled)} cancelled, "
            f"{len(results) - len(attempted)} skipped."
        ),
        "generated_at": generated_at,
        "provider": llm.provider,
        "model": model,
        "reasoning_effort": llm.reasoning_effort,
        "editor_mode": editor_mode,
        "edition_run_id": edition_run_id,
        "reporter_persona": persona_metadata(ctx.writer_preferences, "daily_brief"),
        "edition_packet": _edition_packet_result(edition_packet),
        "edition_receipt": execution_receipt,
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
        "editor_review": 0,
        "skipped": 0,
        "blocked": 0,
        "unavailable": 0,
    }
    planned_summary_inputs_changed = False
    for article in sorted(articles.ARTICLES, key=_article_execution_sort_key):
        reporter = persona_metadata(ctx.writer_preferences, article.key)
        desk_effort = article_reasoning_effort(article.key, llm.reasoning_effort)
        entry: dict[str, Any] = {
            "article": article.key,
            "title": article.title,
            "section": article.section,
            "reporter": reporter,
            "provider": llm.provider,
            "model": llm.model,
            "reasoning_effort": desk_effort,
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
            if article.key != "daily_brief":
                evidence = articles.apply_entity_dedup(ctx, evidence)
            entry["evidence_count"] = len(evidence)
            entry["source_count"] = len(
                {
                    str(item.get("source_trace") or "").strip()
                    for item in evidence
                    if str(item.get("source_trace") or "").strip()
                }
            )
            if article.key == "daily_brief" and planned_summary_inputs_changed and writer_config["configured"]:
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

            if _can_reuse_article(
                previous, output_path, evidence_fingerprint, reporter, llm.model, editor_mode, desk_effort
            ):
                entry.update(
                    state="unchanged",
                    decision="reuse",
                    reason="Evidence, article content, reporter, and configured model still match.",
                )
                counts["reuse"] += 1
                if article.key != "daily_brief":
                    narrative = _article_narrative_from_file(output_path)
                    if narrative:
                        # The summary scope consumes the section narratives.
                        # Replaying reused inputs keeps its no-cost fingerprint
                        # identical to the real workflow.
                        ctx.section_outputs[article.key] = narrative
            elif (
                _can_reuse_writer_draft(
                    previous, output_path, evidence_fingerprint, reporter, llm.model, editor_mode, desk_effort
                )
                and writer_config["configured"]
            ):
                entry.update(
                    state="ready",
                    decision="editor_review",
                    reason="The writer draft is unchanged but was held; retry the editor pass without regenerating the article.",
                )
                counts["editor_review"] += 1
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
                elif _artifact_reasoning_effort(previous) and _artifact_reasoning_effort(previous) != desk_effort:
                    reasons.append("configured reasoning effort changed")
                entry.update(
                    state="ready",
                    decision="generate",
                    reason="; ".join(reasons) or "Current article receipt does not match the selected evidence.",
                )
                counts["generate"] += 1
                if article.key != "daily_brief":
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
    reasoning_effort: str = "",
    status: str = "generated",
    fallback_reason: str = "",
    generation_metadata: dict[str, Any] | None = None,
    editorial_review: dict[str, Any] | None = None,
    writer_mode: str = "automatic_llm",
) -> None:
    if context is None or context.user_id is None:
        return
    try:
        from app import db as app_db

        reporter = reporter or persona_metadata(context.writer_preferences, article.key)
        writer_mode = str(writer_mode or "automatic_llm").strip().lower()
        llm_receipt = writer_api_configuration()
        llm_receipt["reasoning_effort"] = str(reasoning_effort or llm_receipt.get("reasoning_effort") or "")
        app_db.record_content_artifact(
            int(context.user_id),
            context.league_id,
            context.season,
            "article",
            article.key,
            str(output_path),
            source={
                "mode": writer_mode,
                "valid": bool(validation.get("valid")),
                "writer_preferences": context.writer_preferences,
                "reporter_persona": persona_metadata(context.writer_preferences, article.key),
                "llm": llm_receipt,
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
                "reality_check": validation.get("reality_check") or {},
            },
            generation_metadata=generation_metadata or {
                "provider": llm_receipt.get("provider"),
                "model": model,
                "reasoning_effort": llm_receipt.get("reasoning_effort"),
                "cost_known": False,
            },
            status=status,
            evidence_fingerprint=evidence_fingerprint,
            content_hash=content_hash,
            reporter_id=str(reporter.get("persona_id") or ""),
            writer_mode=writer_mode,
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
    reasoning_effort: str | None = None,
) -> bool:
    if not previous or previous.get("status") != "generated" or not output_path.exists():
        return False
    if previous.get("evidence_fingerprint") != evidence_fingerprint:
        return False
    if previous.get("content_hash") != _content_hash(output_path):
        return False
    if previous.get("reporter_id") != str(reporter.get("persona_id") or ""):
        return False
    if previous.get("model") != model or previous.get("writer_mode") not in {"automatic_llm", "codex_task"}:
        return False
    source = previous.get("source") if isinstance(previous.get("source"), dict) else {}
    previous_editor_mode = str(source.get("editor_mode") or "deterministic").strip().lower()
    if previous_editor_mode != str(editor_mode or "deterministic").strip().lower():
        return False
    return _artifact_reasoning_effort(previous) in {"", str(reasoning_effort or "").strip().lower()}


def _can_reuse_writer_draft(
    previous: dict[str, Any] | None,
    output_path: Path,
    evidence_fingerprint: str,
    reporter: dict[str, Any],
    model: str,
    editor_mode: str = "deterministic",
    reasoning_effort: str | None = None,
) -> bool:
    """Allow an unchanged held draft to enter the editor without another writer call."""

    if not previous or previous.get("status") != "held" or not output_path.exists():
        return False
    if previous.get("evidence_fingerprint") != evidence_fingerprint:
        return False
    if previous.get("content_hash") != _content_hash(output_path):
        return False
    if previous.get("reporter_id") != str(reporter.get("persona_id") or ""):
        return False
    if previous.get("model") != model or previous.get("writer_mode") != "automatic_llm":
        return False
    if _artifact_reasoning_effort(previous) not in {"", str(reasoning_effort or "").strip().lower()}:
        return False
    source = previous.get("source") if isinstance(previous.get("source"), dict) else {}
    return (
        str(editor_mode or "deterministic").strip().lower() == "llm"
        and str(source.get("editor_mode") or "deterministic").strip().lower() == "llm"
    )


def _artifact_reasoning_effort(previous: Mapping[str, Any] | None) -> str:
    """Read the effort used for an older article without breaking legacy receipts."""

    if not isinstance(previous, Mapping):
        return ""
    source = previous.get("source") if isinstance(previous.get("source"), Mapping) else {}
    llm = source.get("llm") if isinstance(source.get("llm"), Mapping) else {}
    if llm.get("reasoning_effort"):
        return str(llm.get("reasoning_effort") or "").strip().lower()
    metadata = previous.get("generation_metadata") if isinstance(previous.get("generation_metadata"), Mapping) else {}
    return str(metadata.get("reasoning_effort") or "").strip().lower()


def _existing_article_writer_output(path: Path) -> dict[str, Any] | None:
    """Rehydrate the validated writer payload stored beside a held article."""

    structured = _article_front_matter_json(path, "article_payload_json")
    narrative = _article_narrative_from_file(path)
    if not structured or not narrative:
        return None
    output = dict(structured)
    output["narrative_markdown"] = narrative
    output["cited_evidence_ids"] = list(
        structured.get("evidence_ids")
        or structured.get("cited_evidence_ids")
        or []
    )
    return output


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
                final_status = (
                    _base_status("complete", result.get("message", f"{name} complete."), job=name)
                    | result
                    | {"stage": "complete", "completed_at": _now()}
                )
                _write_status(_carry_forward_status_context(final_status))
            except Exception as exc:  # pragma: no cover - status path is the behavior under test.
                prior_status = _safe_json(STATUS_PATH)
                failure_status = _base_status("failed", f"{name} failed: {exc}", job=name) | {
                    "stage": "failed",
                    "last_stage": str(prior_status.get("stage") or "unknown"),
                    "failed_at": _now(),
                    "error_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                }
                _write_status(_carry_forward_status_context(failure_status, prior_status))
            finally:
                _ACTIVE_JOB = False


def _carry_forward_status_context(
    payload: dict[str, Any],
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep safe progress fields when a wrapper changes the terminal state."""

    previous = prior if isinstance(prior, dict) else _safe_json(STATUS_PATH)
    for field in _STATUS_CONTEXT_FIELDS:
        if field not in payload and field in previous:
            payload[field] = previous[field]
    return payload


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
    writer_preferences: dict[str, Any] | None = None,
    edition_run_id: str = "",
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
            "reality_check": result.get("reality_check", {}) if isinstance(result, dict) else {},
            "reporter": {
                "persona_id": reporter.get("persona_id", "") if isinstance(reporter, dict) else "",
                "name": reporter.get("name", "") if isinstance(reporter, dict) else "",
            },
        }
    current_label = current_article.title if current_article is not None else "Preparing the newsroom"
    if current_article is not None:
        current_label = f"{current_article.title} ({completed_count}/{total_count})"
    progress = (
        _base_status(
            "running",
            f"{current_label} is in progress.",
            job="generate-insights",
        )
        | {
            "stage": "writing",
            "provider": writer_api_configuration().get("provider", ""),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "timeout_seconds": llm_timeout_seconds(),
            "editor_mode": editor_mode,
            "completed_count": completed_count,
            "total_count": total_count,
            "current_article": current_article.key if current_article is not None else "",
            "current_reporter": (
                persona_metadata(writer_preferences or {}, current_article.key)
                if current_article is not None
                else {}
            ),
            "edition_run_id": edition_run_id,
            "articles": article_receipts,
        }
    )
    _write_status(_carry_forward_status_context(progress))


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

    # Status receipts are shared by the web workers through the durable data
    # root.  A request can therefore read a running receipt written by a
    # different worker even though this interpreter has no active thread. Do
    # not convert that receipt into a false failure while its recorded owner
    # process is still alive. A missing, malformed, or dead owner remains an
    # orphan and is recovered below.
    owner_pid = _status_owner_pid(payload)
    if owner_pid and owner_pid != os.getpid() and _owner_process_is_alive(owner_pid):
        return payload
    recovered = dict(payload)
    recovered.update(
        {
            "state": "failed",
            "message": "The previous operator job was interrupted before completion; retry the run.",
            "updated_at": _now(),
            "stage": "interrupted",
            "last_stage": str(payload.get("stage") or "unknown"),
            "recovered_from_restart": True,
        }
    )
    edition_run_id = str(payload.get("edition_run_id") or "")
    if edition_run_id:
        try:
            from app import db as app_db

            app_db.interrupt_edition_run(
                edition_run_id,
                resume_stage=str(payload.get("stage") or ""),
            )
        except Exception:  # noqa: BLE001 - recovery must still write the JSON receipt.
            pass
    _write_json(status_path, recovered)
    return recovered


def _status_owner_pid(payload: dict[str, Any]) -> int:
    try:
        owner_pid = int(payload.get("owner_pid") or 0)
    except (TypeError, ValueError):
        return 0
    return owner_pid if owner_pid > 0 else 0


def _owner_process_is_alive(owner_pid: int) -> bool:
    """Return whether a different worker still owns a running receipt."""

    try:
        os.kill(owner_pid, 0)
    except PermissionError:
        # The process exists but this worker cannot signal it.
        return True
    except (ProcessLookupError, OSError, ValueError):
        return False
    return True


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
