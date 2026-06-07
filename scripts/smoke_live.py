from __future__ import annotations

import sys

import requests


DEFAULT_URL = "https://fantasy-dominator-production.up.railway.app/"
REQUIRED_MARKERS = [
    "Today's Board",
    "brief-card",
    "Projection Board",
    "Signal Board",
    "Analyst Brief",
    "News Desk",
    "Market Gaps",
    "Data Diagnostics",
]
BOOT_ONLY_MARKER = "Data refresh is running; reload shortly"


def main(url: str = DEFAULT_URL) -> None:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    html = response.text

    missing = [marker for marker in REQUIRED_MARKERS if marker not in html]
    if missing:
        raise SystemExit(f"Smoke failed for {url}: missing markers {missing}")
    if BOOT_ONLY_MARKER in html and "News Desk" not in html:
        raise SystemExit(f"Smoke failed for {url}: site is still on boot placeholder")

    print(f"Smoke passed for {url} ({response.status_code}, {len(html)} bytes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
