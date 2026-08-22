from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .utils import RAW_DIR, RAW_EXTERNAL_DIR, cache_is_fresh, dump_json, load_json


class SleeperAPIError(RuntimeError):
    """Raised when a Sleeper API request fails."""


class SleeperAPI:
    BASE_URL = "https://api.sleeper.app/v1"
    DEFAULT_LIVE_CACHE_MAX_AGE_SECONDS = 15 * 60
    DEFAULT_HISTORICAL_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
    DEFAULT_PLAYER_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        raw_dir: Path = RAW_DIR,
        timeout: int = 30,
        current_season: str | None = None,
        live_cache_max_age_seconds: int | None = None,
        historical_cache_max_age_seconds: int | None = None,
        player_cache_max_age_seconds: int | None = None,
    ) -> None:
        self.raw_dir = raw_dir
        self.timeout = timeout
        self.session = requests.Session()
        self.current_season = str(
            current_season
            or os.environ.get("FRONT_OFFICE_CURRENT_SEASON", "")
            or datetime.now(timezone.utc).year
        )
        self.live_cache_max_age_seconds = (
            live_cache_max_age_seconds
            if live_cache_max_age_seconds is not None
            else _env_seconds("FRONT_OFFICE_LIVE_CACHE_MAX_AGE_SECONDS", self.DEFAULT_LIVE_CACHE_MAX_AGE_SECONDS)
        )
        self.historical_cache_max_age_seconds = (
            historical_cache_max_age_seconds
            if historical_cache_max_age_seconds is not None
            else _env_seconds(
                "FRONT_OFFICE_HISTORICAL_CACHE_MAX_AGE_SECONDS", self.DEFAULT_HISTORICAL_CACHE_MAX_AGE_SECONDS
            )
        )
        self.player_cache_max_age_seconds = (
            player_cache_max_age_seconds
            if player_cache_max_age_seconds is not None
            else _env_seconds("FRONT_OFFICE_PLAYER_CACHE_MAX_AGE_SECONDS", self.DEFAULT_PLAYER_CACHE_MAX_AGE_SECONDS)
        )

    def get(
        self,
        endpoint: str,
        cache_path: Path | None = None,
        force: bool = False,
        max_age_seconds: int | None = None,
    ) -> Any:
        if (
            cache_path
            and cache_path.exists()
            and not force
            and (max_age_seconds is None or cache_is_fresh(cache_path, max_age_seconds))
        ):
            return load_json(cache_path)

        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SleeperAPIError(f"Failed Sleeper request: {url}") from exc

        data = response.json()
        if cache_path:
            dump_json(cache_path, data)
        return data

    def user(self, username_or_id: str, force: bool = False) -> dict[str, Any]:
        return self.get(
            f"/user/{username_or_id}",
            self.raw_dir / "users" / f"{username_or_id}.json",
            force,
            self.live_cache_max_age_seconds,
        )

    def user_leagues(self, user_id: str, season: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/user/{user_id}/leagues/nfl/{season}",
            self.raw_dir / "users" / user_id / f"leagues_{season}.json",
            force,
            self._season_cache_max_age(season),
        )

    def league(self, season: str, league_id: str, force: bool = False) -> dict[str, Any]:
        return self.get(
            f"/league/{league_id}",
            self.raw_dir / season / "league.json",
            force,
            self._season_cache_max_age(season),
        )

    def users(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/league/{league_id}/users",
            self.raw_dir / season / "users.json",
            force,
            self._season_cache_max_age(season),
        )

    def rosters(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/league/{league_id}/rosters",
            self.raw_dir / season / "rosters.json",
            force,
            self._season_cache_max_age(season),
        )

    def traded_picks(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/league/{league_id}/traded_picks",
            self.raw_dir / season / "traded_picks.json",
            force,
            self._season_cache_max_age(season),
        )

    def drafts(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/league/{league_id}/drafts",
            self.raw_dir / season / "drafts.json",
            force,
            self._season_cache_max_age(season),
        )

    def draft_picks(self, season: str, draft_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/draft/{draft_id}/picks",
            self.raw_dir / season / f"draft_{draft_id}_picks.json",
            force,
            self._season_cache_max_age(season),
        )

    def transactions(self, season: str, league_id: str, week: int, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/league/{league_id}/transactions/{week}",
            self.raw_dir / season / f"transactions_week_{week:02d}.json",
            force,
            self._season_cache_max_age(season),
        )

    def players_nfl(self, cache_path: Path, force: bool = False) -> dict[str, Any]:
        return self.get("/players/nfl", cache_path, force, self.player_cache_max_age_seconds)

    def trending_players(self, season: str, trend_type: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/players/nfl/trending/{trend_type}",
            RAW_EXTERNAL_DIR / "sleeper" / season / f"trending_{trend_type}.json",
            force,
            self._season_cache_max_age(season),
        )

    def _season_cache_max_age(self, season: str) -> int:
        return (
            self.live_cache_max_age_seconds
            if str(season) == self.current_season
            else self.historical_cache_max_age_seconds
        )


def _env_seconds(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default
