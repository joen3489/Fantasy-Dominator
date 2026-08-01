from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src import operator as front_operator
from src.attention import load_attention
from src.browser_site import build_browser_site
from src.context import context_from_league_row
from src.league_paths import LeaguePaths
from src.league_registry import discover_leagues, save_registry
from src.sleeper_api import SleeperAPI
from src.utils import load_config, load_json

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
    def healthz() -> dict[str, bool]:
        return {"ok": True}

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
                "redirect_url": str(request.url_for("home")),
            },
        )

    @app.post("/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        # Clerk owns the domain-scoped session cookie; clearing this app cookie is enough for v2 sign-out UX.
        response.delete_cookie("__session")
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, user: dict[str, Any] = Depends(current_user)) -> HTMLResponse:
        user_id = int(user["id"])
        leagues = [_league_view(row, user_id) for row in db.list_user_leagues(user_id)]
        attention_items = [_attention_view(item) for item in _load_attention_safe(user_id)]
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "request": request,
                "user": user,
                "leagues": leagues,
                "enabled_leagues": [league for league in leagues if league.get("enabled")],
                "attention": attention_items,
                "queue_generated_at": attention_items[0].get("generated_at", "") if attention_items else "",
                "operator_status": _operator_status_for_user(user_id),
            },
        )

    @app.get("/api/attention")
    def attention(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        items = _load_attention_safe(int(user["id"]))
        generated_at = items[0].generated_at if items else ""
        return {"generated_at": generated_at, "items": [_attention_view(item) for item in items]}

    @app.post("/api/leagues/link")
    def link_leagues(body: LinkLeagueBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
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
            "strategy_profile": {},
            "writer_preferences": {},
        }

    @app.put("/api/leagues/{league_id}/profile")
    def update_team_profile(
        league_id: str,
        body: TeamProfileBody,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        league = _owned_league(user, league_id)
        profile = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        profile.update(
            {
                "roster_id": league.get("roster_id"),
                "season": league.get("season") or "",
            }
        )
        return db.upsert_team_profile(int(user["id"]), league_id, profile)

    @app.get("/league/{league_id}/")
    def league_index(league_id: str, user: dict[str, Any] = Depends(current_user)) -> FileResponse:
        return _serve_league_file(user, league_id, "")

    @app.get("/league/{league_id}/{path:path}")
    def league_file(league_id: str, path: str, user: dict[str, Any] = Depends(current_user)) -> FileResponse:
        return _serve_league_file(user, league_id, path)

    @app.get("/api/operator/status")
    def operator_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return _operator_status_for_user(int(user["id"]))

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
    # A failed or interrupted private refresh can leave the workspace root in
    # place before it writes the browser bundle. Prefer a complete private
    # edition, then a complete legacy edition, before falling back to whichever
    # workspace is present so an incomplete private root cannot hide a usable
    # migration fallback.
    if (private.site_dir / "index.html").is_file():
        return private
    if (legacy.site_dir / "index.html").is_file():
        return legacy
    # Read-only migration fallback for v2 data generated before user roots
    # existed. New refreshes always use the private root below.
    return legacy if legacy.root.exists() else private


def _serve_league_file(user: dict[str, Any], league_id: str, requested_path: str) -> FileResponse:
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
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="league file not found")
    return FileResponse(target)


def _context_for_league(user_id: int, league: dict[str, Any]):
    profile = db.get_team_profile(user_id, str(league.get("league_id") or ""))
    return context_from_league_row(str(user_id), league, profile)


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
    path = build_browser_site(
        paths.site_dir,
        paths.processed_dir,
        paths.analysis_dir,
        league_type=str(league.get("league_type") or "dynasty"),
        league_id=str(league.get("league_id") or ""),
    )
    return {"state": "complete", "message": "Browser bundle rebuilt.", "site_path": str(path.as_posix())}


def _league_view(row: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
    view = dict(row)
    view["enabled"] = bool(row.get("enabled"))
    view["refresh_status"] = _refresh_status(str(row.get("league_id") or ""), user_id)
    view["refresh_freshness"] = _refresh_freshness(view["refresh_status"])
    return view


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


def _operator_status_for_user(user_id: int) -> dict[str, Any]:
    statuses = []
    for league in db.list_user_leagues(user_id):
        if not int(league.get("enabled")):
            continue
        statuses.append(
            front_operator.status(_private_paths(user_id, str(league["league_id"])))
            | {"league_id": str(league["league_id"]), "league_name": league.get("name", "")}
        )
    if not statuses:
        return {"state": "idle", "message": "No enabled league workspaces yet.", "leagues": []}
    if any(item.get("state") == "running" for item in statuses):
        state = "running"
    elif any(item.get("state") == "failed" for item in statuses):
        state = "failed"
    else:
        state = "complete"
    return {"state": state, "leagues": statuses, "updated_at": max(item.get("updated_at", "") for item in statuses)}


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
