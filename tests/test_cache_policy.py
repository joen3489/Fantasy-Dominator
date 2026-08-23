from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from src.news import build_news_tables
from src.sleeper_api import SleeperAPI
from src.browser_site import _safe_cache_path


class CachePolicyTests(unittest.TestCase):
    def test_browser_audit_path_does_not_expose_host_filesystem(self) -> None:
        self.assertEqual(
            _safe_cache_path(r"C:\Users\joeno\OneDrive\Documents\Fantasy Football\data\raw_external\news\2026\feed.xml"),
            "data/raw_external/news/2026/feed.xml",
        )
        self.assertEqual(_safe_cache_path("/app/data/raw_external/feed.json"), "data/raw_external/feed.json")
        self.assertEqual(_safe_cache_path(""), "")

    def test_expired_current_sleeper_cache_refetches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            cache_path = raw_dir / "2026" / "league_league-1.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(json.dumps({"name": "old"}), encoding="utf-8")
            expired_at = (datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp()
            os.utime(cache_path, (expired_at, expired_at))

            response = MagicMock()
            response.json.return_value = {"name": "fresh"}
            response.raise_for_status.return_value = None
            with patch("src.sleeper_api.requests.Session.get", return_value=response) as request:
                api = SleeperAPI(
                    raw_dir=raw_dir,
                    current_season="2026",
                    live_cache_max_age_seconds=60,
                )
                payload = api.league("2026", "league-1")

            self.assertEqual(payload["name"], "fresh")
            request.assert_called_once()

    def test_fresh_historical_cache_stays_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            cache_path = raw_dir / "2025" / "league_league-1.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(json.dumps({"name": "historical"}), encoding="utf-8")

            with patch("src.sleeper_api.requests.Session.get") as request:
                api = SleeperAPI(
                    raw_dir=raw_dir,
                    current_season="2026",
                    historical_cache_max_age_seconds=86400,
                )
                payload = api.league("2025", "league-1")

            self.assertEqual(payload["name"], "historical")
            request.assert_not_called()

    def test_league_payload_caches_are_isolated_by_league_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            responses = {
                "/league/league-a": {"name": "League A"},
                "/league/league-b": {"name": "League B"},
                "/league/league-a/rosters": [{"roster_id": 2, "owner_id": "user-a"}],
                "/league/league-b/rosters": [{"roster_id": 7, "owner_id": "user-a"}],
            }

            def response_for(url: str, *args, **kwargs) -> MagicMock:
                response = MagicMock()
                response.json.return_value = responses[url.split("/v1", 1)[-1]]
                response.raise_for_status.return_value = None
                return response

            with patch("src.sleeper_api.requests.Session.get", side_effect=response_for) as request:
                api = SleeperAPI(raw_dir=raw_dir, current_season="2026")
                self.assertEqual(api.league("2026", "league-a")["name"], "League A")
                self.assertEqual(api.league("2026", "league-b")["name"], "League B")
                self.assertEqual(api.rosters("2026", "league-a")[0]["roster_id"], 2)
                self.assertEqual(api.rosters("2026", "league-b")[0]["roster_id"], 7)

            self.assertEqual(request.call_count, 4)
            self.assertTrue((raw_dir / "2026" / "league_league-a.json").is_file())
            self.assertTrue((raw_dir / "2026" / "league_league-b.json").is_file())
            self.assertTrue((raw_dir / "2026" / "rosters_league-a.json").is_file())
            self.assertTrue((raw_dir / "2026" / "rosters_league-b.json").is_file())

    def test_stale_rotowire_cache_is_kept_but_marked_limited_on_failure(self) -> None:
        xml = """
        <rss><channel><item>
          <title>Jayden Daniels: role update</title>
          <description>Jayden Daniels has a role update.</description>
          <link>https://example.test/news/1</link>
          <pubDate>Sat, 22 Aug 2026 12:00:00 GMT</pubDate>
        </item></channel></rss>
        """
        players = {"1": {"full_name": "Jayden Daniels", "position": "QB", "team": "WAS"}}

        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            cache_path = cache_root / "news" / "2026" / "rotowire_nfl_rss.xml"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(xml, encoding="utf-8")
            expired_at = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
            os.utime(cache_path, (expired_at, expired_at))

            with patch.dict(os.environ, {"FRONT_OFFICE_NEWS_CACHE_MAX_AGE_SECONDS": "60"}), patch(
                "src.news.RAW_EXTERNAL_DIR", cache_root
            ), patch("src.news.requests.get", side_effect=RuntimeError("news unavailable")):
                tables = build_news_tables(
                    {"current_season": "2026", "news_sources": {"enabled": ["rotowire_rss"]}},
                    MagicMock(),
                    players,
                    teams=pd.DataFrame(),
                    roster_players=pd.DataFrame(),
                )

        self.assertEqual(len(tables["news_events"]), 1)
        self.assertTrue(str(tables["news_source_freshness"].iloc[0]["status"]).startswith("stale_after_refresh_error"))


if __name__ == "__main__":
    unittest.main()
