from __future__ import annotations

import unittest

from src.team_identity import current_sleeper_team_name, resolve_team_name


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
