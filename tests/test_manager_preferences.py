import unittest

import pandas as pd

from src.manager_preferences import MANAGER_TRANSACTION_PREFERENCE_COLUMNS, build_manager_transaction_preferences


class ManagerTransactionPreferenceTests(unittest.TestCase):
    def test_owner_lineage_and_horizon_context_are_joined_without_using_names_as_identity(self) -> None:
        profiles = pd.DataFrame(
            [
                {
                    "owner_id": "owner-a",
                    "roster_id": 12,
                    "team_name": "Current Crew",
                    "roster_ids_by_season": "2024:2; 2025:2; 2026:12",
                    "seasons_covered": "2024; 2025; 2026",
                },
                {
                    "owner_id": "owner-b",
                    "roster_id": 8,
                    "team_name": "Other Crew",
                    "roster_ids_by_season": "2024:8; 2025:8; 2026:8",
                    "seasons_covered": "2024; 2025; 2026",
                },
            ]
        )
        history = pd.DataFrame(
            [
                {"owner_id": "", "season": "2024", "roster_id": 2, "player_id": "p1", "player_name": "Quarterback One", "event_type": "trade", "direction": "acquired", "week": 4},
                {"owner_id": "", "season": "2025", "roster_id": 2, "player_id": "p2", "player_name": "Quarterback Two", "event_type": "waiver_add", "direction": "added", "week": 7},
                {"owner_id": "", "season": "2025", "roster_id": 2, "player_id": "p5", "player_name": "Quarterback Five", "event_type": "trade", "direction": "acquired", "week": 8},
                {"owner_id": "", "season": "2026", "roster_id": 12, "player_id": "p3", "player_name": "Quarterback Three", "event_type": "trade", "direction": "sold", "week": 2},
                {"owner_id": "", "season": "2026", "roster_id": 999, "player_id": "p4", "player_name": "Should Not Leak", "event_type": "trade", "direction": "acquired", "week": 2},
                {"owner_id": "", "season": "2026", "roster_id": 12, "player_id": "", "player_name": "Unresolved Name", "event_type": "trade", "direction": "acquired", "week": 3},
            ]
        )
        players = pd.DataFrame(
            [
                {"player_id": "p1", "full_name": "Quarterback One", "position": "QB"},
                {"player_id": "p2", "full_name": "Quarterback Two", "position": "QB"},
                {"player_id": "p3", "full_name": "Quarterback Three", "position": "QB"},
                {"player_id": "p5", "full_name": "Quarterback Five", "position": "QB"},
            ]
        )
        roster = pd.DataFrame(
            [
                {"season": "2026", "roster_id": 12, "player_id": "p1", "position": "QB"},
                {"season": "2026", "roster_id": 8, "player_id": "other", "position": "QB"},
            ]
        )
        horizon = pd.DataFrame(
            [
                {"player_id": "p1", "next_game_market_score": 80, "rest_of_season_market_score": 70, "dynasty_market_score": 60, "career_projection_score": 50, "contender_fit_score": 75, "rebuilder_fit_score": 45},
                {"player_id": "p2", "next_game_market_score": 40, "rest_of_season_market_score": 30, "dynasty_market_score": 20, "career_projection_score": 10, "contender_fit_score": 35, "rebuilder_fit_score": 25},
                {"player_id": "p3", "next_game_market_score": 20, "rest_of_season_market_score": 25, "dynasty_market_score": 30, "career_projection_score": 35, "contender_fit_score": 30, "rebuilder_fit_score": 40},
            ]
        )

        result = build_manager_transaction_preferences(profiles, history, roster, players, horizon)

        lane = result[(result["owner_id"] == "owner-a") & (result["position_group"] == "QB")].iloc[0]
        self.assertEqual(lane["roster_id"], 12)
        self.assertEqual(lane["acquired_count"], 3)
        self.assertEqual(lane["sold_count"], 1)
        self.assertEqual(lane["trade_acquired_count"], 2)
        self.assertEqual(lane["waiver_acquired_count"], 1)
        self.assertEqual(lane["current_roster_acquired_count"], 1)
        self.assertEqual(lane["horizon_acquired_matches"], 2)
        self.assertEqual(lane["horizon_sold_matches"], 1)
        self.assertEqual(lane["horizon_acquired_next_game_matches"], 2)
        self.assertEqual(lane["horizon_sold_next_game_matches"], 1)
        self.assertEqual(lane["horizon_acquired_career_window_matches"], 2)
        self.assertEqual(lane["horizon_sold_career_window_matches"], 1)
        self.assertIn("next_game: acquired 2/3; sold 1/1", lane["horizon_coverage_detail"])
        self.assertEqual(lane["acquired_rest_of_season_market_score"], 50.0)
        self.assertEqual(lane["sold_dynasty_market_score"], 30.0)
        self.assertEqual(lane["acquired_minus_sold_dynasty_delta"], 10.0)
        self.assertEqual(lane["history_status"], "supported")
        self.assertIn("current context", lane["evidence"])
        unknown = result[(result["owner_id"] == "owner-a") & (result["position_group"] == "UNKNOWN")].iloc[0]
        self.assertEqual(unknown["acquired_count"], 1)
        self.assertNotIn("Should Not Leak", result["unique_acquired_players"].to_string())

    def test_missing_history_is_fail_closed_and_does_not_create_zero_lanes(self) -> None:
        profiles = pd.DataFrame([{"owner_id": "owner-a", "roster_id": 2, "team_name": "Quiet", "seasons_covered": "2026"}])
        result = build_manager_transaction_preferences(
            profiles,
            pd.DataFrame(columns=["season", "roster_id", "player_id", "event_type", "direction"]),
            pd.DataFrame(),
        )
        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), list(MANAGER_TRANSACTION_PREFERENCE_COLUMNS))


if __name__ == "__main__":
    unittest.main()
