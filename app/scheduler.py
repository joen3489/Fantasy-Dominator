"""In-process refresh scheduler for The Front Office v2.

The attention queue is only useful if it is fresh without anyone clicking anything, so a
daemon thread refreshes every linked user's leagues and rebuilds the cross-league queue on
an interval. Observability follows the Sprint 16 boot-fix convention: every cycle's outcome
is written to a status JSON the UI can read, and failures are loud (recorded per league and
per cycle), never silent. LLM article generation is deliberately NOT scheduled -- it stays
an explicit, user-triggered, cost-incurring action.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.refresh_all import refresh_user
from src.attention import build_user_attention, save_attention
from src.league_registry import load_registry
from src.utils import DATA_DIR, load_config

from . import db

SCHEDULER_STATUS_PATH = DATA_DIR / "scheduler_status.json"
DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60

_STARTED = threading.Event()


def refresh_interval_seconds() -> int:
    try:
        return max(300, int(os.environ.get("FRONT_OFFICE_REFRESH_INTERVAL", DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def run_cycle(now: datetime | None = None) -> dict[str, Any]:
    """One full refresh cycle: every linked user's leagues, then the attention queue.

    Pure enough to call from tests and from the operator's manual-refresh path; the thread
    wrapper below only adds timing and crash isolation.
    """
    started_at = (now or datetime.now(timezone.utc)).isoformat()
    season = str(load_config().get("current_season", ""))
    cycle: dict[str, Any] = {"state": "running", "started_at": started_at, "users": {}}
    _write_status(cycle)

    any_failure = False
    for user in db.list_users_with_sleeper():
        username = str(user.get("sleeper_username") or "")
        if not username:
            continue
        try:
            league_statuses = refresh_user(username, season)
            cycle["users"][username] = league_statuses
            if any(status.get("state") == "failed" for status in league_statuses.values()):
                any_failure = True
        except Exception as exc:  # noqa: BLE001 - one user failing must not kill the cycle.
            any_failure = True
            cycle["users"][username] = {"state": "failed", "message": f"{type(exc).__name__}: {exc}"}

    try:
        items = build_user_attention(load_registry())
        save_attention(items)
        cycle["attention_items"] = len(items)
    except Exception as exc:  # noqa: BLE001 - queue rebuild failure is loud but not fatal.
        any_failure = True
        cycle["attention_error"] = f"{type(exc).__name__}: {exc}"

    cycle["state"] = "complete_with_failures" if any_failure else "complete"
    cycle["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_status(cycle)
    return cycle


def start_scheduler() -> None:
    """Idempotent daemon-thread starter -- safe to call from app startup on every boot."""
    if _STARTED.is_set():
        return
    _STARTED.set()

    def loop() -> None:
        interval = refresh_interval_seconds()
        while True:
            try:
                run_cycle()
            except Exception:  # noqa: BLE001 - the loop itself must never die silently.
                _write_status(
                    {
                        "state": "crashed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "traceback": traceback.format_exc(),
                    }
                )
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="front-office-scheduler").start()


def load_status() -> dict[str, Any]:
    try:
        return json.loads(SCHEDULER_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "never_run"}


def _write_status(payload: dict[str, Any]) -> None:
    try:
        SCHEDULER_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEDULER_STATUS_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass
