from __future__ import annotations

"""Focused tests for the multi-league path and orchestration layer."""

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import refresh_all
from src.league_paths import LeaguePaths
from src.league_registry import classify_league, discover_leagues


class MultiLeagueLayerTests(unittest.TestCase):
    def test_classify_league_handles_known_and_missing_settings(self) -> None:
        self.assertEqual(classify_league({"settings": {"type": 2}}), "dynasty")
        self.assertEqual(classify_league({"settings": {"type": 1}}), "dynasty")
        self.assertEqual(classify_league({"settings": {"type": 0}}), "redraft")
        self.assertEqual(classify_league({"settings": {"best_ball": 1, "type": 2}}), "best_ball")
        self.assertEqual(classify_league({}), "redraft")

    def test_league_paths_for_league_layout_and_ensure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            leagues_root = Path(tmp) / "data" / "leagues"
            with patch("src.league_paths.LEAGUES_ROOT", leagues_root):
                paths = LeaguePaths.for_league("123")
                self.assertEqual(paths.root, leagues_root / "123")
                self.assertEqual(paths.raw_dir, leagues_root / "123" / "raw")
                self.assertEqual(paths.processed_dir, leagues_root / "123" / "processed")
                self.assertEqual(paths.analysis_dir, leagues_root / "123" / "analysis")
                self.assertEqual(paths.site_dir, leagues_root / "123" / "site")
                self.assertEqual(paths.operator_inbox_dir, leagues_root / "123" / "operator" / "inbox")

                paths.ensure()

                for path in (
                    paths.raw_dir,
                    paths.processed_dir,
                    paths.cache_dir,
                    paths.reports_dir,
                    paths.site_dir,
                    paths.analysis_dir,
                    paths.operator_inbox_dir,
                    paths.operator_outbox_dir,
                    paths.operator_status_dir,
                ):
                    self.assertTrue(path.is_dir())

    def test_discover_leagues_resolves_user_roster_and_type(self) -> None:
        api = MagicMock()
        api.user.return_value = {"user_id": "user-1"}
        api.user_leagues.return_value = [
            {
                "league_id": "league-a",
                "name": "Alpha",
                "settings": {"type": 2},
                "total_rosters": 12,
            },
            {
                "league_id": "league-b",
                "name": "Beta",
                "settings": {"best_ball": 1},
                "total_rosters": 10,
            },
        ]
        api.rosters.side_effect = [
            [{"roster_id": 4, "owner_id": "other"}, {"roster_id": 7, "owner_id": "user-1"}],
            [{"roster_id": 1, "owner_id": "other"}],
        ]

        entries = discover_leagues(api, "joe", "2026")

        self.assertEqual(
            entries,
            [
                {
                    "league_id": "league-a",
                    "name": "Alpha",
                    "season": "2026",
                    "league_type": "dynasty",
                    "roster_id": 7,
                    "total_rosters": 12,
                },
                {
                    "league_id": "league-b",
                    "name": "Beta",
                    "season": "2026",
                    "league_type": "best_ball",
                    "roster_id": None,
                    "total_rosters": 10,
                },
            ],
        )
        api.user.assert_called_once_with("joe")
        api.user_leagues.assert_called_once_with("user-1", "2026")

    def test_refresh_user_records_statuses_and_isolates_failure(self) -> None:
        entries = [
            {"league_id": "ok", "league_type": "dynasty", "roster_id": 2},
            {"league_id": "bad", "league_type": "redraft", "roster_id": 3},
            {"league_id": "skip", "league_type": "best_ball", "roster_id": 4},
        ]

        def fake_main(**kwargs: object) -> None:
            if kwargs["league_id"] == "bad":
                raise RuntimeError("boom")

        mocked_main = MagicMock(side_effect=fake_main)
        with patch.multiple(
            refresh_all,
            discover_leagues=MagicMock(return_value=entries),
            save_registry=MagicMock(),
            main=mocked_main,
        ):
            statuses = refresh_all.refresh_user("joe", "2026", force=True)

        self.assertEqual(statuses["ok"]["state"], "complete")
        self.assertEqual(statuses["ok"]["league_type"], "dynasty")
        self.assertEqual(statuses["bad"]["state"], "failed")
        self.assertIn("boom", statuses["bad"]["message"])
        self.assertNotIn("skip", statuses)
        self.assertEqual(mocked_main.call_count, 2)

    def test_refresh_all_main_keeps_legacy_defaults(self) -> None:
        signature = inspect.signature(refresh_all.main)
        self.assertEqual(signature.parameters["force"].default, False)
        self.assertIsNone(signature.parameters["league_id"].default)
        self.assertIsNone(signature.parameters["roster_id"].default)
        self.assertIsNone(signature.parameters["paths"].default)
        self.assertEqual(refresh_all.PROCESSED_DIR, Path(refresh_all.PROCESSED_DIR))


if __name__ == "__main__":
    unittest.main()
