from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.refresh_all import main as refresh_all
from scripts.serve import main as serve_site
from src.utils import SITE_DIR, ensure_dirs


# Written into SITE_DIR so it is served statically at /refresh_status.json. The startup
# data refresh runs in a background thread; if it hangs or crashes, the health check on "/"
# still returns 200 for the boot page, so Railway never notices and the site is stuck on
# "refresh is running" forever. This status file (plus the error page below) makes the real
# outcome visible over HTTP instead of only in container logs we may not be able to read live.
REFRESH_STATUS_PATH = SITE_DIR / "refresh_status.json"
REFRESH_WATCHDOG_SECONDS = 600


def main() -> None:
    ensure_dirs()
    refresh_on_start = os.environ.get("FANTASY_REFRESH_ON_START", "missing").lower()
    force_refresh = os.environ.get("FANTASY_FORCE_REFRESH", "false").lower() == "true"
    sync_refresh = os.environ.get("FANTASY_SYNC_REFRESH_ON_START", "false").lower() == "true"
    needs_refresh = force_refresh or refresh_on_start in {"1", "true", "yes", "always"}
    needs_refresh = needs_refresh or (refresh_on_start == "missing" and not (SITE_DIR / "index.html").exists())

    if not (SITE_DIR / "index.html").exists():
        write_boot_page(SITE_DIR)

    if needs_refresh and sync_refresh:
        _run_refresh(force_refresh)
    elif needs_refresh:
        _write_refresh_status("running", "Background data refresh in progress.")
        thread = threading.Thread(target=_run_refresh, args=(force_refresh,), daemon=True)
        thread.start()
        _start_watchdog()
    else:
        _write_refresh_status("skipped", "Existing site served; no startup refresh requested.")

    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0")
    serve_site(port=port, host=host)


def write_boot_page(site_dir: Path = SITE_DIR) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    path = site_dir / "index.html"
    path.write_text(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fantasy Dominator</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 32px; background: #f6f7f3; color: #15171a; }
    main { max-width: 720px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    p { color: #626a73; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <h1>Fantasy Dominator</h1>
    <p>The app is online. Data refresh is running; reload shortly for the full dynasty front office.</p>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def _run_refresh(force_refresh: bool) -> None:
    _write_refresh_status("running", "Background data refresh in progress.")
    try:
        print("Starting background data refresh", flush=True)
        refresh_all(force=force_refresh)
        _write_refresh_status("complete", "Background data refresh complete.")
        print("Background data refresh complete", flush=True)
    except Exception as exc:  # noqa: BLE001 - we want to surface *any* refresh failure, not just expected ones.
        tb = traceback.format_exc()
        _write_refresh_status("failed", f"{type(exc).__name__}: {exc}", traceback_text=tb)
        _write_error_page(exc, tb)
        print("Background data refresh failed", flush=True)
        print(tb, flush=True)


def _start_watchdog() -> None:
    def watch() -> None:
        time.sleep(REFRESH_WATCHDOG_SECONDS)
        status = _read_refresh_status()
        if status.get("state") == "running":
            _write_refresh_status(
                "stalled",
                f"Refresh has been running for over {REFRESH_WATCHDOG_SECONDS}s without completing "
                "or raising -- most likely blocked on a slow or unreachable external source.",
            )

    threading.Thread(target=watch, daemon=True).start()


def _write_refresh_status(state: str, message: str, traceback_text: str | None = None) -> None:
    payload = {
        "state": state,
        "message": message,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if traceback_text:
        payload["traceback"] = traceback_text
    try:
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        REFRESH_STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _read_refresh_status() -> dict:
    try:
        return json.loads(REFRESH_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_error_page(exc: Exception, tb: str) -> None:
    # Replace the misleading "refresh is running" boot page with an honest error page once the
    # refresh has actually failed. Keeps the real technical detail visible (and curl-able) so the
    # failure can be diagnosed without live container-log access.
    updated_at = datetime.now(timezone.utc).isoformat()
    safe_tb = (
        tb.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    try:
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        (SITE_DIR / "index.html").write_text(
            f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fantasy Dominator</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 32px; background: #f6f7f3; color: #15171a; }}
    main {{ max-width: 860px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    p {{ color: #626a73; line-height: 1.5; }}
    pre {{ background: #14171a; color: #e6e6e6; padding: 16px; border-radius: 8px; overflow: auto; font-size: 13px; line-height: 1.4; }}
    code {{ color: #a23f2d; }}
  </style>
</head>
<body>
  <main>
    <h1>Fantasy Dominator</h1>
    <p>The startup data refresh failed, so the full site could not be built. This page will be replaced automatically the next time a refresh succeeds. Details below.</p>
    <p><strong>{type(exc).__name__}:</strong> <code>{str(exc).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</code></p>
    <p>Updated at {updated_at}</p>
    <pre>{safe_tb}</pre>
  </main>
</body>
</html>
""",
            encoding="utf-8",
        )
    except OSError:
        pass


if __name__ == "__main__":
    main()
