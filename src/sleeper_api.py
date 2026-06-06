from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .utils import RAW_DIR, dump_json, load_json


class SleeperAPIError(RuntimeError):
    """Raised when a Sleeper API request fails."""


class SleeperAPI:
    BASE_URL = "https://api.sleeper.app/v1"

    def __init__(self, raw_dir: Path = RAW_DIR, timeout: int = 30) -> None:
        self.raw_dir = raw_dir
        self.timeout = timeout
        self.session = requests.Session()

    def get(self, endpoint: str, cache_path: Path | None = None, force: bool = False) -> Any:
        if cache_path and cache_path.exists() and not force:
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

    def league(self, season: str, league_id: str, force: bool = False) -> dict[str, Any]:
        return self.get(f"/league/{league_id}", self.raw_dir / season / "league.json", force)

    def users(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(f"/league/{league_id}/users", self.raw_dir / season / "users.json", force)

    def rosters(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(f"/league/{league_id}/rosters", self.raw_dir / season / "rosters.json", force)

    def traded_picks(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(f"/league/{league_id}/traded_picks", self.raw_dir / season / "traded_picks.json", force)

    def drafts(self, season: str, league_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(f"/league/{league_id}/drafts", self.raw_dir / season / "drafts.json", force)

    def draft_picks(self, season: str, draft_id: str, force: bool = False) -> list[dict[str, Any]]:
        return self.get(f"/draft/{draft_id}/picks", self.raw_dir / season / f"draft_{draft_id}_picks.json", force)

    def transactions(self, season: str, league_id: str, week: int, force: bool = False) -> list[dict[str, Any]]:
        return self.get(
            f"/league/{league_id}/transactions/{week}",
            self.raw_dir / season / f"transactions_week_{week:02d}.json",
            force,
        )

    def players_nfl(self, cache_path: Path, force: bool = False) -> dict[str, Any]:
        return self.get("/players/nfl", cache_path, force)
