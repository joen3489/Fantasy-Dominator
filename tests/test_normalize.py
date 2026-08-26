import unittest

from src.normalize import normalize_roster_players


class RosterAvailabilityNormalizationTests(unittest.TestCase):
    """Protect the current-only boundary for Sleeper player availability metadata."""

    def setUp(self) -> None:
        self.rosters = [
            {
                "roster_id": 2,
                "owner_id": "user-1",
                "players": ["p1"],
                "starters": ["p1"],
            }
        ]
        self.roster_map = {2: {"team_name": "Lulu's Potatoes"}}
        self.players = {
            "p1": {
                "full_name": "Current Injury Player",
                "position": "WR",
                "team": "MIA",
                "age": 31,
                "years_exp": 9,
                "injury_status": "Questionable",
                "injury_body_part": "Knee - ACL",
            }
        }

    def test_current_season_keeps_current_sleeper_availability(self) -> None:
        rows = normalize_roster_players(
            "2026", "league-1", self.rosters, self.roster_map, 2, self.players, current_season="2026"
        )

        self.assertEqual(rows[0]["injury_status"], "Questionable")
        self.assertEqual(rows[0]["injury_body_part"], "Knee - ACL")
        self.assertEqual(rows[0]["availability_scope"], "current_season_snapshot")

    def test_historical_season_does_not_copy_current_availability(self) -> None:
        rows = normalize_roster_players(
            "2025", "league-1", self.rosters, self.roster_map, 2, self.players, current_season="2026"
        )

        self.assertEqual(rows[0]["injury_status"], "")
        self.assertEqual(rows[0]["injury_body_part"], "")
        self.assertEqual(rows[0]["availability_scope"], "historical_unavailable")

    def test_missing_season_boundary_fails_closed(self) -> None:
        rows = normalize_roster_players(
            "2026", "league-1", self.rosters, self.roster_map, 2, self.players
        )

        self.assertEqual(rows[0]["injury_status"], "")
        self.assertEqual(rows[0]["injury_body_part"], "")
        self.assertEqual(rows[0]["availability_scope"], "historical_unavailable")


if __name__ == "__main__":
    unittest.main()
