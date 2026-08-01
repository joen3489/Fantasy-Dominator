from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from src.articles import ArticleContext, _scope_team_report
from src.context import FantasyContext, scoped_config
from src.league_paths import LeaguePaths


class ContextIsolationTests(unittest.TestCase):
    def test_scoped_config_clears_singleton_team_customization(self) -> None:
        base = {
            "current_team": {
                "roster_id": 2,
                "display_name": "Legacy Joe",
                "team_name": "Legacy Team",
            },
            "strategy_profile": {"name": "Legacy rebuild", "team_direction": "rebuild"},
            "current_season": "2026",
        }
        context = FantasyContext(
            user_id="17",
            league_id="league-b",
            season="2026",
            roster_id=9,
            team_name="New Team",
            strategy_profile={"name": "Win now", "team_direction": "contend"},
        )

        scoped = scoped_config(base, context)

        self.assertEqual(scoped["current_team"]["roster_id"], 9)
        self.assertEqual(scoped["current_team"]["team_name"], "New Team")
        self.assertEqual(scoped["current_team"]["display_name"], "")
        self.assertEqual(scoped["strategy_profile"]["name"], "Win now")
        self.assertEqual(scoped["context"]["league_id"], "league-b")
        self.assertEqual(base["strategy_profile"]["name"], "Legacy rebuild")

    def test_user_league_paths_are_private_and_reject_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "users"
            with patch("src.league_paths.USERS_ROOT", root):
                first = LeaguePaths.for_user_league("101", "league-a")
                second = LeaguePaths.for_user_league("202", "league-a")
                self.assertNotEqual(first.root, second.root)
                self.assertEqual(first.root, root / "101" / "leagues" / "league-a")
                with self.assertRaises(ValueError):
                    LeaguePaths.for_user_league("101", "../other")

    def test_team_profiles_and_content_artifacts_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "app.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                first = db.get_or_create_user("first")
                second = db.get_or_create_user("second")
                db.upsert_team_profile(
                    int(first["id"]),
                    "league-a",
                    {
                        "roster_id": 1,
                        "season": "2026",
                        "team_name": "First Team",
                        "strategy_profile": {"team_direction": "contend"},
                    },
                )
                db.upsert_team_profile(
                    int(second["id"]),
                    "league-a",
                    {
                        "roster_id": 2,
                        "season": "2026",
                        "team_name": "Second Team",
                        "strategy_profile": {"team_direction": "rebuild"},
                    },
                )

                self.assertEqual(
                    db.get_team_profile(int(first["id"]), "league-a")["team_name"],
                    "First Team",
                )
                self.assertEqual(
                    db.get_team_profile(int(second["id"]), "league-a")["strategy_profile"]["team_direction"],
                    "rebuild",
                )
                db.record_content_artifact(
                    int(first["id"]), "league-a", "2026", "article", "market_watch", "first.md"
                )
                self.assertIsNone(db.get_team_profile(int(first["id"]), "league-b"))

    def test_legacy_profile_migration_does_not_overwrite_customization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("custom")
                db.upsert_team_profile(
                    int(user["id"]),
                    "league-a",
                    {"roster_id": 2, "season": "2026", "team_name": "Custom Team", "strategy_profile": {"name": "Contend"}},
                )
                migrated = db.migrate_legacy_team_profile(
                    int(user["id"]),
                    {"league_id": "league-a", "season": "2026", "roster_id": 2},
                    {
                        "current_team": {"roster_id": 2, "team_name": "Legacy Team"},
                        "strategy_profile": {"name": "Legacy Rebuild"},
                    },
                )

                self.assertEqual(migrated["team_name"], "Custom Team")
                self.assertEqual(db.get_team_profile(int(user["id"]), "league-a")["strategy_profile"]["name"], "Contend")

    def test_article_scope_reads_selected_processed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processed = Path(temporary) / "processed"
            analysis = Path(temporary) / "analysis"
            processed.mkdir()
            analysis.mkdir()
            with (processed / "player_dossiers.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["roster_id", "player_id", "player_name", "market_value"],
                )
                writer.writeheader()
                writer.writerow({"roster_id": "9", "player_id": "p9", "player_name": "Private Player", "market_value": "40"})

            context = ArticleContext(analysis_dir=analysis, active_roster_id=9, processed_dir=processed)
            rows = _scope_team_report(context)

            self.assertEqual([row["name"] for row in rows], ["Private Player"])


if __name__ == "__main__":
    unittest.main()
