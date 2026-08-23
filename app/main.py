from __future__ import annotations

import csv
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src import operator as front_operator
from src.attention import load_attention
from src.browser_site import browser_bundle_is_complete, browser_bundle_missing, build_browser_site
from src.context import context_from_league_row, scoped_config
from src.league_paths import LeaguePaths
from src.league_registry import discover_leagues, save_registry
from src.personas import persona_metadata, public_reporter_personas
from src.sleeper_api import SleeperAPI
from src.utils import DATA_DIR, load_config, load_json

from . import db
from .auth import current_user


templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
templates.env.cache = None


class LinkLeagueBody(BaseModel):
    sleeper_username: str
    season: str


class ToggleLeagueBody(BaseModel):
    enabled: bool | None = None


class OperatorBody(BaseModel):
    league_id: str | None = None


class TeamProfileBody(BaseModel):
    team_name: str = ""
    display_name: str = ""
    strategy_name: str = ""
    team_direction: str = ""
    contention_window: str = ""
    strategy_profile: dict[str, Any] = Field(default_factory=dict)
    writer_preferences: dict[str, Any] = Field(default_factory=dict)


class ManagerTradeProfileBody(BaseModel):
    manager_name: str = ""
    trade_style: str = ""
    preferred_assets: str = ""
    protected_assets: str = ""
    editor_note: str = ""


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        # The refresh scheduler keeps the attention queue fresh without clicks. Disabled by
        # default under tests (FRONT_OFFICE_SCHEDULER=off) and enabled in deployment via env.
        if os.environ.get("FRONT_OFFICE_SCHEDULER", "on").lower() != "off" and app.state.background_starter:
            app.state.background_starter()
        yield

    app = FastAPI(lifespan=lifespan)
    from . import scheduler as front_scheduler

    app.state.background_starter = front_scheduler.start_scheduler

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse | RedirectResponse:
        if exc.status_code in {302, 303, 307, 308} and exc.headers and exc.headers.get("Location"):
            return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        """Return boot health plus safe deployment continuity signals.

        Railway only needs ``ok`` for the health check.  The additional fields
        make the common production failure modes visible without exposing
        secrets or filesystem paths: a development Clerk key, an unset public
        URL, or an app database that is not present at boot.
        """

        publishable_key = os.environ.get("CLERK_PUBLISHABLE_KEY", "").strip()
        auth_mode = _clerk_key_mode(publishable_key)
        development_auth_allowed = _development_auth_allowed()
        auth_issuer_configured = bool(os.environ.get("CLERK_ISSUER", "").strip())
        auth_jwks_configured = bool(os.environ.get("CLERK_JWKS_URL", "").strip())
        storage = db.storage_health()
        public_url_ready = bool(
            os.environ.get("FRONT_OFFICE_PUBLIC_URL", "").strip()
            or os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
        )
        scheduler_enabled = os.environ.get("FRONT_OFFICE_SCHEDULER", "on").lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        deployment_gate = _production_gate()
        return {
            "ok": True,
            "revision": _deployment_revision(),
            "auth_mode": auth_mode,
            "development_auth_allowed": development_auth_allowed,
            "auth_issuer_configured": auth_issuer_configured,
            "auth_jwks_configured": auth_jwks_configured,
            "auth_configuration_ready": bool(publishable_key and auth_issuer_configured and auth_jwks_configured),
            "public_url_configured": bool(os.environ.get("FRONT_OFFICE_PUBLIC_URL", "").strip()),
            "public_url_ready": public_url_ready,
            "data_root_configured": bool(os.environ.get("FRONT_OFFICE_DATA_DIR", "").strip()),
            "database_present": (DATA_DIR / "app.db").is_file(),
            **storage,
            "writer_api_configured": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
            "operator_token_configured": bool(os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN", "").strip()),
            "scheduler_enabled": scheduler_enabled,
            "deployment_ready": deployment_gate["ready"],
            "deployment_blockers": deployment_gate["blockers"],
        }

    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request) -> HTMLResponse:
        publishable_key = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "publishable_key": publishable_key,
                "clerk_js_url": _clerk_js_url(publishable_key),
                "redirect_url": _public_home_url(request),
                "deployment_gate": _production_gate(),
            },
        )

    @app.post("/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        # Clerk owns the domain-scoped session cookie; clearing this app cookie is enough for v2 sign-out UX.
        response.delete_cookie("__session")
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(
        request: Request,
        league_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> HTMLResponse:
        user_id = int(user["id"])
        leagues = [_league_view(row, user_id) for row in db.list_user_leagues(user_id)]
        enabled_leagues = [league for league in leagues if league.get("enabled")]
        featured_league = next(
            (league for league in enabled_leagues if str(league.get("league_id")) == str(league_id)),
            enabled_leagues[0] if enabled_leagues else None,
        )
        attention_items = [_attention_view(item) for item in _load_attention_safe(user_id)]
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "request": request,
                "user": user,
                "leagues": leagues,
                "enabled_leagues": enabled_leagues,
                "featured_league": featured_league,
                "featured_league_id": str((featured_league or {}).get("league_id") or ""),
                "attention": attention_items,
                "queue_generated_at": attention_items[0].get("generated_at", "") if attention_items else "",
                "operator_status": _operator_status_for_user(user_id),
                "writer_personas": public_reporter_personas(),
                "writer_api_configured": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
                "continuity": _continuity_view(user_id),
                "deployment_gate": _production_gate(),
            },
        )

    @app.get("/api/attention")
    def attention(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        items = _load_attention_safe(int(user["id"]))
        generated_at = items[0].generated_at if items else ""
        return {"generated_at": generated_at, "items": [_attention_view(item) for item in items]}

    @app.get("/api/continuity")
    def continuity(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return _continuity_view(int(user["id"]))

    @app.get("/api/operator/storage-audit")
    def operator_storage_audit(
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        """Expose non-identifying store counts for production continuity repair."""

        _require_operator_access(request)
        return db.storage_audit(int(user["id"]))

    @app.post("/api/leagues/link")
    def link_leagues(body: LinkLeagueBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        _require_deployment_ready()
        entries = discover_leagues(SleeperAPI(), body.sleeper_username, body.season)
        user_id = int(user["id"])
        db.set_sleeper_username(user_id, body.sleeper_username)
        stored = [db.upsert_user_league(user_id, entry) for entry in entries]
        config = _legacy_config()
        for entry in stored:
            db.migrate_legacy_team_profile(user_id, entry, config)
        save_registry(entries, user_id=user_id)
        return {"leagues": stored}

    @app.post("/api/leagues/refresh")
    def refresh_user_leagues(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        """Refresh the signed-in user's leagues without exposing operator actions."""

        _require_deployment_ready()
        user_id = int(user["id"])
        return front_operator.start_job(
            "refresh",
            lambda: _refresh_job(None, user_id),
        )

    @app.post("/api/leagues/{league_id}/toggle")
    def toggle_league(
        league_id: str,
        body: ToggleLeagueBody | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_deployment_ready()
        row = db.toggle_league(int(user["id"]), league_id, None if body is None else body.enabled)
        if row is None:
            raise HTTPException(status_code=404, detail="league not found")
        return row

    @app.get("/api/leagues/{league_id}/profile")
    def team_profile(league_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        league = _owned_league(user, league_id)
        return db.get_team_profile(int(user["id"]), league_id) or {
            "league_id": league_id,
            "roster_id": league.get("roster_id"),
            "season": league.get("season") or "",
            "team_name": "",
            "display_name": "",
            "strategy_name": "",
            "team_direction": "",
            "contention_window": "",
            "strategy_profile": {},
            "writer_preferences": {"persona_id": "front_office", "custom_instructions": ""},
        }

    @app.put("/api/leagues/{league_id}/profile")
    def update_team_profile(
        league_id: str,
        body: TeamProfileBody,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_deployment_ready()
        league = _owned_league(user, league_id)
        profile = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        profile.update(
            {
                "roster_id": league.get("roster_id"),
                "season": league.get("season") or "",
            }
        )
        return db.upsert_team_profile(int(user["id"]), league_id, profile)

    @app.get("/api/leagues/{league_id}/manager-trade-profiles")
    def manager_trade_profiles(
        league_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        league = _owned_league(user, league_id)
        return {
            "league_id": league_id,
            "profiles": _manager_trade_profile_views(int(user["id"]), league),
        }

    @app.put("/api/leagues/{league_id}/manager-trade-profiles/{roster_id}")
    def update_manager_trade_profile(
        league_id: str,
        roster_id: int,
        body: ManagerTradeProfileBody,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_deployment_ready()
        league = _owned_league(user, league_id)
        profile = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        saved = db.upsert_manager_trade_profile(int(user["id"]), league_id, roster_id, profile)
        views = _manager_trade_profile_views(int(user["id"]), league)
        return next(
            (item for item in views if str(item.get("roster_id")) == str(roster_id)),
            saved,
        )

    @app.get("/api/leagues/{league_id}/readiness")
    def league_readiness(league_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        league = _owned_enabled_league(user, league_id)
        return _edition_readiness(int(user["id"]), league)


    @app.get("/league/{league_id}/")
    def league_index(request: Request, league_id: str, user: dict[str, Any] = Depends(current_user)) -> Response:
        return _serve_league_file(request, user, league_id, "")

    @app.get("/league/{league_id}/{path:path}")
    def league_file(request: Request, league_id: str, path: str, user: dict[str, Any] = Depends(current_user)) -> Response:
        return _serve_league_file(request, user, league_id, path)

    @app.get("/api/operator/status")
    def operator_status(
        league_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        user_id = int(user["id"])
        if league_id:
            league = _owned_enabled_league(user, league_id)
            return _operator_status_for_user(user_id, league)
        return _operator_status_for_user(user_id)

    @app.post("/api/operator/build-packet")
    def operator_build_packet(
        request: Request,
        body: OperatorBody | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_operator_access(request)
        league = _owned_enabled_league(user, body.league_id) if body and body.league_id else None
        paths = _private_paths(int(user["id"]), str(league["league_id"])) if league else None
        return front_operator.build_insight_packet(paths)

    @app.post("/api/operator/validate-insights")
    def operator_validate_insights(
        request: Request,
        body: OperatorBody | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_operator_access(request)
        league = _owned_enabled_league(user, body.league_id) if body and body.league_id else None
        paths = _private_paths(int(user["id"]), str(league["league_id"])) if league else None
        return front_operator.validate_insight_output(paths)

    @app.get("/api/operator/chat-context")
    def operator_chat_context(
        request: Request,
        league_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_operator_access(request)
        league = _owned_enabled_league(user, league_id) if league_id else None
        paths = _private_paths(int(user["id"]), str(league["league_id"])) if league else None
        return front_operator.build_chat_context_markdown(paths)

    @app.post("/api/operator/import-insights")
    def operator_import_insights(
        request: Request,
        payload: dict[str, Any],
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_operator_access(request)
        league_id = str(payload.get("league_id") or "")
        league = _owned_enabled_league(user, league_id) if league_id else None
        paths = _private_paths(int(user["id"]), league_id) if league else None
        imported = dict(payload)
        imported.pop("league_id", None)
        return front_operator.import_insight_output(imported, paths)

    @app.post("/api/operator/{action}")
    def operator_action(
        action: str,
        request: Request,
        body: OperatorBody | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if action not in {"refresh", "generate-insights", "rebuild-browser"}:
            raise HTTPException(status_code=404, detail="operator action not found")
        _require_operator_access(request)
        league = _owned_enabled_league(user, body.league_id if body else None) if body and body.league_id else None
        paths = _private_paths(int(user["id"]), str(league["league_id"])) if league else None
        if action == "refresh":
            return front_operator.start_job(
                "refresh",
                lambda: _refresh_job(league, int(user["id"])),
                paths=paths,
            )
        if action == "generate-insights":
            return front_operator.start_job(
                "generate-insights",
                lambda: _generate_insights_job(league, int(user["id"])),
                paths=paths,
            )
        return front_operator.start_job(
            "rebuild-browser",
            lambda: _rebuild_browser_job(league, int(user["id"])),
            paths=paths,
        )

    return app


def _clerk_js_url(publishable_key: str) -> str:
    """Serve clerk-js from the instance's own frontend API domain, pinned to major v5.

    The publishable key encodes that domain (base64 of "host$"). Loading a pinned
    major from the instance domain is Clerk's documented pattern; an unpinned
    @latest from a third-party CDN silently breaks on major releases.
    """
    import base64

    try:
        encoded = publishable_key.split("_")[2]
        # Clerk pads with '$' before base64; restore b64 padding then strip the sentinel.
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8").rstrip("$")
        if host:
            return f"https://{host}/npm/@clerk/clerk-js@5/dist/clerk.browser.js"
    except Exception:
        pass
    return "https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/dist/clerk.browser.js"


def _clerk_key_mode(publishable_key: str) -> str:
    """Classify the Clerk publishable key without returning the key itself."""

    if publishable_key.startswith("pk_live_"):
        return "live"
    if publishable_key.startswith("pk_test_"):
        return "development"
    return "unknown" if publishable_key else "not_configured"


def _development_auth_allowed() -> bool:
    """Return whether a private deployment explicitly permits Clerk test auth."""

    return os.environ.get("FRONT_OFFICE_ALLOW_DEVELOPMENT_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _deployment_revision() -> str:
    """Return a safe release identifier when the platform provides one."""

    for key in ("RAILWAY_GIT_COMMIT_SHA", "SOURCE_VERSION", "COMMIT_SHA", "GIT_COMMIT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value[:80]
    return ""


def _production_gate() -> dict[str, Any]:
    """Describe whether a deployed instance is safe to use as a personal headquarters.

    Local development intentionally stays open. A Railway deployment with a
    development Clerk key normally stays closed, but a private personal
    deployment may explicitly opt into that existing Clerk identity.
    """

    deployed = bool(
        os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
        or os.environ.get("RAILWAY_ENVIRONMENT", "").strip()
    )
    if not deployed:
        return {"deployed": False, "ready": True, "blockers": []}

    blockers: list[str] = []
    publishable_key = os.environ.get("CLERK_PUBLISHABLE_KEY", "").strip()
    auth_mode = _clerk_key_mode(publishable_key)
    if auth_mode != "live" and not (auth_mode == "development" and _development_auth_allowed()):
        blockers.append(
            "Use a live Clerk publishable key for production authentication, or set "
            "FRONT_OFFICE_ALLOW_DEVELOPMENT_AUTH=true for a private deployment."
        )
    if not os.environ.get("FRONT_OFFICE_DATA_DIR", "").strip():
        blockers.append("Mount the durable application volume and set FRONT_OFFICE_DATA_DIR.")
    if not db.storage_health().get("database_schema_ready"):
        blockers.append("Initialize the application database schema before opening the headquarters.")
    if not os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN", "").strip():
        blockers.append("Set FRONT_OFFICE_OPERATOR_TOKEN before enabling protected writes.")
    scheduler_value = os.environ.get("FRONT_OFFICE_SCHEDULER", "on").lower()
    if scheduler_value in {"0", "false", "no", "off"}:
        blockers.append("Enable FRONT_OFFICE_SCHEDULER for automatic league freshness.")
    return {"deployed": True, "ready": not blockers, "blockers": blockers}


def _require_deployment_ready() -> None:
    gate = _production_gate()
    if gate["deployed"] and not gate["ready"]:
        raise HTTPException(
            status_code=503,
            detail="Production setup is incomplete. Repair the deployment before linking or refreshing leagues.",
        )


def _public_home_url(request: Request) -> str:
    """Build the URL Clerk should use after sign-in.

    Railway terminates TLS before forwarding requests to the container.  A
    plain ``request.url_for`` can therefore produce ``http://...`` even when
    the user is browsing the public HTTPS URL.  Prefer an explicit canonical
    URL, then honor the trusted forwarded scheme while retaining Starlette's
    host handling for local development.
    """

    configured = os.environ.get("FRONT_OFFICE_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return f"{configured}/"
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip().strip("/")
    if railway_domain:
        return f"https://{railway_domain}/"
    url = request.url_for("home")
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if forwarded_proto in {"http", "https"}:
        url = url.replace(scheme=forwarded_proto)
    elif str(url.hostname or "").lower().endswith(".up.railway.app"):
        # Railway's public domain is HTTPS even when the internal request
        # reaches the container as plain HTTP.
        url = url.replace(scheme="https")
    return str(url)


def _require_operator_access(request: Request) -> None:
    """Require the deployment operator token for mutation/cost endpoints.

    Local development remains usable when no operator token is configured;
    production deployments set FRONT_OFFICE_OPERATOR_TOKEN and therefore fail
    closed for ordinary authenticated users.
    """

    token_required = bool(os.environ.get("FRONT_OFFICE_OPERATOR_TOKEN")) or os.environ.get(
        "FRONT_OFFICE_REQUIRE_OPERATOR_TOKEN", ""
    ).lower() in {"1", "true", "yes", "on"}
    if token_required and not front_operator.token_valid(dict(request.headers)):
        raise HTTPException(status_code=403, detail="operator authorization required")


def _owned_league(user: dict[str, Any], league_id: str) -> dict[str, Any]:
    for row in db.list_user_leagues(int(user["id"])):
        if str(row["league_id"]) == str(league_id):
            return row
    raise HTTPException(status_code=404, detail="league not found")


def _owned_enabled_league(user: dict[str, Any], league_id: str | None) -> dict[str, Any] | None:
    if league_id is None:
        return None
    row = _owned_league(user, league_id)
    if int(row["enabled"]):
        return row
    raise HTTPException(status_code=404, detail="league not found")


def _private_paths(user_id: int | str, league_id: str) -> LeaguePaths:
    return LeaguePaths.for_user_league(str(user_id), str(league_id))


def _paths_for_user_league(user: dict[str, Any], league: dict[str, Any] | None) -> LeaguePaths:
    if league is None:
        return LeaguePaths.default()
    private = _private_paths(int(user["id"]), str(league["league_id"]))
    legacy = LeaguePaths.for_league(str(league["league_id"]))
    # A failed or interrupted refresh can leave an index shell in place before
    # it writes the data bundle. Prefer a complete private edition, then a
    # complete legacy edition, before falling back to an incomplete root for a
    # truthful recovery response. An incomplete private root must not hide a
    # usable migration fallback.
    for candidate in (private, legacy):
        if browser_bundle_is_complete(candidate.site_dir):
            return candidate
    for candidate in (private, legacy):
        if (candidate.site_dir / "index.html").is_file():
            return candidate
    # Read-only migration fallback for v2 data generated before user roots
    # existed. New refreshes always use the private root below.
    return legacy if legacy.root.exists() else private


def _rebuild_missing_bundle(user: dict[str, Any], league: dict[str, Any]) -> None:
    """Synchronously rebuild a missing static bundle when processed facts exist."""

    candidates = [
        _private_paths(int(user["id"]), str(league["league_id"])),
        LeaguePaths.for_league(str(league["league_id"])),
    ]
    context = _context_for_league(int(user["id"]), league)
    config = scoped_config(load_config(), context)
    seen: set[str] = set()
    for paths in candidates:
        key = str(paths.root)
        if key in seen:
            continue
        seen.add(key)
        if browser_bundle_is_complete(paths.site_dir):
            return
        if not (paths.processed_dir / "refresh_metadata.csv").is_file():
            continue
        try:
            build_browser_site(
                paths.site_dir,
                paths.processed_dir,
                paths.analysis_dir,
                league_type=str(league.get("league_type") or "dynasty"),
                league_id=str(league.get("league_id") or ""),
                config=config,
            )
            return
        except Exception:  # noqa: BLE001 - the recovery page must remain available.
            continue


def _serve_league_file(
    request: Request,
    user: dict[str, Any],
    league_id: str,
    requested_path: str,
) -> FileResponse | HTMLResponse:
    league = _owned_enabled_league(user, league_id)
    paths = _paths_for_user_league(user, league)
    site_dir = paths.site_dir.resolve()
    target = (site_dir / (requested_path or "index.html")).resolve()
    # SECURITY: resolved path containment blocks ../ path traversal from escaping the generated league site.
    if not target.is_relative_to(site_dir):
        raise HTTPException(status_code=404, detail="league file not found")
    if target.is_dir():
        target = (target / "index.html").resolve()
        # SECURITY: repeat containment after default-document resolution to keep nested directory requests boxed in.
        if not target.is_relative_to(site_dir):
            raise HTTPException(status_code=404, detail="league file not found")
    if not target.exists() or not target.is_file() or not browser_bundle_is_complete(site_dir):
        if requested_path in {"", "index.html"} or browser_bundle_missing(site_dir):
            _rebuild_missing_bundle(user, league)
            paths = _paths_for_user_league(user, league)
            site_dir = paths.site_dir.resolve()
            target = (site_dir / (requested_path or "index.html")).resolve()
            if target.is_dir():
                target = (target / "index.html").resolve()
            if target.exists() and target.is_file():
                return FileResponse(target)
            readiness = _edition_readiness(int(user["id"]), league)
            response = templates.TemplateResponse(
                request,
                "edition_recovery.html",
                {"request": request, "user": user, "league": league, "readiness": readiness},
            )
            response.status_code = 503
            response.headers["Retry-After"] = "15"
            return response
        raise HTTPException(status_code=404, detail="league file not found")
    return FileResponse(target)


def _context_for_league(user_id: int, league: dict[str, Any]):
    profile = db.get_team_profile(user_id, str(league.get("league_id") or ""))
    manager_trade_profiles = db.list_manager_trade_profiles(
        user_id,
        str(league.get("league_id") or ""),
    )
    return context_from_league_row(
        str(user_id),
        league,
        profile,
        manager_trade_profiles=manager_trade_profiles,
    )


def _refresh_job(league: dict[str, Any] | None, user_id: int) -> dict[str, Any]:
    from scripts.refresh_all import main as refresh_all

    if league is None:
        # No league scope means "refresh my world": every linked league plus the
        # attention queue, i.e. the scheduler cycle on demand. The legacy
        # single-league refresh only runs when a specific league is named.
        from . import scheduler as front_scheduler

        front_scheduler.run_cycle(user_id=user_id)
        return {"state": "complete", "message": "All leagues refreshed and attention queue rebuilt."}
    context = _context_for_league(user_id, league)
    refresh_all(
        force=True,
        league_id=str(league["league_id"]),
        roster_id=league.get("roster_id"),
        paths=_private_paths(user_id, str(league["league_id"])),
        league_type=str(league.get("league_type") or "dynasty"),
        context=context,
    )
    return {"state": "complete", "message": "Data refresh complete."}


def _generate_insights_job(league: dict[str, Any] | None, user_id: int) -> dict[str, Any]:
    if league is None:
        _refresh_job(None, user_id)
        results: dict[str, Any] = {}
        for row in db.list_user_leagues(user_id):
            if not int(row.get("enabled")):
                continue
            paths = _private_paths(user_id, str(row["league_id"]))
            context = _context_for_league(user_id, row)
            article_result = front_operator.generate_articles_workflow(paths, context)
            _rebuild_browser_job(row, user_id)
            results[str(row["league_id"])] = article_result
        return {"state": "complete", "message": "All league writers and browser bundles rebuilt.", "leagues": results}
    _refresh_job(league, user_id)
    paths = _private_paths(user_id, str(league["league_id"]))
    context = _context_for_league(user_id, league)
    result = front_operator.generate_articles_workflow(paths, context)
    _rebuild_browser_job(league, user_id)
    return result | {"message": "League refreshed, writers run, and browser bundle rebuilt."}


def _rebuild_browser_job(league: dict[str, Any] | None, user_id: int) -> dict[str, Any]:
    if league is None:
        rebuilt = []
        for row in db.list_user_leagues(user_id):
            if not int(row.get("enabled")):
                continue
            rebuilt.append(_rebuild_browser_job(row, user_id))
        return {"state": "complete", "message": "Browser bundles rebuilt.", "leagues": rebuilt}
    paths = _private_paths(user_id, str(league["league_id"]))
    context = _context_for_league(user_id, league)
    path = build_browser_site(
        paths.site_dir,
        paths.processed_dir,
        paths.analysis_dir,
        league_type=str(league.get("league_type") or "dynasty"),
        league_id=str(league.get("league_id") or ""),
        config=scoped_config(load_config(), context),
    )
    return {"state": "complete", "message": "Browser bundle rebuilt.", "site_path": str(path.as_posix())}


def _edition_readiness(user_id: int, league: dict[str, Any]) -> dict[str, Any]:
    """Compile a truthful, user-scoped status for the league reader surface."""

    user = {"id": user_id}
    paths = _paths_for_user_league(user, league)
    bundle_path = paths.site_dir / "index.html"
    bundle_missing = browser_bundle_missing(paths.site_dir)
    bundle_exists = not bundle_missing
    refresh_status = _refresh_status(str(league.get("league_id") or ""), user_id)
    latest_run = db.latest_refresh_run(user_id, str(league.get("league_id") or ""))
    run_state = str((latest_run or {}).get("status") or "").lower()
    file_state = str((refresh_status or {}).get("state") or "").lower()
    lifecycle_state = run_state or file_state
    timestamp = str(
        (latest_run or {}).get("finished_at")
        or (latest_run or {}).get("started_at")
        or (refresh_status or {}).get("generated_at")
        or (refresh_status or {}).get("updated_at")
        or ""
    )
    if not timestamp and bundle_exists:
        try:
            timestamp = datetime.fromtimestamp(bundle_path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            timestamp = ""
    freshness = _refresh_freshness({"updated_at": timestamp}) if timestamp else "unknown"
    error = str((latest_run or {}).get("error") or (refresh_status or {}).get("message") or "")
    receipt = None
    if latest_run:
        receipt = {
            "status": latest_run.get("status"),
            "started_at": latest_run.get("started_at"),
            "finished_at": latest_run.get("finished_at"),
            "error": latest_run.get("error"),
        }

    if lifecycle_state in {"running", "queued"}:
        state, label, message, dot_class = (
            "building",
            "Building",
            "The data is refreshing now. Your edition will appear when the bundle is ready.",
            "building",
        )
    elif bundle_exists and (lifecycle_state == "failed" or freshness == "stale"):
        state, label, message, dot_class = (
            "stale",
            "Stale",
            "The last good edition is still available, but its refresh needs attention."
            if lifecycle_state != "failed"
            else "The last good edition is still available, but the latest refresh failed.",
            "stale",
        )
    elif bundle_exists:
        state, label, message, dot_class = "ready", "Ready", "The latest league edition is ready to read.", "fresh"
    else:
        state, label, message, dot_class = (
            "needs_refresh",
            "Needs refresh",
            "No league edition is available yet. Refresh from headquarters to build it."
            if lifecycle_state != "complete"
            else "The data refresh completed, but the league edition bundle is missing. Refresh to rebuild it.",
            "failed",
        )

    return {
        "league_id": str(league.get("league_id") or ""),
        "league_name": league.get("name") or league.get("league_id") or "League",
        "state": state,
        "label": label,
        "message": message,
        "dot_class": dot_class,
        "bundle_exists": bundle_exists,
        "bundle_missing": bundle_missing,
        "bundle_source": "private" if paths.user_id else "legacy",
        "updated_at": timestamp,
        "refresh_state": lifecycle_state or "unknown",
        "last_refresh": receipt,
        "error": error if lifecycle_state == "failed" else "",
    }


def _league_view(row: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
    view = dict(row)
    view["enabled"] = bool(row.get("enabled"))
    view["refresh_status"] = _refresh_status(str(row.get("league_id") or ""), user_id)
    readiness = _edition_readiness(user_id, row) if user_id is not None else None
    view["edition_readiness"] = readiness
    view["refresh_freshness"] = readiness["dot_class"] if readiness else _refresh_freshness(view["refresh_status"])
    view["editorial"] = _load_editorial_issue(user_id, view) if user_id is not None else {}
    view["source_receipt"] = _source_receipt_view(view["editorial"])
    view["writer_preview"] = (
        _load_writer_preview(user_id, view)
        if user_id is not None
        else {"available": False}
    )
    view["content_status"] = (
        db.content_artifact_status(
            user_id,
            str(row.get("league_id") or ""),
            str(row.get("season") or load_config().get("current_season") or ""),
        )
        if user_id is not None
        else {}
    )
    return view


def _load_editorial_issue(user_id: int, league: dict[str, Any]) -> dict[str, Any]:
    """Load the small reader-facing issue receipt without opening the fact bundle."""

    paths = _paths_for_user_league({"id": user_id}, league)
    path = paths.site_dir / "data" / "editorial_issue.json"
    if not path.is_file():
        return {}
    try:
        payload = load_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_writer_preview(user_id: int, league: dict[str, Any]) -> dict[str, Any]:
    """Load a short, escaped preview from this user's private Daily GM Brief.

    The headquarters may use a legacy bundle as a read-only migration fallback,
    but generated writing is personal customization.  Never source this preview
    from the shared legacy league root or from another user's workspace.
    """

    empty = {
        "available": False,
        "text": "",
        "mode": "",
        "mode_label": "Not yet published",
        "generated_at": "",
        "generated_at_label": "",
        "reporter_persona": "",
        "reporter_name": "The Front Office",
    }
    path = _private_paths(user_id, str(league.get("league_id") or "")).analysis_dir / "daily_gm_brief.md"
    if not path.is_file():
        return empty
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return empty

    front_matter: dict[str, str] = {}
    body_lines = raw.splitlines()
    if body_lines and body_lines[0].strip() == "---":
        end = next((index for index, line in enumerate(body_lines[1:], start=1) if line.strip() == "---"), None)
        if end is not None:
            for line in body_lines[1:end]:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                front_matter[key.strip()] = value.strip()
            body_lines = body_lines[end + 1 :]

    preview_lines: list[str] = []
    skipped_title = False
    for raw_line in body_lines:
        line = raw_line.strip()
        if not line:
            if preview_lines and preview_lines[-1] != "":
                preview_lines.append("")
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if not skipped_title:
                skipped_title = True
                continue
        line = line.replace("**", "").replace("__", "")
        if line.startswith("-"):
            line = f"• {line[1:].strip()}"
        preview_lines.append(line)

    preview = "\n".join(preview_lines).strip()
    if not preview:
        return empty
    if len(preview) > 900:
        preview = preview[:897].rsplit(" ", 1)[0].rstrip() + "…"

    mode = front_matter.get("model_mode", "").strip()
    mode_label = {
        "automatic_llm": "API reporter",
        "deterministic_template": "Evidence-led fallback",
    }.get(mode, "Writer output")
    generated_at = front_matter.get("generated_at", "").strip()
    generated_at_label = generated_at.replace("T", " ").replace("+00:00", " UTC")
    persona = persona_metadata({"persona_id": front_matter.get("reporter_persona", "")})
    return {
        "available": True,
        "text": preview,
        "mode": mode,
        "mode_label": mode_label,
        "generated_at": generated_at,
        "generated_at_label": generated_at_label,
        "reporter_persona": persona["persona_id"],
        "reporter_name": persona["name"],
    }


def _manager_trade_profile_views(user_id: int, league: dict[str, Any]) -> list[dict[str, Any]]:
    """Overlay private manager notes on the deterministic manager roster list."""

    league_id = str(league.get("league_id") or "")
    custom_rows = db.list_manager_trade_profiles(user_id, league_id)
    custom_by_roster = {str(row.get("roster_id")): row for row in custom_rows}
    generated: dict[str, dict[str, Any]] = {}
    candidates = (
        _private_paths(user_id, league_id),
        LeaguePaths.for_league(league_id),
    )
    for paths in candidates:
        source = paths.processed_dir / "manager_profiles.csv"
        if not source.is_file():
            continue
        try:
            with source.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    roster_id = str(row.get("roster_id") or "").strip()
                    if roster_id and roster_id not in generated:
                        generated[roster_id] = row
        except (OSError, csv.Error):
            continue
        if generated:
            break

    roster_ids = sorted(set(generated) | set(custom_by_roster), key=lambda value: (value == "", value))
    views: list[dict[str, Any]] = []
    for roster_id in roster_ids:
        source = generated.get(roster_id, {})
        custom = custom_by_roster.get(roster_id, {})
        name = str(
            custom.get("manager_name")
            or source.get("team_name")
            or source.get("display_name")
            or f"Roster {roster_id}"
        )
        views.append(
            {
                "roster_id": roster_id,
                "manager_name": name,
                "generated_manager_name": str(source.get("team_name") or source.get("display_name") or ""),
                "trade_style": str(custom.get("trade_style") or ""),
                "preferred_assets": str(custom.get("preferred_assets") or ""),
                "protected_assets": str(custom.get("protected_assets") or ""),
                "editor_note": str(custom.get("editor_note") or ""),
                "customized": bool(custom),
                "updated_at": str(custom.get("updated_at") or ""),
            }
        )
    return views


def _source_receipt_view(editorial: dict[str, Any]) -> dict[str, Any]:
    """Summarize source provenance for the headquarters without copying the data room."""

    rows = editorial.get("source_health") if isinstance(editorial, dict) else []
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def is_current(row: dict[str, Any]) -> bool:
        return row.get("healthy") is True or str(row.get("status_label") or "").lower() == "current"

    current = sum(1 for row in rows if is_current(row))
    limited = sum(1 for row in rows if str(row.get("status_label") or "").lower() == "limited")
    failed = sum(
        1
        for row in rows
        if str(row.get("status") or "").lower() in {"failed", "error"}
        or str(row.get("status_label") or "").lower() in {"failed", "error"}
    )
    news_rows = [row for row in rows if str(row.get("label") or "").lower() == "news desk"]

    def row_count(row: dict[str, Any]) -> int:
        try:
            return max(0, int(row.get("row_count") or 0))
        except (TypeError, ValueError):
            return 0

    if not rows:
        label = "No source receipt"
    elif failed:
        label = f"{current}/{len(rows)} current; {failed} failed"
    elif limited:
        label = f"{current}/{len(rows)} current; {limited} limited"
    else:
        label = f"{current}/{len(rows)} sources current"

    checked_at = max(
        (str(row.get("checked_at") or "") for row in rows),
        default="",
    )
    reporter = editorial.get("reporter_persona") if isinstance(editorial, dict) else {}
    reporter_name = reporter.get("name") if isinstance(reporter, dict) else ""
    writer_mode = (
        str(editorial.get("writer_mode") or "Evidence-led template")
        if isinstance(editorial, dict)
        else "Evidence-led template"
    )
    return {
        "label": label,
        "current": current,
        "limited": limited,
        "failed": failed,
        "total": len(rows),
        "news_current": sum(1 for row in news_rows if is_current(row)),
        "news_total": len(news_rows),
        "news_row_count": sum(row_count(row) for row in news_rows),
        "checked_at": checked_at,
        "as_of_label": str(editorial.get("as_of_label") or "Latest refresh"),
        "reporter_name": str(reporter_name or "The Front Office"),
        "writer_mode": writer_mode,
        "latest_news_published_at": str(editorial.get("latest_news_published_at") or ""),
        "latest_news_label": str(editorial.get("latest_news_label") or "Not recorded"),
    }


def _refresh_status(league_id: str, user_id: int | None = None) -> dict[str, Any] | None:
    if user_id is not None:
        private = _private_paths(user_id, league_id)
        path = private.site_dir / "refresh_status.json"
        if not path.exists():
            path = LeaguePaths.for_league(league_id).site_dir / "refresh_status.json"
    else:
        path = LeaguePaths.for_league(league_id).site_dir / "refresh_status.json"
    if not path.exists():
        return None
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _refresh_freshness(status: dict[str, Any] | None) -> str:
    if not status:
        return "unknown"
    if str(status.get("state") or "").lower() == "failed":
        return "failed"
    timestamp = str(status.get("generated_at") or status.get("updated_at") or "")
    if not timestamp:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return "fresh" if datetime.now(timezone.utc) - parsed.astimezone(timezone.utc) < timedelta(hours=24) else "stale"


def _attention_view(item: Any) -> dict[str, Any]:
    return {
        "severity": item.severity,
        "headline": item.headline,
        "detail": item.detail,
        "deep_link": item.deep_link,
        "league_id": item.league_id,
        "league_name": item.league_name,
        "league_type": item.league_type,
        "item_type": item.item_type,
        "generated_at": item.generated_at,
    }


def _load_attention_safe(user_id: int | None = None) -> list[Any]:
    try:
        return load_attention(user_id=user_id) if user_id is not None else load_attention()
    except (FileNotFoundError, OSError, ValueError):
        return []


def _legacy_config() -> dict[str, Any]:
    try:
        return load_config()
    except (OSError, ValueError):
        return {}


def _safe_operator_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep authenticated status useful without returning host filesystem details."""

    private_fields = {"packet_path", "output_path", "validated_path", "site_path", "traceback"}
    return {key: value for key, value in payload.items() if key not in private_fields}


def _operator_status_for_user(user_id: int, league: dict[str, Any] | None = None) -> dict[str, Any]:
    if league is not None:
        status = _safe_operator_status(
            front_operator.status(_private_paths(user_id, str(league["league_id"])))
        )
        return status | {
            "league_id": str(league["league_id"]),
            "league_name": league.get("name", ""),
        }

    statuses = []
    for league in db.list_user_leagues(user_id):
        if not int(league.get("enabled")):
            continue
        statuses.append(
            _safe_operator_status(front_operator.status(_private_paths(user_id, str(league["league_id"]))))
            | {"league_id": str(league["league_id"]), "league_name": league.get("name", "")}
        )
    if not statuses:
        return {"state": "idle", "message": "No enabled league workspaces yet.", "leagues": []}
    if any(item.get("state") == "running" for item in statuses):
        state = "running"
    elif any(item.get("state") == "failed" for item in statuses):
        state = "failed"
    elif any(item.get("state") == "complete" for item in statuses):
        state = "complete"
    else:
        state = "idle"
    return {"state": state, "leagues": statuses, "updated_at": max(item.get("updated_at", "") for item in statuses)}


def _continuity_view(user_id: int) -> dict[str, Any]:
    """Expose an identity/storage receipt without exposing filesystem paths."""

    leagues = db.list_user_leagues(user_id)
    profile_count = sum(1 for league in leagues if db.get_team_profile(user_id, str(league["league_id"])))
    workspace_count = sum(
        1 for league in leagues if _private_paths(user_id, str(league["league_id"])).root.is_dir()
    )
    if leagues:
        identity_state = "linked"
        identity_message = "This login has linked league workspaces."
    elif db.another_user_has_leagues(user_id):
        identity_state = "identity_check"
        identity_message = (
            "This login has no linked leagues while preserved league workspaces exist under another identity. "
            "Verify the Clerk instance before reconnecting."
        )
    else:
        identity_state = "needs_link"
        identity_message = "Link a Sleeper account to create your first league workspace."
    volume_configured = bool(os.environ.get("FRONT_OFFICE_DATA_DIR", "").strip())
    database_present = (DATA_DIR / "app.db").is_file()
    state = "durable" if volume_configured and database_present else "local_default"
    return {
        "state": state,
        "label": "Durable workspace" if state == "durable" else "Local workspace",
        "volume_configured": volume_configured,
        "database_present": database_present,
        "linked_leagues": len(leagues),
        "team_profiles": profile_count,
        "private_workspaces": workspace_count,
        "identity_state": identity_state,
        "identity_message": identity_message,
    }


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        # 0.0.0.0, not 127.0.0.1: inside the Railway container a loopback bind is
        # unreachable from the healthcheck, which fails the deploy before swap.
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8765")),
        reload=False,
    )
