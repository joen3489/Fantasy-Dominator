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
from pydantic import BaseModel

from src import operator as front_operator
from src.attention import load_attention
from src.browser_site import build_browser_site
from src.league_paths import LeaguePaths
from src.league_registry import discover_leagues
from src.sleeper_api import SleeperAPI
from src.utils import load_json

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
        leagues = [_league_view(row) for row in db.list_user_leagues(int(user["id"]))]
        attention_items = [_attention_view(item) for item in _load_attention_safe()]
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
                "operator_status": front_operator.status(),
            },
        )

    @app.get("/api/attention")
    def attention(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        items = _load_attention_safe()
        generated_at = items[0].generated_at if items else ""
        return {"generated_at": generated_at, "items": [_attention_view(item) for item in items]}

    @app.post("/api/leagues/link")
    def link_leagues(body: LinkLeagueBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        entries = discover_leagues(SleeperAPI(), body.sleeper_username, body.season)
        db.set_sleeper_username(int(user["id"]), body.sleeper_username)
        stored = [db.upsert_user_league(int(user["id"]), entry) for entry in entries]
        return {"leagues": stored}

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

    @app.get("/league/{league_id}/")
    def league_index(league_id: str, user: dict[str, Any] = Depends(current_user)) -> FileResponse:
        return _serve_league_file(user, league_id, "")

    @app.get("/league/{league_id}/{path:path}")
    def league_file(league_id: str, path: str, user: dict[str, Any] = Depends(current_user)) -> FileResponse:
        return _serve_league_file(user, league_id, path)

    @app.get("/api/operator/status")
    def operator_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return front_operator.status()

    @app.post("/api/operator/{action}")
    def operator_action(action: str, body: OperatorBody | None = None, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if action not in {"refresh", "generate-insights", "rebuild-browser"}:
            raise HTTPException(status_code=404, detail="operator action not found")
        league = _owned_enabled_league(user, body.league_id if body else None) if body and body.league_id else None
        if action == "refresh":
            return front_operator.start_job("refresh", lambda: _refresh_job(league))
        if action == "generate-insights":
            return front_operator.start_job("generate-insights", lambda: _generate_insights_job(league))
        return front_operator.start_job("rebuild-browser", lambda: _rebuild_browser_job(league))

    return app


def _owned_enabled_league(user: dict[str, Any], league_id: str | None) -> dict[str, Any] | None:
    if league_id is None:
        return None
    for row in db.list_user_leagues(int(user["id"])):
        if str(row["league_id"]) == str(league_id) and int(row["enabled"]):
            return row
    raise HTTPException(status_code=404, detail="league not found")


def _serve_league_file(user: dict[str, Any], league_id: str, requested_path: str) -> FileResponse:
    _owned_enabled_league(user, league_id)
    paths = LeaguePaths.for_league(league_id)
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


def _refresh_job(league: dict[str, Any] | None) -> dict[str, Any]:
    from scripts.refresh_all import main as refresh_all

    if league is None:
        refresh_all(force=True)
    else:
        refresh_all(
            force=True,
            league_id=str(league["league_id"]),
            roster_id=league.get("roster_id"),
            paths=LeaguePaths.for_league(str(league["league_id"])),
        )
    return {"state": "complete", "message": "Data refresh complete."}


def _generate_insights_job(league: dict[str, Any] | None) -> dict[str, Any]:
    if league is None:
        from scripts.refresh_all import main as refresh_all

        refresh_all(force=True)
        result = front_operator.generate_articles_workflow()
        front_operator.rebuild_browser()
        return result
    _refresh_job(league)
    _rebuild_browser_job(league)
    return {"state": "complete", "message": "League refreshed and browser bundle rebuilt."}


def _rebuild_browser_job(league: dict[str, Any] | None) -> dict[str, Any]:
    if league is None:
        return front_operator.rebuild_browser()
    paths = LeaguePaths.for_league(str(league["league_id"]))
    path = build_browser_site(paths.site_dir, paths.processed_dir, paths.analysis_dir)
    return {"state": "complete", "message": "Browser bundle rebuilt.", "site_path": str(path.as_posix())}


def _league_view(row: dict[str, Any]) -> dict[str, Any]:
    view = dict(row)
    view["enabled"] = bool(row.get("enabled"))
    view["refresh_status"] = _refresh_status(str(row.get("league_id") or ""))
    view["refresh_freshness"] = _refresh_freshness(view["refresh_status"])
    return view


def _refresh_status(league_id: str) -> dict[str, Any] | None:
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


def _load_attention_safe() -> list[Any]:
    try:
        return load_attention()
    except FileNotFoundError:
        return []


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
