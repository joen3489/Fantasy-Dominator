from __future__ import annotations

import sys
import os

import requests


DEFAULT_URL = "https://fantasy-dominator-production.up.railway.app/"
REQUIRED_MARKERS = [
    "The Front Office",
    "Personal Edition",
    "editorial-issue",
    "Signal pulse",
    "Show the evidence",
    "Today's Board",
    "today-priority-board",
    "brief-card",
    "Projection Board",
    "Signal Board",
    "Analyst Brief",
    "News Desk",
    "Market Gaps",
    "Market Lens Lab",
    "Data Room",
    "Data Diagnostics",
]
BOOT_ONLY_MARKER = "Data refresh is running; reload shortly"


def _assert_authenticated_surface(response: requests.Response, url: str) -> None:
    if response.status_code != 200:
        raise SystemExit(
            f"Authenticated smoke failed for {url}: expected 200, got {response.status_code}. "
            "The supplied FRONT_OFFICE_SESSION_TOKEN may be expired or belong to another Clerk instance."
        )
    html = response.text

    missing = [marker for marker in REQUIRED_MARKERS if marker not in html]
    if missing:
        raise SystemExit(f"Authenticated smoke failed for {url}: missing markers {missing}")
    if BOOT_ONLY_MARKER in html and "News Desk" not in html:
        raise SystemExit(f"Authenticated smoke failed for {url}: site is still on boot placeholder")

    print(f"Authenticated smoke passed for {url} ({response.status_code}, {len(html)} bytes)")


def main(url: str = DEFAULT_URL, session_token: str | None = None) -> None:
    base_url = url.rstrip("/")
    health = requests.get(f"{base_url}/healthz", timeout=30)
    health.raise_for_status()
    try:
        health_payload = health.json()
    except ValueError as exc:
        raise SystemExit(f"Public smoke failed for {base_url}: /healthz did not return JSON") from exc
    if health_payload.get("ok") is not True:
        raise SystemExit(f"Public smoke failed for {base_url}: /healthz reported {health_payload}")

    login = requests.get(f"{base_url}/login", timeout=30)
    login.raise_for_status()
    if "Sign in to the Front Office" not in login.text and "Auth is not configured" not in login.text:
        raise SystemExit(f"Public smoke failed for {base_url}: login surface is missing its auth marker")

    token = session_token or os.environ.get("FRONT_OFFICE_SESSION_TOKEN", "").strip()
    if not token:
        print(
            f"Public smoke passed for {base_url} ({health.status_code} health, {login.status_code} login). "
            "Authenticated smoke skipped; set FRONT_OFFICE_SESSION_TOKEN to verify a league edition."
        )
        return

    response = requests.get(
        f"{base_url}/",
        cookies={"__session": token},
        timeout=30,
        allow_redirects=False,
    )
    _assert_authenticated_surface(response, f"{base_url}/")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
