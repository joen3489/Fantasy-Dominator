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
    "Four-Window Market Board",
    "Market decision view",
    "This week",
    "Rest of season",
    "Dynasty / career",
    "Contender vs rebuilder",
    "Repricing leads",
    "horizon-market-board",
    "Data Room",
    "Data Diagnostics",
]
BOOT_ONLY_MARKER = "Data refresh is running; reload shortly"
REQUIRED_EDITION_MARKERS = [
    "The Front Office",
    "Draft Room",
    "News Desk",
    "Data Room",
    # Design source: AGENTS.md and docs/production_runbook.md. The direct
    # league route is a real writer entry point and must bind its poller to
    # the accepted durable run rather than trusting any stale receipt.
    "operatorRunId: ''",
    "pollOperatorStatus(expectedRunId = '')",
    "The accepted writer request has no durable run receipt",
]
EXPECTED_ARTICLE_KEYS = ("daily_brief", "team_report", "market_watch", "horizon_watch", "trade_desk", "manager_intel")
FALLBACK_ARTICLE_SCHEMA_VERSION = "deterministic_fallback_v2"


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
    expected_revision = os.environ.get("FRONT_OFFICE_EXPECTED_REVISION", "").strip()
    if expected_revision and str(payload.get("revision") or "") != expected_revision:
        errors.append(
            f"running revision={payload.get('revision')!r}; expected {expected_revision!r}"
        )
    auth_mode = payload.get("auth_mode")
    development_auth_allowed = payload.get("development_auth_allowed") is True
    if auth_mode != "live" and not (auth_mode == "development" and development_auth_allowed):
        errors.append(
            f"auth_mode={auth_mode!r}; expected live Clerk keys or an explicit private development-auth opt-in"
        )
    if payload.get("auth_configuration_ready") is not True:
        errors.append("Clerk publishable key, issuer, and JWKS configuration is incomplete")
    if payload.get("public_url_ready") is not True:
        errors.append("a canonical public URL is not configured")
    if payload.get("data_root_configured") is not True:
        errors.append("FRONT_OFFICE_DATA_DIR is not configured for a durable deployment")
    if payload.get("database_present") is not True:
        errors.append("application database is not present")
    if payload.get("database_schema_ready") is not True:
        errors.append("application database schema is not ready")
    if payload.get("operator_token_configured") is not True:
        errors.append("FRONT_OFFICE_OPERATOR_TOKEN is not configured for protected writes")
    if payload.get("scheduler_enabled") is not True:
        errors.append("FRONT_OFFICE_SCHEDULER is disabled")
    if "deployment_ready" in payload and payload.get("deployment_ready") is not True:
        blockers = payload.get("deployment_blockers") or ["the deployment gate is not ready"]
        errors.append("deployment gate is not ready: " + "; ".join(str(blocker) for blocker in blockers))
    if payload.get("writer_api_configured") is not True:
        key_env = str(payload.get("writer_api_key_env") or "the configured writer API key")
        warnings.append(f"{key_env} is not configured; only deterministic editions are available")
    return errors, warnings


def validate_edition_bundle(payload: dict) -> list[str]:
    """Check that an owned edition contains facts, analysis, and source receipts."""

    errors: list[str] = []
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, dict):
        return ["edition bundle has no tables object"]
    for table in (
        "today_priority_board",
        "player_dossiers",
        "player_horizon_market_scores",
        "available_player_horizon_scores",
        "horizon_market_movements",
        "manager_dossiers",
        "manager_season_history",
        "team_asset_inventory",
        "source_freshness",
        "news_source_freshness",
        "projection_source_freshness",
    ):
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


def validate_authenticated_edition(
    payload: dict,
    expected_revision: str = "",
    expected_league_id: str = "",
) -> list[str]:
    """Validate the private identity and deployment binding, not only payload shape."""

    errors = validate_edition_bundle(payload)
    if expected_revision and str(payload.get("sourceRevision") or "") != expected_revision:
        errors.append(
            "edition bundle source revision="
            f"{payload.get('sourceRevision')!r}; expected {expected_revision!r}"
        )
    if expected_league_id and str(payload.get("leagueId") or "") != str(expected_league_id):
        errors.append(
            f"edition bundle league_id={payload.get('leagueId')!r}; expected {expected_league_id!r}"
        )
    identity = payload.get("identityReceipt") if isinstance(payload.get("identityReceipt"), dict) else {}
    if str(identity.get("status") or "").lower() not in {"verified", "verified_roster_match"}:
        errors.append("edition bundle does not carry a verified Sleeper roster receipt")
    if not str(identity.get("sleeper_user_id") or "").strip():
        errors.append("edition bundle identity receipt has no linked Sleeper user ID")
    if identity.get("roster_id") in (None, ""):
        errors.append("edition bundle identity receipt has no exact roster_id")
    errors.extend(_validate_publication_receipts(payload))
    return errors


def _validate_publication_receipts(payload: dict) -> list[str]:
    """Require the reader payload to carry the same receipt contract as the UI."""

    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    receipts = analysis.get("articleReceipts") if isinstance(analysis.get("articleReceipts"), dict) else {}
    errors: list[str] = []
    for article_key in EXPECTED_ARTICLE_KEYS:
        receipt = receipts.get(article_key)
        if not isinstance(receipt, dict):
            errors.append(f"edition bundle is missing publication receipt: {article_key}")
            continue
        mode = str(receipt.get("mode") or "").strip().lower()
        if mode not in {"deterministic_template", "automatic_llm"}:
            errors.append(f"publication receipt {article_key} has unknown mode {mode!r}")
            continue
        structured = receipt.get("structured") if isinstance(receipt.get("structured"), dict) else {}
        for field in ("headline", "thesis", "what_changed", "action"):
            if not str(structured.get(field) or "").strip():
                errors.append(f"publication receipt {article_key} is missing structured field: {field}")
        if mode == "deterministic_template":
            if structured.get("fallback_schema_version") != FALLBACK_ARTICLE_SCHEMA_VERSION:
                errors.append(f"publication receipt {article_key} has stale fallback schema")
            if not str(structured.get("lede") or "").strip():
                errors.append(f"publication receipt {article_key} is missing fallback lede")
            if not str(structured.get("visual_brief") or "").strip():
                errors.append(f"publication receipt {article_key} is missing visual direction")
        if not str(receipt.get("reporter_id") or "").strip():
            errors.append(f"publication receipt {article_key} has no reporter identity")
        if mode == "deterministic_template":
            if str(receipt.get("reporter_id") or "").strip().lower() != "front_office":
                errors.append(
                    f"publication receipt {article_key} fallback is not owned by The Front Office"
                )
            if not str(receipt.get("assigned_reporter_id") or "").strip():
                errors.append(
                    f"publication receipt {article_key} fallback has no assigned reporter lens"
                )
        editorial_review = receipt.get("editorial_review")
        if editorial_review is not None:
            if not isinstance(editorial_review, dict):
                errors.append(f"publication receipt {article_key} has an invalid editorial review")
            else:
                review_mode = str(editorial_review.get("mode") or "").strip().lower()
                review_status = str(editorial_review.get("status") or "").strip().lower()
                review_decision = str(editorial_review.get("decision") or "").strip().lower()
                if review_mode != "llm":
                    errors.append(f"publication receipt {article_key} has unknown editorial review mode {review_mode!r}")
                if review_status not in {"approved", "held"}:
                    errors.append(f"publication receipt {article_key} has unknown editorial review status {review_status!r}")
                if review_decision not in {"approve", "modify", "hold"}:
                    errors.append(f"publication receipt {article_key} has unknown editorial decision {review_decision!r}")
    return errors


def validate_paid_publication(payload: dict) -> list[str]:
    """Require a completed six-desk LLM publication for an explicit post-run check.

    The normal authenticated smoke intentionally accepts deterministic fallback
    because fallback is a valid degraded reader state.  A writer-run acceptance
    check needs a stricter contract: every registered desk must be automatic LLM
    output, approved for publication, and attributed to its assigned reporter
    lens.  This is opt-in so a missing provider run cannot turn the ordinary
    deployment health check into a false outage.
    """

    errors = _validate_publication_receipts(payload)
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    receipts = analysis.get("articleReceipts") if isinstance(analysis.get("articleReceipts"), dict) else {}
    expected_model = os.environ.get("FRONT_OFFICE_EXPECTED_WRITER_MODEL", "").strip().lower()
    for article_key in EXPECTED_ARTICLE_KEYS:
        receipt = receipts.get(article_key)
        if not isinstance(receipt, dict):
            continue
        mode = str(receipt.get("mode") or "").strip().lower()
        if mode != "automatic_llm":
            errors.append(f"paid publication receipt {article_key} is not automatic_llm")
            continue
        if str(receipt.get("publication_status") or "").strip().lower() != "approved":
            errors.append(f"paid publication receipt {article_key} is not approved")
        if expected_model and str(receipt.get("model") or "").strip().lower() != expected_model:
            errors.append(
                f"paid publication receipt {article_key} model does not match {expected_model!r}"
            )
        reporter_id = str(receipt.get("reporter_id") or "").strip().lower()
        assigned_reporter_id = str(receipt.get("assigned_reporter_id") or "").strip().lower()
        if not reporter_id or reporter_id == "front_office":
            errors.append(f"paid publication receipt {article_key} has no named reporter attribution")
        if not assigned_reporter_id:
            errors.append(f"paid publication receipt {article_key} has no assigned reporter lens")
        editorial_review = receipt.get("editorial_review")
        if isinstance(editorial_review, dict):
            if str(editorial_review.get("status") or "").strip().lower() != "approved":
                errors.append(f"paid publication receipt {article_key} is not desk-approved")
        elif str(receipt.get("editor_mode") or "").strip().lower() == "llm":
            errors.append(f"paid publication receipt {article_key} is missing its editor receipt")
    return errors


def validate_edition_manifest(payload: dict, expected_revision: str = "") -> list[str]:
    """Ensure the HTML shell's manifest is bound to the revision being checked."""

    if not isinstance(payload, dict):
        return ["edition manifest is not an object"]
    errors: list[str] = []
    if expected_revision and str(payload.get("sourceRevision") or "") != expected_revision:
        errors.append(
            "edition manifest source revision="
            f"{payload.get('sourceRevision')!r}; expected {expected_revision!r}"
        )
    identity = payload.get("identityReceipt") if isinstance(payload.get("identityReceipt"), dict) else {}
    if not str(identity.get("sleeper_user_id") or "").strip():
        errors.append("edition manifest identity receipt has no linked Sleeper user ID")
    if identity.get("roster_id") in (None, ""):
        errors.append("edition manifest identity receipt has no exact roster_id")
    return errors


def validate_storage_audit_payload(payload: dict) -> list[str]:
    """Check the operator-safe continuity receipt without exposing its contents."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["storage audit response is not an object"]
    if payload.get("database_schema_ready") is not True:
        errors.append("storage audit reports an unready SQLite schema")
    if payload.get("current_user_present") is not True:
        errors.append("storage audit cannot find the authenticated identity")
    try:
        current_leagues = int(payload.get("current_user_leagues", 0))
    except (TypeError, ValueError):
        current_leagues = 0
    if current_leagues < 1:
        errors.append("storage audit finds no leagues for the authenticated identity")
    return errors


def resolve_smoke_credentials(
    session_token: str | None = None,
    public_only: bool | None = None,
) -> tuple[str, bool]:
    """Resolve the authenticated gate, failing closed unless public-only is explicit."""

    token = session_token or os.environ.get("FRONT_OFFICE_SESSION_TOKEN", "").strip()
    if token:
        return token, False

    if public_only is None:
        public_only = os.environ.get("FRONT_OFFICE_PUBLIC_ONLY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if public_only:
        return "", True

    raise SystemExit(
        "Authenticated smoke not done: FRONT_OFFICE_SESSION_TOKEN is missing. "
        "Set it for the deployment gate, or set FRONT_OFFICE_PUBLIC_ONLY=1 "
        "for an explicit public-only diagnostic."
    )


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

    token, _ = resolve_smoke_credentials(session_token=session_token)
    if not token:
        print(
            f"Public smoke passed for {base_url} ({health.status_code} health, {login.status_code} login). "
            "Authenticated smoke not run because FRONT_OFFICE_PUBLIC_ONLY is enabled."
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

    league_links = list(dict.fromkeys(re.findall(r'href="(/league/[A-Za-z0-9_-]+/)"', response.text)))
    if not league_links:
        raise SystemExit("Authenticated smoke failed: home page exposes no owned league edition link")
    for league_link in league_links:
        league_id_match = re.fullmatch(r"/league/([^/]+)/", league_link)
        league_id = league_id_match.group(1) if league_id_match else ""
        edition = _get(
            f"{base_url}{league_link}",
            cookies={"__session": token},
            timeout=30,
            allow_redirects=False,
        )
        if edition.status_code != 200:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}{league_link}: expected 200, got {edition.status_code}"
            )
        missing = [marker for marker in REQUIRED_EDITION_MARKERS if marker not in edition.text]
        if missing:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}{league_link}: missing edition markers {missing}"
            )
        bundle = _get(
            f"{base_url}{league_link}data/app_bundle.json",
            cookies={"__session": token},
            timeout=30,
            allow_redirects=False,
        )
        if bundle.status_code != 200:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}{league_link}data/app_bundle.json: "
                f"expected 200, got {bundle.status_code}"
            )
        try:
            bundle_payload = bundle.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Authenticated smoke failed for {base_url}{league_link}: edition fact bundle was not JSON") from exc
        bundle_errors = validate_authenticated_edition(
            bundle_payload,
            expected_revision=os.environ.get("FRONT_OFFICE_EXPECTED_REVISION", "").strip(),
            expected_league_id=league_id,
        )
        require_paid = os.environ.get("FRONT_OFFICE_REQUIRE_LLM_PUBLICATION", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if require_paid:
            bundle_errors.extend(validate_paid_publication(bundle_payload))
        if bundle_errors:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}{league_link}data/app_bundle.json: {'; '.join(bundle_errors)}"
            )
        manifest = _get(
            f"{base_url}{league_link}data/manifest.json",
            cookies={"__session": token},
            timeout=30,
            allow_redirects=False,
        )
        if manifest.status_code != 200:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}{league_link}data/manifest.json: "
                f"expected 200, got {manifest.status_code}"
            )
        try:
            manifest_payload = manifest.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Authenticated smoke failed for {base_url}{league_link}: edition manifest was not JSON") from exc
        manifest_errors = validate_edition_manifest(
            manifest_payload,
            expected_revision=os.environ.get("FRONT_OFFICE_EXPECTED_REVISION", "").strip(),
        )
        if manifest_errors:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}{league_link}data/manifest.json: {'; '.join(manifest_errors)}"
            )
        print(f"Authenticated smoke passed for {base_url}{league_link} ({edition.status_code}, {len(edition.text)} bytes)")

    operator_token = os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN", "").strip()
    if operator_token:
        audit = _get(
            f"{base_url}/api/operator/storage-audit",
            cookies={"__session": token},
            headers={"x-front-office-token": operator_token},
            timeout=30,
            allow_redirects=False,
        )
        if audit.status_code != 200:
            raise SystemExit(
                f"Authenticated smoke failed for {base_url}/api/operator/storage-audit: "
                f"expected 200, got {audit.status_code}"
            )
        try:
            audit_payload = audit.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SystemExit("Authenticated smoke failed: storage audit was not JSON") from exc
        audit_errors = validate_storage_audit_payload(audit_payload)
        if audit_errors:
            raise SystemExit(f"Authenticated smoke failed: {'; '.join(audit_errors)}")
        print(
            "Authenticated storage audit passed "
            f"({audit_payload.get('current_user_leagues', 0)} current leagues, "
            f"{audit_payload.get('content_artifacts', 0)} content artifacts)"
        )
    else:
        print("Authenticated storage audit skipped; set FRONT_OFFICE_OPERATOR_TOKEN to verify mounted-store continuity.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
