from __future__ import annotations

import sys
import os
import json
import re

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
REQUIRED_EDITION_MARKERS = ["The Front Office", "Draft Room", "News Desk", "Data Room"]


def _get(url: str, **kwargs: object) -> requests.Response:
    """GET through the configured network, with a direct fallback for dead proxies."""

    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.ProxyError as proxy_error:
        direct = requests.Session()
        direct.trust_env = False
        try:
            return direct.get(url, **kwargs)
        except requests.RequestException:
            raise proxy_error


def validate_health_payload(payload: dict) -> tuple[list[str], list[str]]:
    """Return blocking errors and non-blocking warnings for production health."""

    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("ok") is not True:
        errors.append(f"/healthz reported {payload}")
    if payload.get("auth_mode") != "live":
        errors.append(f"auth_mode={payload.get('auth_mode')!r}; expected live Clerk keys")
    if payload.get("auth_configuration_ready") is not True:
        errors.append("Clerk publishable key, issuer, and JWKS configuration is incomplete")
    if payload.get("data_root_configured") is not True:
        errors.append("FRONT_OFFICE_DATA_DIR is not configured for a durable deployment")
    if payload.get("database_present") is not True:
        errors.append("application database is not present")
    if payload.get("database_schema_ready") is not True:
        errors.append("application database schema is not ready")
    if payload.get("writer_api_configured") is not True:
        warnings.append("ANTHROPIC_API_KEY is not configured; only deterministic editions are available")
    return errors, warnings


def validate_edition_bundle(payload: dict) -> list[str]:
    """Check that an owned edition contains facts, analysis, and source receipts."""

    errors: list[str] = []
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, dict):
        return ["edition bundle has no tables object"]
    for table in ("today_priority_board", "player_dossiers", "source_freshness", "news_source_freshness", "projection_source_freshness"):
        if table not in tables:
            errors.append(f"edition bundle is missing {table}")
    if not tables.get("source_freshness"):
        errors.append("edition bundle has no source freshness receipt")
    if not tables.get("news_source_freshness"):
        errors.append("edition bundle has no news freshness receipt")
    if not tables.get("projection_source_freshness"):
        errors.append("edition bundle has no projection freshness receipt")
    if not payload.get("analysis"):
        errors.append("edition bundle has no analysis payload")
    if not payload.get("draftRoom"):
        errors.append("edition bundle has no Draft Room payload")
    return errors


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
    health = _get(f"{base_url}/healthz", timeout=30)
    health.raise_for_status()
    try:
        health_payload = health.json()
    except ValueError as exc:
        raise SystemExit(f"Public smoke failed for {base_url}: /healthz did not return JSON") from exc
    health_errors, health_warnings = validate_health_payload(health_payload)
    if health_errors:
        raise SystemExit(f"Public smoke failed for {base_url}: {'; '.join(health_errors)}")
    for warning in health_warnings:
        print(f"Public smoke warning for {base_url}: {warning}")

    login = _get(f"{base_url}/login", timeout=30)
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

    response = _get(
        f"{base_url}/",
        cookies={"__session": token},
        timeout=30,
        allow_redirects=False,
    )
    _assert_authenticated_surface(response, f"{base_url}/")

    continuity = _get(
        f"{base_url}/api/continuity",
        cookies={"__session": token},
        timeout=30,
        allow_redirects=False,
    )
    if continuity.status_code != 200:
        raise SystemExit(
            f"Authenticated smoke failed for {base_url}/api/continuity: expected 200, got {continuity.status_code}"
        )
    try:
        continuity_payload = continuity.json()
    except ValueError as exc:
        raise SystemExit("Authenticated smoke failed: continuity receipt was not JSON") from exc
    if continuity_payload.get("identity_state") != "linked" or int(continuity_payload.get("linked_leagues", 0)) < 1:
        raise SystemExit(
            "Authenticated smoke failed: this identity has no linked league workspace; "
            f"continuity={continuity_payload}"
        )

    league_links = re.findall(r'href="(/league/[A-Za-z0-9_-]+/)"', response.text)
    if not league_links:
        raise SystemExit("Authenticated smoke failed: home page exposes no owned league edition link")
    edition = _get(
        f"{base_url}{league_links[0]}",
        cookies={"__session": token},
        timeout=30,
        allow_redirects=False,
    )
    if edition.status_code != 200:
        raise SystemExit(
            f"Authenticated smoke failed for {base_url}{league_links[0]}: expected 200, got {edition.status_code}"
        )
    missing = [marker for marker in REQUIRED_EDITION_MARKERS if marker not in edition.text]
    if missing:
        raise SystemExit(
            f"Authenticated smoke failed for {base_url}{league_links[0]}: missing edition markers {missing}"
        )
    bundle = _get(
        f"{base_url}{league_links[0]}data/app_bundle.json",
        cookies={"__session": token},
        timeout=30,
        allow_redirects=False,
    )
    if bundle.status_code != 200:
        raise SystemExit(
            f"Authenticated smoke failed for {base_url}{league_links[0]}data/app_bundle.json: "
            f"expected 200, got {bundle.status_code}"
        )
    try:
        bundle_payload = bundle.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("Authenticated smoke failed: edition fact bundle was not JSON") from exc
    bundle_errors = validate_edition_bundle(bundle_payload)
    if bundle_errors:
        raise SystemExit(
            f"Authenticated smoke failed for {base_url}{league_links[0]}data/app_bundle.json: {'; '.join(bundle_errors)}"
        )
    print(f"Authenticated smoke passed for {base_url}{league_links[0]} ({edition.status_code}, {len(edition.text)} bytes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
