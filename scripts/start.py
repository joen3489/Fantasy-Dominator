from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.refresh_all import main as refresh_all
from scripts.serve import main as serve_site
from src.utils import SITE_DIR, ensure_dirs


def main() -> None:
    ensure_dirs()
    refresh_on_start = os.environ.get("FANTASY_REFRESH_ON_START", "missing").lower()
    force_refresh = os.environ.get("FANTASY_FORCE_REFRESH", "false").lower() == "true"

    if force_refresh or refresh_on_start in {"1", "true", "yes", "always"}:
        refresh_all(force=force_refresh)
    elif refresh_on_start == "missing" and not (SITE_DIR / "index.html").exists():
        refresh_all(force=False)

    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0")
    serve_site(port=port, host=host)


if __name__ == "__main__":
    main()
