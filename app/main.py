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
from src.browser_site import (
    browser_bundle_is_complete,
    browser_bundle_missing,
    build_browser_site,
    rebuild_browser_shell,
)
from src.context import context_from_league_row, scoped_config
from src.league_paths import LeaguePaths
from src.league_registry import discover_leagues, save_registry
from src.llm import writer_api_configuration
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


class ContentInteractionBody(BaseModel):
    artifact_type: str = "article"
    artifact_key: str
    interaction_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


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
        writer_config = writer_api_configuration()
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
            "writer_api_configured": writer_config["configured"],
            "writer_provider": writer_config["provider"],
            "writer_model": writer_config["model"],
            "writer_api_key_env": writer_config["api_key_env"],
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
        requested_league_id = str(league_id or "").strip()
        remembered_league_id = db.get_selected_league_id(user_id)
        eligible_ids = {str(league.get("league_id") or "") for league in enabled_leagues}
        selected_id = next(
            (
                candidate
                for candidate in (requested_league_id, remembered_league_id)
                if candidate and candidate in eligible_ids
            ),
            str((enabled_leagues[0] if enabled_leagues else {}).get("league_id") or ""),
        )
        if selected_id and selected_id != remembered_league_id:
            db.set_selected_league_id(user_id, selected_id)
        featured_league = next(
            (league for league in enabled_leagues if str(league.get("league_id")) == selected_id),
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
                "writer_personas": public_reporter_personas(include_newsroom=True),
                "writer_api_configured": writer_api_configuration()["configured"],
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
        return _link_user_leagues(int(user["id"]), body.sleeper_username, body.season, reset_identity_labels=True)

    @app.post("/api/leagues/identity/refresh")
    def refresh_league_identity(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        """Re-derive the signed-in manager's roster IDs from their Sleeper account.

        This endpoint accepts no team name or roster selector. It uses the
        Sleeper account already linked to this Clerk user, then reconciles any
        stale profile labels before the next league refresh.
        """

        _require_deployment_ready()
        sleeper_username = str(user.get("sleeper_username") or "").strip()
        if not sleeper_username:
            raise HTTPException(status_code=409, detail="Link a Sleeper username before refreshing identity.")
        season = str(
            os.environ.get("FRONT_OFFICE_CURRENT_SEASON", "").strip()
            or load_config().get("current_season")
            or datetime.now(timezone.utc).year
        )
        return _link_user_leagues(int(user["id"]), sleeper_username, season, reset_identity_labels=True)

    @app.post("/api/leagues/refresh")
    def refresh_user_leagues(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        """Refresh the signed-in user's leagues without exposing operator actions."""

        _require_deployment_ready()
        user_id = int(user["id"])
        return front_operator.start_job(
            "refresh",
            lambda: _refresh_job(None, user_id),
        )

    @app.post("/api/leagues/{league_id}/refresh")
    def refresh_one_league(league_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        """Force-refresh one owned league after an identity recheck."""

        _require_deployment_ready()
        league = _owned_enabled_league(user, league_id)
        user_id = int(user["id"])
        return front_operator.start_job(
            "refresh",
            lambda: _refresh_and_rebuild_league(league, user_id),
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
        profile = db.get_team_profile(int(user["id"]), league_id)
        if profile is not None:
            identity_status = str(league.get("identity_status") or "unverified").lower()
            identity_verified = identity_status in {"verified", "verified_roster_match"} and league.get("roster_id") not in (None, "")
            try:
                profile_matches_identity = int(profile.get("roster_id")) == int(league.get("roster_id"))
            except (TypeError, ValueError):
                profile_matches_identity = False
            if identity_verified and profile_matches_identity:
                return profile
            # Keep strategy notes available, but never return a stale profile
            # label that the browser could mistake for the owned roster.
            return {
                **profile,
                "roster_id": league.get("roster_id"),
                "team_name": "",
                "display_name": "",
            }
        return {
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

    @app.post("/api/leagues/{league_id}/content-interactions")
    def content_interaction(
        league_id: str,
        body: ContentInteractionBody,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        """Record explicit, scoped feedback without tracking ordinary reading."""

        league = _owned_league(user, league_id)
        allowed_types = {"useful", "not_useful", "evidence_opened", "saved", "pursued", "outcome"}
        if body.interaction_type not in allowed_types:
            raise HTTPException(status_code=422, detail="Unsupported content interaction type.")
        artifact_key = str(body.artifact_key or "").strip()
        if not artifact_key or len(artifact_key) > 120:
            raise HTTPException(status_code=422, detail="artifact_key is required and must be short.")
        roster_id = league.get("roster_id")
        if roster_id in (None, ""):
            raise HTTPException(status_code=409, detail="This league does not have a verified roster scope.")
        return db.record_content_interaction(
            int(user["id"]),
            league_id,
            int(roster_id),
            body.artifact_type,
            artifact_key,
            body.interaction_type,
            body.payload,
        )

    @app.get("/api/leagues/{league_id}/content-interactions")
    def content_interactions(
        league_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        league = _owned_league(user, league_id)
        roster_id = league.get("roster_id")
        if roster_id in (None, ""):
            return {"league_id": league_id, "roster_id": None, "interactions": []}
        return {
            "league_id": league_id,
            "roster_id": int(roster_id),
            "interactions": db.list_content_interactions(int(user["id"]), league_id, int(roster_id)),
        }

    @app.get("/api/leagues/{league_id}/learning-summary")
    def learning_summary(
        league_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        league = _owned_league(user, league_id)
        roster_id = league.get("roster_id")
        if roster_id in (None, ""):
            return db.content_learning_summary(int(user["id"]), league_id)
        return db.content_learning_summary(int(user["id"]), league_id, int(roster_id))


    @app.get("/league/{league_id}/")
    def league_index(request: Request, league_id: str, user: dict[str, Any] = Depends(current_user)) -> Response:
        # A direct edition visit is also a deliberate league selection. Persist
        # it at the owned-route boundary so bookmarks, home links, and a later
        # login all converge on the same most-recently-used edition.
        _owned_enabled_league(user, league_id)
        db.set_selected_league_id(int(user["id"]), str(league_id))
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


def _link_user_leagues(
    user_id: int,
    sleeper_username: str,
    season: str,
    reset_identity_labels: bool = False,
) -> dict[str, Any]:
    """Link leagues using Sleeper ownership, never a display-name choice."""

    entries = discover_leagues(SleeperAPI(), sleeper_username, season, force=True)
    sleeper_user_ids = {
        str(entry.get("sleeper_user_id") or "")
        for entry in entries
        if entry.get("sleeper_user_id")
    }
    db.set_sleeper_account(user_id, sleeper_username, next(iter(sleeper_user_ids), None))

    stored: list[dict[str, Any]] = []
    for entry in entries:
        previous = db.get_user_league(user_id, str(entry.get("league_id") or ""))
        saved = db.upsert_user_league(user_id, entry)
        db.migrate_legacy_team_profile(user_id, saved, _legacy_config())
        db.reconcile_team_profile_identity(user_id, saved, previous, force=reset_identity_labels)
        stored.append(saved)

    save_registry(entries, user_id=user_id)
    # Identity repair must not leave an old ready bundle in front of the
    # corrected roster. Rebuild from existing processed facts immediately;
    # the normal refresh job can still fetch newer source data afterward.
    for entry in stored:
        _rebuild_browser_job(entry, user_id, allow_legacy_fallback=True)
    return {"leagues": stored, "sleeper_username": sleeper_username, "season": str(season)}


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
        if browser_bundle_is_complete(candidate.site_dir) and _bundle_matches_identity(candidate, league):
            return candidate
    for candidate in (private, legacy):
        if (candidate.site_dir / "index.html").is_file() and (candidate is private or _bundle_matches_identity(candidate, league)):
            return candidate
    # Read-only migration fallback for v2 data generated before user roots
    # existed. New refreshes always use the private root below.
    return legacy if legacy.root.exists() and _bundle_matches_identity(legacy, league) else private


def _bundle_matches_identity(paths: LeaguePaths, league: dict[str, Any]) -> bool:
    """Reject a complete bundle whose selected roster is not this league row."""

    bundle_path = paths.site_dir / "data" / "app_bundle.json"
    if not bundle_path.is_file():
        return False
    try:
        payload = load_json(bundle_path)
    except (OSError, ValueError):
        return False
    # Small empty bundles are generic migration fixtures; generated bundles
    # always contain myRosterId and identityReceipt.
    if not isinstance(payload, dict) or not payload:
        return True
    expected = league.get("roster_id")
    receipt = payload.get("identityReceipt") if isinstance(payload.get("identityReceipt"), dict) else {}
    selected = receipt.get("roster_id", payload.get("myRosterId"))
    if expected in (None, ""):
        return str(receipt.get("status") or "").lower() in {"verified", "verified_roster_match"}
    try:
        return int(selected) == int(expected)
    except (TypeError, ValueError):
        return False


def _bundle_needs_source_rebuild(site_dir: Path) -> bool:
    """Invalidate persisted generated HTML when the running source changed."""

    expected = _deployment_revision()
    if not expected:
        return False
    manifest_path = site_dir / "data" / "manifest.json"
    try:
        manifest = load_json(manifest_path)
    except (OSError, ValueError):
        return True
    if not isinstance(manifest, dict):
        return True
    return str(manifest.get("sourceRevision") or "") != expected


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
        if (
            browser_bundle_is_complete(paths.site_dir)
            and (paths is candidates[0] or _bundle_matches_identity(paths, league))
            and not _bundle_needs_source_rebuild(paths.site_dir)
        ):
            return
        if (
            browser_bundle_is_complete(paths.site_dir)
            and (paths is candidates[0] or _bundle_matches_identity(paths, league))
            and _bundle_needs_source_rebuild(paths.site_dir)
        ):
            try:
                rebuild_browser_shell(
                    paths.site_dir,
                    league_type=str(league.get("league_type") or "dynasty"),
                )
                return
            except (OSError, ValueError, TypeError):
                # Fall through to the processed-facts rebuild when the
                # preserved bundle is malformed or incomplete.
                pass
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
            manifest = load_json(paths.site_dir / "data" / "manifest.json")
            db.stamp_content_artifact_bundle(
                int(user["id"]),
                str(league.get("league_id") or ""),
                str(context.season or league.get("season") or load_config().get("current_season") or ""),
                str((manifest or {}).get("bundleRevision") or ""),
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
    source_rebuild_needed = _bundle_needs_source_rebuild(site_dir)
    if not target.exists() or not target.is_file() or not browser_bundle_is_complete(site_dir) or source_rebuild_needed:
        if requested_path in {"", "index.html"} or browser_bundle_missing(site_dir) or source_rebuild_needed:
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


def _refresh_and_rebuild_league(league: dict[str, Any], user_id: int) -> dict[str, Any]:
    result = _refresh_job(league, user_id)
    rebuilt = _rebuild_browser_job(league, user_id)
    return result | {"bundle": rebuilt}


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


def _rebuild_browser_job(
    league: dict[str, Any] | None,
    user_id: int,
    allow_legacy_fallback: bool = False,
) -> dict[str, Any]:
    if league is None:
        rebuilt = []
        for row in db.list_user_leagues(user_id):
            if not int(row.get("enabled")):
                continue
            rebuilt.append(_rebuild_browser_job(row, user_id))
        return {"state": "complete", "message": "Browser bundles rebuilt.", "leagues": rebuilt}
    paths = _private_paths(user_id, str(league["league_id"]))
    processed_dir = paths.processed_dir
    analysis_dir = paths.analysis_dir
    # Existing installations may still have their validated facts in the
    # pre-user legacy root. Build a private shell from those facts once the
    # identity is repaired so the shared fallback cannot keep serving stale
    # personalized prose. Normal refreshes will subsequently write private
    # processed and analysis data.
    if allow_legacy_fallback and not (processed_dir / "teams.csv").is_file():
        legacy = LeaguePaths.for_league(str(league["league_id"]))
        if (legacy.processed_dir / "teams.csv").is_file():
            processed_dir = legacy.processed_dir
            analysis_dir = legacy.analysis_dir
        else:
            return {"state": "skipped", "message": "No processed league facts available yet."}
    context = _context_for_league(user_id, league)
    path = build_browser_site(
        paths.site_dir,
        processed_dir,
        analysis_dir,
        league_type=str(league.get("league_type") or "dynasty"),
        league_id=str(league.get("league_id") or ""),
        config=scoped_config(load_config(), context),
    )
    try:
        manifest = load_json(paths.site_dir / "data" / "manifest.json")
        db.stamp_content_artifact_bundle(
            user_id,
            str(league.get("league_id") or ""),
            str(context.season or league.get("season") or load_config().get("current_season") or ""),
            str((manifest or {}).get("bundleRevision") or ""),
        )
    except (OSError, ValueError, TypeError):
        # The bundle itself is still useful; readiness will expose a missing
        # revision rather than turning a successful rebuild into a 500.
        pass
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
    identity_status = str(row.get("identity_status") or "unverified").lower()
    view["identity_verified"] = identity_status in {"verified", "verified_roster_match"} and row.get("roster_id") not in (None, "")
    view["identity_label"] = "Roster verified" if view["identity_verified"] else "Roster needs verification"
    view["managed_team_name"] = ""
    if user_id is not None:
        profile = db.get_team_profile(int(user_id), str(row.get("league_id") or ""))
        profile_roster_id = (profile or {}).get("roster_id")
        profile_matches_identity = False
        if view["identity_verified"]:
            try:
                profile_matches_identity = int(profile_roster_id) == int(row.get("roster_id"))
            except (TypeError, ValueError):
                profile_matches_identity = False
        # Never show a private profile label while the league identity is
        # missing or points at another roster. That was the Moose Caboose
        # regression: a stale profile became the apparent source of truth.
        if profile_matches_identity:
            view["managed_team_name"] = str((profile or {}).get("team_name") or "")
        if not view["managed_team_name"]:
            private = _private_paths(int(user_id), str(row.get("league_id") or ""))
            if _bundle_matches_identity(private, row):
                try:
                    payload = load_json(private.site_dir / "data" / "app_bundle.json")
                    receipt = payload.get("identityReceipt") if isinstance(payload, dict) else {}
                    bundle_team = payload.get("myTeamName") if isinstance(payload, dict) else ""
                    view["managed_team_name"] = str((receipt or {}).get("team_name") or bundle_team or "")
                except (OSError, ValueError):
                    pass
    view["refresh_status"] = _refresh_status(str(row.get("league_id") or ""), user_id)
    readiness = _edition_readiness(user_id, row) if user_id is not None else None
    view["edition_readiness"] = readiness
    view["refresh_freshness"] = readiness["dot_class"] if readiness else _refresh_freshness(view["refresh_status"])
    view["editorial"] = _load_editorial_issue(user_id, view) if user_id is not None else {}
    view["source_receipt"] = _source_receipt_view(view["editorial"])
    publication_receipt = _load_publication_receipt(user_id, view) if user_id is not None else {}
    view["publication_receipt"] = publication_receipt
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
            current_receipts=publication_receipt.get("article_receipts")
            if publication_receipt.get("manifest_present")
            else None,
            current_bundle_revision=str(publication_receipt.get("bundle_revision") or ""),
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


def _load_publication_receipt(user_id: int, league: dict[str, Any]) -> dict[str, Any]:
    """Read the private bundle's publication receipt for truthful status labels."""

    path = _private_paths(user_id, str(league.get("league_id") or "")).site_dir / "data" / "manifest.json"
    if not path.is_file():
        return {"manifest_present": False, "verified": False, "article_receipts": {}, "bundle_revision": ""}
    try:
        payload = load_json(path)
    except (OSError, ValueError, TypeError):
        return {"manifest_present": True, "verified": False, "article_receipts": {}, "bundle_revision": ""}
    if not isinstance(payload, dict):
        return {"manifest_present": True, "verified": False, "article_receipts": {}, "bundle_revision": ""}
    receipts = payload.get("articleReceipts")
    return {
        "manifest_present": True,
        "verified": isinstance(receipts, dict),
        "article_receipts": receipts if isinstance(receipts, dict) else {},
        "bundle_revision": str(payload.get("bundleRevision") or ""),
    }


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
        publication_receipt = _load_publication_receipt(user_id, league)
        content_status = db.content_artifact_status(
            user_id,
            str(league["league_id"]),
            str(league.get("season") or load_config().get("current_season") or ""),
            current_receipts=publication_receipt.get("article_receipts")
            if publication_receipt.get("manifest_present")
            else None,
            current_bundle_revision=str(publication_receipt.get("bundle_revision") or ""),
        )
        return status | {
            "league_id": str(league["league_id"]),
            "league_name": league.get("name", ""),
            "publication_receipt": publication_receipt,
            "content_status": content_status,
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
