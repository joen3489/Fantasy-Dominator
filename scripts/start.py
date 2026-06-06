from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.refresh_all import main as refresh_all
from scripts.serve import main as serve_site
from src.utils import SITE_DIR, ensure_dirs


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
        refresh_all(force=force_refresh)
    elif needs_refresh:
        thread = threading.Thread(target=_refresh_in_background, args=(force_refresh,), daemon=True)
        thread.start()

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


def _refresh_in_background(force_refresh: bool) -> None:
    try:
        print("Starting background data refresh", flush=True)
        refresh_all(force=force_refresh)
        print("Background data refresh complete", flush=True)
    except Exception:
        print("Background data refresh failed", flush=True)
        traceback.print_exc()


if __name__ == "__main__":
    main()
