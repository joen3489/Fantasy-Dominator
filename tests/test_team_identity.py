from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from src.analysis import rewrite_source_team_labels_in_articles
from src.team_identity import current_sleeper_team_name, historical_sleeper_team_names, resolve_team_name


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


if __name__ == "__main__":
    unittest.main()
