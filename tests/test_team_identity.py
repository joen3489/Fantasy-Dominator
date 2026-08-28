from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.analysis import rewrite_source_team_labels_in_articles, rewrite_source_team_labels_in_structured_analysis
from src.browser_site import build_browser_site
from src.team_identity import (
    current_sleeper_team_label_migrations,
    current_sleeper_team_name,
    historical_sleeper_team_names,
    resolve_team_name,
)


class TeamIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            {
                "league_id": "current",
                "season": "2026",
                "roster_id": 2,
                "owner_id": "joe",
                "display_name": "joe3489",
                "team_name": "Lulu’s Potatoe’s",
            },
            {
                "league_id": "prior",
                "season": "2025",
                "roster_id": 2,
                "owner_id": "joe",
                "display_name": "joe3489",
                "team_name": "Melkor Lord of Light",
            },
            {
                "league_id": "other",
                "season": "2026",
                "roster_id": 2,
                "owner_id": "other-manager",
                "display_name": "other",
                "team_name": "Other roster label",
            },
        ]

    def test_current_label_is_selected_by_exact_league_season_and_roster(self) -> None:
        self.assertEqual(
            current_sleeper_team_name(
                self.rows,
                league_id="current",
                season="2026",
                roster_id=2,
            ),
            "Lulu’s Potatoe’s",
        )

    def test_historical_source_label_follows_current_name(self) -> None:
        self.assertEqual(
            resolve_team_name(
                "Melkor Lord of Light",
                self.rows,
                league_id="current",
                season="2026",
                roster_id=2,
            ),
            "Lulu’s Potatoe’s",
        )

    def test_historical_source_names_exclude_display_name_and_current_label(self) -> None:
        self.assertEqual(
            historical_sleeper_team_names(
                self.rows,
                league_id="current",
                season="2026",
                roster_id=2,
            ),
            {"Melkor Lord of Light"},
        )

    def test_preserved_article_label_rewrite_updates_body_and_receipt_hash(self) -> None:
        body = "---\nmodel_mode: automatic_llm\nteam_name: Melkor Lord of Light\n---\n# Daily GM Brief: Melkor Lord of Light\n\nThe Melkor Lord of Light edition has a live read."
        with tempfile.TemporaryDirectory() as temp_dir:
            analysis_dir = Path(temp_dir)
            (analysis_dir / "daily_gm_brief.md").write_text(body, encoding="utf-8")
            analysis = {
                "dailyGmBrief": body,
                "articleReceipts": {"daily_brief": {"mode": "automatic_llm", "content_hash": "old"}},
            }

            rewritten = rewrite_source_team_labels_in_articles(
                analysis_dir,
                analysis,
                {"Melkor Lord of Light"},
                "Lulu’s Potatoe’s",
            )

            expected_body = body.replace("Melkor Lord of Light", "Lulu’s Potatoe’s")
            self.assertEqual(rewritten["dailyGmBrief"], expected_body)
            self.assertEqual((analysis_dir / "daily_gm_brief.md").read_text(encoding="utf-8"), expected_body)
            self.assertEqual(
                rewritten["articleReceipts"]["daily_brief"]["content_hash"],
                hashlib.sha256(expected_body.encode("utf-8")).hexdigest(),
            )

    def test_genuine_custom_label_is_preserved_and_other_owner_is_not_an_alias(self) -> None:
        self.assertEqual(
            resolve_team_name(
                "My Front Office",
                self.rows,
                league_id="current",
                season="2026",
                roster_id=2,
            ),
            "My Front Office",
        )
        self.assertEqual(
            resolve_team_name(
                "Other roster label",
                self.rows,
                league_id="current",
                season="2026",
                roster_id=2,
            ),
            "Other roster label",
        )

    def test_all_current_manager_labels_follow_owner_lineage_across_roster_changes(self) -> None:
        rows = self.rows + [
            {
                "league_id": "current",
                "season": "2026",
                "roster_id": 11,
                "owner_id": "wild",
                "team_name": "The Semiquincentennials",
            },
            {
                "league_id": "prior",
                "season": "2025",
                "roster_id": 9,
                "owner_id": "wild",
                "team_name": "Threat To Democracy",
            },
        ]

        migrations = current_sleeper_team_label_migrations(
            rows,
            league_id="current",
            season="2026",
        )

        self.assertEqual(migrations["Melkor Lord of Light"], "Lulu’s Potatoe’s")
        self.assertEqual(migrations["Threat To Democracy"], "The Semiquincentennials")
        self.assertNotIn("Other roster label", migrations)

    def test_ambiguous_historical_label_migration_fails_closed(self) -> None:
        rows = [
            {"league_id": "current", "season": "2026", "roster_id": 1, "owner_id": "a", "team_name": "Current A"},
            {"league_id": "current", "season": "2026", "roster_id": 2, "owner_id": "b", "team_name": "Current B"},
            {"league_id": "old-a", "season": "2025", "roster_id": 4, "owner_id": "a", "team_name": "Shared Old Name"},
            {"league_id": "old-b", "season": "2025", "roster_id": 7, "owner_id": "b", "team_name": "Shared Old Name"},
        ]

        self.assertNotIn(
            "Shared Old Name",
            current_sleeper_team_label_migrations(rows, league_id="current", season="2026"),
        )

    def test_structured_trade_theses_use_current_manager_label(self) -> None:
        analysis = {
            "tradeTheses": [
                {
                    "target_manager_name": "Threat To Democracy",
                    "thesis": "Open with Threat To Democracy only if the price stays inside the lane.",
                }
            ],
            "managerIntel": "Historical record: Threat To Democracy made the 2025 move.",
        }

        rewritten = rewrite_source_team_labels_in_structured_analysis(
            analysis,
            {"Threat To Democracy": "The Semiquincentennials"},
        )

        self.assertEqual(rewritten["tradeTheses"][0]["target_manager_name"], "The Semiquincentennials")
        self.assertIn("The Semiquincentennials", rewritten["tradeTheses"][0]["thesis"])
        self.assertIn("Threat To Democracy", rewritten["managerIntel"])

    def test_browser_bundle_repairs_current_trade_decisions_at_the_entry_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed = root / "processed"
            analysis_dir = root / "analysis"
            site = root / "site"
            processed.mkdir()
            analysis_dir.mkdir()
            (processed / "teams.csv").write_text(
                "season,league_id,roster_id,owner_id,display_name,team_name\n"
                "2026,current,2,joe,joe3489,Lulu’s Potatoe’s\n"
                "2026,current,11,wild,wild,The Semiquincentennials\n"
                "2025,prior,9,wild,wild,Threat To Democracy\n",
                encoding="utf-8",
            )
            (processed / "roster_players.csv").write_text(
                "season,league_id,roster_id,owner_id,player_id,player_name,position,is_my_team,team_name\n"
                "2026,current,2,joe,p1,Example Player,WR,true,Lulu’s Potatoe’s\n",
                encoding="utf-8",
            )
            (analysis_dir / "trade_theses.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "target_manager_name": "Threat To Democracy",
                                "thesis": "Call Threat To Democracy about the current lane.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (analysis_dir / "trade_desk.md").write_text(
                "# Trade Desk\n\nCall Threat To Democracy about the current lane.\n",
                encoding="utf-8",
            )

            build_browser_site(
                site,
                processed,
                analysis_dir,
                league_id="current",
                config={
                    "current_season": "2026",
                    "context": {"user_id": "user-1", "league_id": "current", "season": "2026", "roster_id": 2},
                    "current_team": {"team_name": "Lulu’s Potatoe’s"},
                },
            )
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))

        self.assertEqual(
            bundle["analysis"]["tradeTheses"][0]["target_manager_name"],
            "The Semiquincentennials",
        )
        self.assertIn("The Semiquincentennials", bundle["analysis"]["tradeDeskRead"])
        self.assertNotIn("Threat To Democracy", json.dumps(bundle["analysis"]["tradeTheses"]))


if __name__ == "__main__":
    unittest.main()
