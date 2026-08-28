"""Durable worker for queued Fantasy Dominator newsroom editions.

The API can enqueue an edition without holding a web request open.  This
process claims one edition lease, runs only the unfinished desks, and publishes
only through the existing authenticated bundle seam.  The current deployment
must point the worker at the same durable database and private data root as the
web service; a second worker must not be attached to an unproven SQLite volume.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.main import _generate_insights_job
from src import operator
from src.articles import ARTICLES


def _worker_id(explicit: str = "") -> str:
    value = str(explicit or os.environ.get("FRONT_OFFICE_WORKER_ID", "")).strip()
    if value:
        return value[:120]
    return f"newsroom-{socket.gethostname()}-{os.getpid()}"


def _poll_seconds(explicit: float | None = None) -> float:
    raw = explicit if explicit is not None else os.environ.get("FRONT_OFFICE_WORKER_POLL_SECONDS", "5")
    try:
        return max(1.0, min(float(raw), 60.0))
    except (TypeError, ValueError):
        return 5.0


def run_once(worker_id: str) -> dict[str, Any] | None:
    """Claim and process one queued edition, or return ``None`` when idle."""

    db.heartbeat_newsroom_worker(worker_id, state="idle")
    run = db.claim_next_edition_run(worker_id, lease_seconds=operator.worker_lease_seconds())
    if not run:
        return None
    run_id = str(run.get("run_id") or "")
    user_id = int(run.get("user_id") or 0)
    league_id = str(run.get("league_id") or "")
    db.heartbeat_newsroom_worker(worker_id, state="working", run_id=run_id)
    league = db.get_user_league(user_id, league_id)
    if not league:
        db.update_edition_run(
            run_id,
            state="failed",
            stage="worker",
            failure_class="league_not_found",
            failure_message="The queued edition no longer has an owned league row.",
            complete=True,
            worker_id=worker_id,
        )
        db.heartbeat_newsroom_worker(worker_id, state="idle")
        return {"state": "failed", "edition_run_id": run_id, "message": "League row not found."}

    requested = {
        str(value).strip()
        for value in (run.get("requested_article_keys") or [])
        if str(value).strip()
    }
    requested &= {article.key for article in ARTICLES}
    jobs = run.get("jobs") if isinstance(run.get("jobs"), list) else []
    retry_keys = operator.edition_resume_article_keys(run, requested or {article.key for article in ARTICLES})
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    resume_stage = str(metadata.get("resume_stage") or "").strip().lower()
    skip_refresh = bool(jobs) and resume_stage not in {"refreshing", "queued"}
    article_keys = retry_keys or requested or None

    try:
        result = _generate_insights_job(
            league,
            user_id,
            article_keys=article_keys,
            edition_run_id_override=run_id,
            skip_refresh=skip_refresh,
            worker_id=worker_id,
        )
    except Exception as exc:  # noqa: BLE001 - leave the run resumable after worker failure.
        if db.edition_run_cancel_requested(run_id):
            db.cancel_edition_run(
                run_id,
                worker_id=worker_id,
                message="Edition cancelled while the worker was stopping.",
            )
        db.interrupt_edition_run(
            run_id,
            resume_stage=str(run.get("stage") or "worker"),
            failure_message=f"Worker stopped during the edition: {type(exc).__name__}.",
            worker_id=worker_id,
        )
        db.heartbeat_newsroom_worker(worker_id, state="idle")
        return {
            "state": "interrupted",
            "edition_run_id": run_id,
            "message": "Worker stopped; the edition remains resumable.",
        }
    db.heartbeat_newsroom_worker(worker_id, state="idle")
    return result | {"edition_run_id": run_id}


def main(*, once: bool = False, poll_seconds: float | None = None, worker_id: str = "") -> int:
    db.init_db()
    identity = _worker_id(worker_id)
    delay = _poll_seconds(poll_seconds)
    while True:
        result = run_once(identity)
        if result is not None:
            print(
                f"newsroom worker {identity}: {result.get('state', 'unknown')} "
                f"run={result.get('edition_run_id', '')}",
                flush=True,
            )
        elif once:
            return 0
        if once:
            return 0
        time.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process queued Fantasy Dominator newsroom editions.")
    parser.add_argument("--once", action="store_true", help="claim at most one edition and exit")
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--worker-id", default="")
    args = parser.parse_args()
    raise SystemExit(main(once=args.once, poll_seconds=args.poll_seconds, worker_id=args.worker_id))
