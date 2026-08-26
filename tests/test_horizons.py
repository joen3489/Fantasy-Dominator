from __future__ import annotations

import unittest

import pandas as pd

from src.horizons import (
    AVAILABLE_HORIZON_COLUMNS,
    HORIZON_COLUMNS,
    HORIZON_MODEL_VERSION,
    HORIZON_SCORE_BASIS,
    build_available_player_horizon_scores,
    build_player_horizon_market_scores,
)
from src.matchups import build_team_defense_factors
from src.signals import build_counterparty_asset_interest, enrich_counterparty_trade_edges_with_horizons


class HorizonMarketTests(unittest.TestCase):
    def test_available_market_requires_unique_sleeper_identity_and_excludes_current_roster(self) -> None:
        """Design source: AGENTS.md; availability is scoped by league and never guessed from a label."""
        output = build_available_player_horizon_scores(
            pd.DataFrame([
                {"player_id": "", "player_name": "Available Receiver", "position": "WR", "consensus_value": 42, "source_count": 1, "confidence": "high", "source_trace": "market"},
                {"player_id": "", "player_name": "Roster Receiver", "position": "WR", "consensus_value": 50, "source_count": 1, "confidence": "high", "source_trace": "market"},
                {"player_id": "", "player_name": "Ambiguous Receiver", "position": "WR", "consensus_value": 30, "source_count": 1, "confidence": "high", "source_trace": "market"},
            ]),
            pd.DataFrame([
                {"player_id": "p1", "full_name": "Available Receiver", "position": "WR", "team": "BUF", "age": 24, "injury_status": "", "injury_body_part": ""},
                {"player_id": "p2", "full_name": "Roster Receiver", "position": "WR", "team": "NYJ", "age": 25, "injury_status": "", "injury_body_part": ""},
                {"player_id": "p3", "full_name": "Ambiguous Receiver", "position": "WR", "team": "MIA", "age": 25, "injury_status": "", "injury_body_part": ""},
                {"player_id": "p4", "full_name": "Ambiguous Receiver", "position": "WR", "team": "SEA", "age": 26, "injury_status": "", "injury_body_part": ""},
            ]),
            pd.DataFrame([
                {"season": "2026", "league_id": "league-1", "roster_id": 2, "player_id": "p2", "player_name": "Roster Receiver", "position": "WR"},
            ]),
            pd.DataFrame([{"season": "2026", "league_id": "league-1", "scoring_settings": "{}"}]),
            {"current_season": "2026", "current_week": 3, "league_id": "league-1"},
        )

        self.assertEqual(list(output.columns), AVAILABLE_HORIZON_COLUMNS)
        self.assertEqual(list(output["player_id"]), ["p1"])
        self.assertEqual(output.iloc[0]["identity_status"], "sleeper_unique_name_match")
        self.assertEqual(output.iloc[0]["availability_status"], "not_rostered_in_selected_league")
        self.assertEqual(output.iloc[0]["availability_scope"], "current_season_snapshot")
        self.assertIn("not a waiver-eligibility", output.iloc[0]["evidence"])

    def test_available_market_fails_closed_when_selected_league_roster_is_not_present(self) -> None:
        """Design source: docs/data_contract.md; an unproven league boundary cannot label players available."""
        output = build_available_player_horizon_scores(
            pd.DataFrame([{"player_name": "Available Receiver", "position": "WR", "consensus_value": 42}]),
            pd.DataFrame([{"player_id": "p1", "full_name": "Available Receiver", "position": "WR", "team": "BUF", "age": 24}]),
            pd.DataFrame([{"season": "2026", "league_id": "other-league", "roster_id": 2, "player_id": "p2"}]),
            pd.DataFrame([{"season": "2026", "league_id": "league-1", "scoring_settings": "{}"}]),
            {"current_season": "2026", "league_id": "league-1"},
        )

        self.assertTrue(output.empty)

    def test_available_market_uses_refresh_projection_cohort_for_clock_scores(self) -> None:
        """Design source: docs/data_contract.md; position percentiles cannot be computed from a private subset."""
        market = pd.DataFrame([
            {"player_name": "Available Receiver", "position": "WR", "consensus_value": 40, "source_count": 1, "confidence": "high", "source_trace": "market"},
            {"player_name": "Roster Receiver", "position": "WR", "consensus_value": 80, "source_count": 1, "confidence": "high", "source_trace": "market"},
        ])
        players = pd.DataFrame([
            {"player_id": "p1", "full_name": "Available Receiver", "position": "WR", "team": "BUF", "age": 24},
            {"player_id": "p2", "full_name": "Roster Receiver", "position": "WR", "team": "NYJ", "age": 25},
        ])
        roster = pd.DataFrame([
            {"season": "2026", "league_id": "league-1", "roster_id": 2, "player_id": "p2", "player_name": "Roster Receiver", "position": "WR"},
        ])
        projection = pd.DataFrame([
            {"season": "2026", "player_id": "p1", "player_name": "Available Receiver", "position": "WR", "team": "BUF", "projected_fantasy_points": 170, "projected_ppg": 10, "projected_games": 17, "projection_confidence": "medium", "source_trace": "projection"},
            {"season": "2026", "player_id": "p2", "player_name": "Roster Receiver", "position": "WR", "team": "NYJ", "projected_fantasy_points": 340, "projected_ppg": 20, "projected_games": 17, "projection_confidence": "high", "source_trace": "projection"},
        ])
        output = build_available_player_horizon_scores(
            market,
            players,
            roster,
            pd.DataFrame([{"season": "2026", "league_id": "league-1", "scoring_settings": "{}"}]),
            {"current_season": "2026", "current_week": 1, "league_id": "league-1"},
            season_projection_df=projection,
        )

        row = output.iloc[0]
        # With the rostered peer in the score universe, the available player's
        # production clock is below the WR cohort midpoint, not a default 50.
        self.assertEqual(row["player_id"], "p1")
        self.assertEqual(float(row["next_game_market_score"]), 25.0)
        self.assertEqual(float(row["rest_of_season_market_score"]), 25.0)
        self.assertLess(float(row["market_percentile"]), 50.0)

    def test_counterparty_asset_interest_finds_possible_audiences_without_claiming_intent(self) -> None:
        """Design source: AGENTS.md; historical lanes are evidence for questions, not intent."""
        inventory = pd.DataFrame([
            {
                "roster_id": 2,
                "team_name": "My Team",
                "asset_type": "player",
                "asset_id": "asset-1",
                "asset_name": "My Receiver",
                "position": "WR",
                "market_value": 80,
            }
        ])
        lanes = pd.DataFrame([
            {
                "roster_id": 8,
                "team_name": "Contender",
                "position_group": "PASS_CATCHER",
                "transaction_read": "observed acquisition lane",
                "acquired_count": 8,
                "sold_count": 2,
                "current_roster_acquired_count": 3,
                "history_status": "supported",
                "confidence": "high",
            },
            {
                "roster_id": 9,
                "team_name": "Rebuilder",
                "position_group": "PASS_CATCHER",
                "transaction_read": "observed disposal lane",
                "acquired_count": 1,
                "sold_count": 5,
                "current_roster_acquired_count": 0,
                "history_status": "supported",
                "confidence": "high",
            },
        ])
        needs = pd.DataFrame([
            {"roster_id": 8, "team_shape": "contender_shape", "need_pass_catcher": "high"},
            {"roster_id": 9, "team_shape": "rebuild_asset_bank", "need_pass_catcher": "medium"},
        ])
        horizons = pd.DataFrame([
            {
                "player_id": "asset-1",
                "roster_id": 2,
                "contender_fit_score": 40,
                "rebuilder_fit_score": 90,
                "horizon_model_version": HORIZON_MODEL_VERSION,
                "fit_basis": "test horizon basis",
                "market_percentile": 55,
                "next_game_market_score": 35,
                "rest_of_season_market_score": 62,
                "dynasty_market_score": 88,
                "career_projection_score": 75,
                "next_game_minus_market_delta": -20,
                "rest_of_season_minus_market_delta": 7,
                "dynasty_minus_market_delta": 33,
                "career_minus_market_delta": 20,
                "rest_of_season_minus_next_game_delta": 27,
                "dynasty_minus_rest_of_season_delta": 26,
                "career_minus_dynasty_delta": -13,
            }
        ])

        output = build_counterparty_asset_interest(
            inventory,
            lanes,
            needs,
            horizons,
            {
                "current_team": {"roster_id": 2, "team_name": "My Team"},
                "strategy_profile": {"team_direction": "rebuild"},
            },
        )

        self.assertEqual(set(output["target_roster_id"]), {8, 9})
        best = output.iloc[0]
        self.assertEqual(best["target_roster_id"], 8)
        self.assertEqual(best["asset_id"], "asset-1")
        self.assertEqual(float(best["market_value"]), 80.0)
        self.assertEqual(best["transaction_lane_read"], "observed acquisition lane")
        self.assertEqual(best["horizon_fit_read"], "active_team_timeline_premium")
        self.assertEqual(float(best["horizon_market_percentile"]), 55.0)
        self.assertEqual(best["horizon_market_disagreement_window"], "dynasty")
        self.assertEqual(float(best["horizon_market_disagreement_delta"]), 33.0)
        self.assertEqual(best["horizon_market_disagreement_read"], "clock_leads_market")
        self.assertIn("not proof of intent", best["risk"])
        self.assertIn("manager_transaction_preferences", best["source_trace"])
        self.assertIn("player_horizon_market_scores", best["source_trace"])

    def test_counterparty_asset_interest_fails_closed_without_a_resolved_lane(self) -> None:
        """Design source: AGENTS.md; no manager preference is inferred from missing history."""
        inventory = pd.DataFrame([{
            "roster_id": 2, "team_name": "My Team", "asset_type": "player",
            "asset_id": "asset-1", "asset_name": "My Receiver", "position": "WR", "market_value": 80,
        }])
        output = build_counterparty_asset_interest(
            inventory,
            pd.DataFrame([{
                "roster_id": 8, "team_name": "Other", "position_group": "UNKNOWN",
                "acquired_count": 20, "sold_count": 0, "history_status": "supported", "confidence": "high",
            }]),
            pd.DataFrame([{"roster_id": 8, "team_shape": "contender_shape", "need_pass_catcher": "high"}]),
            pd.DataFrame(),
            {"current_team": {"roster_id": 2}, "strategy_profile": {"team_direction": "contender"}},
        )
        self.assertTrue(output.empty)

    def test_counterparty_edges_carry_target_timeline_fit_without_repricing_the_edge(self) -> None:
        """Design source: AGENTS.md; writers explain timeline fit but deterministic price remains separate."""
        edges = pd.DataFrame([{
            "target_roster_id": 8,
            "target_team": "Contender",
            "player_id": "veteran",
            "player_name": "Veteran Receiver",
            "position": "WR",
            "trade_edge_score": 12.5,
            "edge_type": "we_may_value_more",
            "evidence": "market edge",
            "risk": "medium",
            "confidence": "high",
            "source_trace": "player_signal_scores",
        }])
        horizons = pd.DataFrame([{
            "player_id": "veteran",
            "roster_id": 8,
            "contender_fit_score": 85,
            "rebuilder_fit_score": 35,
            "horizon_model_version": HORIZON_MODEL_VERSION,
            "market_percentile": 50,
            "next_game_market_score": 75,
            "rest_of_season_market_score": 30,
            "dynasty_market_score": 65,
            "career_projection_score": 45,
            "next_game_minus_market_delta": 25,
            "rest_of_season_minus_market_delta": -20,
            "dynasty_minus_market_delta": 15,
            "career_minus_market_delta": -5,
            "rest_of_season_minus_next_game_delta": -45,
            "dynasty_minus_rest_of_season_delta": 35,
            "career_minus_dynasty_delta": -20,
        }])
        needs = pd.DataFrame([{
            "roster_id": 8,
            "team_shape": "contender_shape",
        }])

        output = enrich_counterparty_trade_edges_with_horizons(
            edges,
            horizons,
            needs,
            {
                "current_team": {"roster_id": 2},
                "strategy_profile": {"team_direction": "deep rebuild"},
            },
        )
        row = output.iloc[0]
        self.assertEqual(row["target_team_lens"], "contender")
        self.assertEqual(float(row["target_horizon_fit_score"]), 85.0)
        self.assertEqual(float(row["active_horizon_fit_score"]), 35.0)
        self.assertEqual(float(row["horizon_fit_edge"]), 50.0)
        self.assertEqual(row["horizon_fit_read"], "target_team_timeline_premium")
        self.assertEqual(row["horizon_market_disagreement_window"], "this_week")
        self.assertEqual(float(row["horizon_market_disagreement_delta"]), 25.0)
        self.assertEqual(float(row["horizon_market_disagreement_magnitude"]), 25.0)
        self.assertEqual(row["horizon_market_disagreement_read"], "clock_leads_market")
        self.assertEqual(float(row["next_game_market_score"]), 75.0)
        self.assertEqual(row["horizon_model_version"], HORIZON_MODEL_VERSION)
        self.assertEqual(float(row["trade_edge_score"]), 12.5)
        self.assertIn("target_team_lens=contender", row["evidence"])
        self.assertIn("player_horizon_market_scores", row["source_trace"])

    def test_counterparty_edges_remain_usable_when_horizon_join_is_missing(self) -> None:
        """Design source: AGENTS.md fail-closed seam; missing enrichment cannot erase the edge."""
        edges = pd.DataFrame([{
            "target_roster_id": 8,
            "target_team": "Unknown timeline",
            "player_id": "missing",
            "player_name": "Missing Horizon Player",
            "position": "RB",
            "trade_edge_score": 7.0,
            "edge_type": "mutual_fit",
            "evidence": "original evidence",
            "risk": "medium",
            "confidence": "low",
            "source_trace": "player_signal_scores",
        }])
        output = enrich_counterparty_trade_edges_with_horizons(
            edges,
            pd.DataFrame(),
            pd.DataFrame(),
            {"strategy_profile": {"team_direction": "contender"}},
        )
        row = output.iloc[0]
        self.assertEqual(float(row["trade_edge_score"]), 7.0)
        self.assertEqual(row["evidence"], "original evidence")
        self.assertEqual(row["horizon_fit_read"], "")

    def test_horizon_identity_uses_selected_league_before_roster_id_or_name(self) -> None:
        """Design source: AGENTS.md; league scope precedes mutable team labels."""
        season = pd.DataFrame([{
            "season": "2026",
            "player_id": "shared-player",
            "player_name": "Shared Receiver",
            "position": "WR",
            "projected_fantasy_points": 255,
            "projected_ppg": 15,
            "projection_confidence": "high",
            "source_trace": "season_projection",
        }])
        weekly = pd.DataFrame([{
            "season": "2026",
            "week": 2,
            "player_id": "shared-player",
            "position": "WR",
            "projected_fantasy_points": 15,
        }])
        signals = pd.DataFrame([{
            "player_id": "shared-player",
            "position": "WR",
            "age": 24,
            "market_value": 50,
            "market_percentile": 60,
            "source_trace": "market",
        }])
        roster = pd.DataFrame([
            {
                "season": "2026",
                "league_id": "league-1",
                "roster_id": 7,
                "player_id": "shared-player",
                "player_name": "Lulu's Potatoes",
                "position": "WR",
                "team_name": "Lulu's Potatoes",
                "availability_scope": "current_season_snapshot",
            },
            {
                "season": "2026",
                "league_id": "league-2",
                "roster_id": 3,
                "player_id": "shared-player",
                "player_name": "Moose Caboose",
                "position": "WR",
                "team_name": "Moose Caboose",
                "availability_scope": "current_season_snapshot",
            },
        ])

        output = build_player_horizon_market_scores(
            season,
            weekly,
            signals,
            roster,
            {"current_season": "2026", "current_week": 1, "league_id": "league-1"},
        )

        self.assertEqual(len(output), 1)
        row = output.iloc[0]
        self.assertEqual(row["league_id"], "league-1")
        self.assertEqual(int(row["roster_id"]), 7)
        self.assertEqual(row["team_name"], "Lulu's Potatoes")

    def test_four_windows_keep_week_ros_dynasty_and_career_separate(self) -> None:
        season = pd.DataFrame(
            [
                {
                    "season": "2026",
                    "player_id": "young",
                    "player_name": "Young Receiver",
                    "position": "WR",
                    "roster_id": 2,
                    "team_name": "My Team",
                    "projected_fantasy_points": 272,
                    "projected_ppg": 16,
                    "projection_confidence": "high",
                    "source_trace": "season_projection",
                },
                {
                    "season": "2026",
                    "player_id": "veteran",
                    "player_name": "Veteran Receiver",
                    "position": "WR",
                    "roster_id": 8,
                    "team_name": "Contender",
                    "projected_fantasy_points": 340,
                    "projected_ppg": 20,
                    "projection_confidence": "high",
                    "source_trace": "season_projection",
                },
            ]
        )
        weekly = pd.DataFrame(
            [
                {"season": "2026", "week": 2, "player_id": "young", "position": "WR", "projected_fantasy_points": 16},
                {"season": "2026", "week": 2, "player_id": "veteran", "position": "WR", "projected_fantasy_points": 20},
            ]
        )
        signals = pd.DataFrame(
            [
                {"player_id": "young", "position": "WR", "age": 23, "market_value": 40, "market_percentile": 35, "source_trace": "market"},
                {"player_id": "veteran", "position": "WR", "age": 30, "market_value": 80, "market_percentile": 90, "source_trace": "market"},
            ]
        )
        market = pd.DataFrame(
            [
                {"player_id": "young", "source_count": 2, "disagreement_score": 4.5, "confidence": "high", "source_trace": "market-a; market-b"},
                {"player_id": "veteran", "source_count": 1, "disagreement_score": 0, "confidence": "medium", "source_trace": "market-a"},
            ]
        )
        roster = pd.DataFrame(
            [
                {"season": "2026", "player_id": "young", "position": "WR", "roster_id": 2, "availability_scope": "current_season_snapshot", "injury_status": "Active", "injury_body_part": ""},
                {"season": "2026", "player_id": "veteran", "position": "WR", "roster_id": 8, "availability_scope": "current_season_snapshot", "injury_status": "Questionable", "injury_body_part": "knee"},
            ]
        )

        output = build_player_horizon_market_scores(
            season,
            weekly,
            signals,
            roster,
            {"current_season": "2026", "current_week": 1},
            market_consensus_df=market,
        )
        self.assertEqual(list(output.columns), HORIZON_COLUMNS)
        self.assertTrue((output["horizon_model_version"] == HORIZON_MODEL_VERSION).all())
        self.assertTrue((output["horizon_score_basis"] == HORIZON_SCORE_BASIS).all())
        young = output.set_index("player_id").loc["young"]
        veteran = output.set_index("player_id").loc["veteran"]
        self.assertEqual(int(young["next_game_week"]), 2)
        self.assertEqual(young["availability_scope"], "current_season_snapshot")
        self.assertEqual(int(young["rest_of_season_weeks"]), 16)
        self.assertEqual(float(young["next_game_baseline_points"]), 16.0)
        self.assertEqual(float(young["rest_of_season_baseline_points"]), 256.0)
        self.assertEqual(young["next_game_status"], "opponent_neutral_weekly_allocation")
        self.assertNotIn("current availability flag is applied", young["risk"])
        self.assertEqual(float(young["market_value"]), 40.0)
        self.assertEqual(float(young["market_percentile"]), 35.0)
        self.assertEqual(int(young["market_source_count"]), 2)
        self.assertAlmostEqual(float(young["market_disagreement_score"]), 4.5)
        self.assertEqual(young["market_source_confidence"], "high")
        self.assertIn("market_source_count=2", young["evidence"])
        self.assertIn("market-a", young["source_trace"])
        self.assertIn("market_value_is_the_cross_position_price_anchor", young["evidence"])
        self.assertNotEqual(float(young["next_game_market_score"]), float(young["dynasty_market_score"]))
        self.assertAlmostEqual(
            float(young["rest_of_season_minus_next_game_delta"]),
            float(young["rest_of_season_market_score"]) - float(young["next_game_market_score"]),
        )
        self.assertAlmostEqual(
            float(young["dynasty_minus_rest_of_season_delta"]),
            float(young["dynasty_market_score"]) - float(young["rest_of_season_market_score"]),
        )
        self.assertAlmostEqual(
            float(young["career_minus_dynasty_delta"]),
            float(young["career_projection_score"]) - float(young["dynasty_market_score"]),
        )
        self.assertGreater(float(young["rebuilder_fit_score"]), float(young["contender_fit_score"]))
        self.assertEqual(young["career_projection_status"], "internal_age_curve_5yr")
        self.assertEqual(int(young["career_projection_years"]), 5)
        self.assertGreater(float(young["career_projection_points"]), 0)
        self.assertIn("contender fit weights", young["fit_basis"])
        self.assertEqual(young["fit_coverage"], "4/4")
        self.assertIn("not a dollar market value", young["horizon_score_basis"])
        self.assertIn("score_basis=position-relative percentile", young["evidence"])
        self.assertEqual(veteran["next_game_status"], "availability_flagged_questionable")
        self.assertLess(float(veteran["next_game_expected_points"]), float(veteran["next_game_baseline_points"]))
        self.assertIn("not a career-points forecast", veteran["dynasty_basis"])
        self.assertIn("rest-of-season baseline is not recovery-adjusted", veteran["rest_of_season_basis"])
        self.assertIn("rest-of-season baseline", veteran["risk"])
        self.assertIn("single-source", veteran["risk"])
        self.assertNotEqual(float(young["career_projection_score"]), float(veteran["career_projection_score"]))

        custom = build_player_horizon_market_scores(
            season,
            weekly,
            signals,
            roster,
            {
                "current_season": "2026",
                "current_week": 1,
                "strategy_profile": {
                    "horizon_fit_weights": {
                        "contender": {"next_game": 100, "rest_of_season": 0, "dynasty": 0, "career_window": 0},
                        "rebuilder": {"next_game": 0, "rest_of_season": 0, "dynasty": 100, "career_window": 0},
                    }
                },
            },
        ).set_index("player_id")
        self.assertEqual(custom.loc["young", "fit_basis"].split("fit weight profile=", 1)[1].split(";", 1)[0], "custom")
        self.assertAlmostEqual(
            float(custom.loc["young", "contender_fit_score"]),
            float(custom.loc["young", "next_game_market_score"]),
        )
        self.assertAlmostEqual(
            float(custom.loc["young", "rebuilder_fit_score"]),
            float(custom.loc["young", "dynasty_market_score"]),
        )

    def test_market_receipt_uses_unique_name_position_bridge_when_provider_has_no_sleeper_id(self) -> None:
        """Design source: docs/data_contract.md; external rows may bridge only when identity is unique."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "sleeper-1", "player_name": "Receipt Receiver", "position": "WR",
            "projected_fantasy_points": 272, "projected_ppg": 16, "projected_games": 17,
            "projection_confidence": "high", "source_trace": "projection",
        }])
        signals = pd.DataFrame([{
            "player_id": "sleeper-1", "position": "WR", "age": 24,
            "market_value": 55, "market_percentile": 60, "source_trace": "signals",
        }])
        market = pd.DataFrame([{
            "player_id": "", "player_name": "Receipt Receiver", "position": "WR",
            "source_count": 3, "disagreement_score": 8.25, "confidence": "high",
            "source_trace": "provider-a; provider-b; provider-c",
        }])

        row = build_player_horizon_market_scores(
            season,
            pd.DataFrame(),
            signals,
            pd.DataFrame(),
            {"current_season": "2026", "current_week": 1},
            market_consensus_df=market,
        ).iloc[0]

        self.assertEqual(int(row["market_source_count"]), 3)
        self.assertAlmostEqual(float(row["market_disagreement_score"]), 8.25)
        self.assertEqual(row["market_source_confidence"], "high")
        self.assertIn("provider-a", row["source_trace"])
        self.assertNotIn("receipt is unavailable", row["risk"])

    def test_invalid_horizon_fit_weights_fail_closed_to_defaults(self) -> None:
        season = pd.DataFrame([{
            "season": "2026", "player_id": "p1", "player_name": "Player One", "position": "WR",
            "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projection_confidence": "high", "source_trace": "projection",
        }])
        output = build_player_horizon_market_scores(
            season,
            pd.DataFrame([{"season": "2026", "week": 2, "player_id": "p1", "position": "WR", "projected_fantasy_points": 16}]),
            pd.DataFrame([{"player_id": "p1", "position": "WR", "age": 23, "market_value": 40, "market_percentile": 50}]),
            pd.DataFrame([{"season": "2026", "player_id": "p1", "position": "WR", "roster_id": 2}]),
            {
                "current_season": "2026",
                "current_week": 1,
                "strategy_profile": {"horizon_fit_weights": {"contender": {"next_game": -1}}},
            },
        )
        row = output.iloc[0]
        self.assertIn("fit weight profile=invalid_custom_fallback", row["fit_basis"])
        self.assertIn("contender fit weights next game 52%", row["fit_basis"])

    def test_missing_projection_is_unavailable_not_zero_forecast(self) -> None:
        season = pd.DataFrame(
            [{
                "season": "2026", "player_id": "missing", "player_name": "Unknown Player", "position": "RB",
                "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 0,
                "projected_ppg": 0, "projection_confidence": "low", "source_trace": "missing_projection_input",
            }]
        )
        output = build_player_horizon_market_scores(
            season,
            pd.DataFrame(),
            pd.DataFrame([{"player_id": "missing", "age": 22, "market_value": 0, "market_percentile": ""}]),
            pd.DataFrame(),
            {"current_season": "2026", "current_week": 1},
        )
        row = output.iloc[0]
        self.assertEqual(row["next_game_status"], "unavailable_missing_projection")
        self.assertEqual(row["rest_of_season_status"], "unavailable_missing_projection")
        self.assertEqual(row["dynasty_status"], "unavailable_missing_market_and_projection")
        self.assertEqual(row["career_projection_status"], "unavailable_missing_projection")
        self.assertTrue(pd.isna(row["next_game_expected_points"]))
        self.assertTrue(pd.isna(row["dynasty_market_score"]))

    def test_career_window_anchors_to_unique_historical_production(self) -> None:
        """Design source: docs/data_contract.md; long-clock output needs a traceable production anchor."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "sleeper-1", "player_name": "History Receiver", "position": "WR",
            "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projected_games": 17, "projection_confidence": "high",
            "source_trace": "season_projection",
        }])
        signals = pd.DataFrame([{
            "player_id": "sleeper-1", "position": "WR", "age": 23,
            "market_value": 40, "market_percentile": 35, "source_trace": "market",
        }])
        history = pd.DataFrame([
            {"season": 2024, "week": 1, "game_id": "2024-1", "player_id": "nfl-1", "player_name": "History Receiver", "position": "WR", "fantasy_points_ppr": 12, "source_trace": "nflverse"},
            {"season": 2024, "week": 2, "game_id": "2024-2", "player_id": "nfl-1", "player_name": "History Receiver", "position": "WR", "fantasy_points_ppr": 20, "source_trace": "nflverse"},
            {"season": 2025, "week": 1, "game_id": "2025-1", "player_id": "nfl-1", "player_name": "History Receiver", "position": "WR", "fantasy_points_ppr": 18, "source_trace": "nflverse"},
            {"season": 2025, "week": 2, "game_id": "2025-2", "player_id": "nfl-1", "player_name": "History Receiver", "position": "WR", "fantasy_points_ppr": 22, "source_trace": "nflverse"},
        ])

        row = build_player_horizon_market_scores(
            season,
            pd.DataFrame(),
            signals,
            pd.DataFrame(),
            {"current_season": "2026", "current_week": 1},
            usage_df=history,
        ).iloc[0]

        self.assertEqual(row["career_projection_status"], "internal_history_age_curve_5yr")
        self.assertEqual(row["career_history_status"], "matched")
        self.assertEqual(row["career_history_join_method"], "normalized_name_position_unique_source_id")
        self.assertEqual(row["career_history_source_player_id"], "nfl-1")
        self.assertEqual(int(row["career_history_seasons"]), 2)
        self.assertEqual(int(row["career_history_games"]), 4)
        self.assertAlmostEqual(float(row["career_history_ppg"]), 18.29, places=2)
        self.assertIn("nflverse history", row["career_projection_basis"])
        self.assertIn("career_history_source_player_id=nfl-1", row["evidence"])
        self.assertIn("nflverse", row["source_trace"])

    def test_ambiguous_historical_name_does_not_enter_career_projection(self) -> None:
        """Design source: AGENTS.md identity boundary; ambiguous external joins fail closed."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "sleeper-2", "player_name": "Duplicate Receiver", "position": "WR",
            "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projected_games": 17, "projection_confidence": "high",
            "source_trace": "season_projection",
        }])
        signals = pd.DataFrame([{
            "player_id": "sleeper-2", "position": "WR", "age": 23,
            "market_value": 40, "market_percentile": 35, "source_trace": "market",
        }])
        history = pd.DataFrame([
            {"season": 2024, "week": 1, "game_id": "a-1", "player_id": "nfl-a", "player_name": "Duplicate Receiver", "position": "WR", "fantasy_points_ppr": 20, "source_trace": "nflverse"},
            {"season": 2025, "week": 1, "game_id": "b-1", "player_id": "nfl-b", "player_name": "Duplicate Receiver", "position": "WR", "fantasy_points_ppr": 2, "source_trace": "nflverse"},
        ])

        row = build_player_horizon_market_scores(
            season,
            pd.DataFrame(),
            signals,
            pd.DataFrame(),
            {"current_season": "2026", "current_week": 1},
            usage_df=history,
        ).iloc[0]

        self.assertEqual(row["career_history_status"], "ambiguous")
        self.assertEqual(row["career_history_source_player_id"], "")
        self.assertTrue(pd.isna(row["career_history_ppg"]))
        self.assertEqual(row["career_projection_status"], "internal_age_curve_5yr")
        self.assertIn("multiple source player IDs", row["career_projection_basis"])
        self.assertIn("historical career anchor was withheld", row["risk"])

    def test_missing_age_withholds_career_window_score(self) -> None:
        """Design source: docs/data_contract.md; career scenario requires age evidence."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "unknown-age", "player_name": "Unknown Age Receiver", "position": "WR",
            "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projected_games": 17, "projection_confidence": "high",
            "source_trace": "season_projection",
        }])
        signals = pd.DataFrame([{
            "player_id": "unknown-age", "position": "WR", "market_value": 50,
            "market_percentile": 60, "source_trace": "market",
        }])

        row = build_player_horizon_market_scores(
            season,
            pd.DataFrame(),
            signals,
            pd.DataFrame(),
            {"current_season": "2026", "current_week": 1},
        ).iloc[0]

        self.assertEqual(row["career_projection_status"], "unavailable_missing_age")
        self.assertTrue(pd.isna(row["career_projection_score"]))
        self.assertTrue(pd.isna(row["career_minus_dynasty_delta"]))
        self.assertEqual(row["fit_coverage"], "3/4")
        self.assertIn("career window", row["risk"])

    def test_schedule_and_defense_evidence_changes_next_game_and_ros_games(self) -> None:
        """Design source: docs/data_contract.md schedule and horizon boundaries."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "wr", "player_name": "Schedule Receiver", "position": "WR",
            "team": "WAS", "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projection_confidence": "high", "source_trace": "season_projection",
        }])
        weekly = pd.DataFrame([{
            "season": "2026", "week": 2, "player_id": "wr", "position": "WR", "projected_fantasy_points": 16,
        }])
        signals = pd.DataFrame([{
            "player_id": "wr", "position": "WR", "age": 24, "market_value": 50,
            "market_percentile": 60, "source_trace": "market",
        }])
        roster = pd.DataFrame([{
            "season": "2026", "player_id": "wr", "position": "WR", "nfl_team": "WAS", "roster_id": 2,
            "injury_status": "", "injury_body_part": "",
        }])
        # Design source: docs/data_contract.md.  A bye is only valid when the
        # full regular-season schedule is present; this synthetic fixture keeps
        # 32 teams and at least 16 games per team while giving WAS week 8 off.
        teams = ["WAS", "NYJ"] + [f"T{index:02d}" for index in range(30)]
        schedule_rows = []
        for week in range(1, 18):
            pairs = [(teams[index], teams[index + 1]) for index in range(0, 32, 2)]
            if week == 2:
                pairs[0] = ("WAS", "NYJ")
            if week == 8:
                pairs = pairs[1:]
            schedule_rows.extend(
                {"season": "2026", "week": week, "game_type": "REG", "away_team": away, "home_team": home}
                for away, home in pairs
            )
        schedule_rows.append({"season": "2026", "week": 18, "game_type": "REG", "away_team": "WAS", "home_team": "NYJ"})
        schedule = pd.DataFrame(schedule_rows)
        defense = pd.DataFrame([{
            "team": "NYJ", "position": "WR", "matchup_factor": 1.15, "confidence": "high",
            "validation_status": "validated_improvement", "validation_games": 24, "validation_mae_delta": 1.75,
        }])

        output = build_player_horizon_market_scores(
            season, weekly, signals, roster, {"current_season": "2026", "current_week": 1},
            schedule_df=schedule, defense_df=defense,
        )
        row = output.iloc[0]

        self.assertEqual(row["next_game_status"], "schedule_aware_matchup_projection")
        self.assertEqual(row["next_game_opponent"], "NYJ")
        self.assertEqual(row["next_game_home_away"], "away")
        self.assertAlmostEqual(float(row["next_game_matchup_factor"]), 1.15)
        self.assertAlmostEqual(float(row["next_game_expected_points"]), 18.4)
        self.assertEqual(row["next_game_matchup_adjustment_status"], "applied")
        self.assertEqual(int(row["rest_of_season_games"]), 15)
        self.assertEqual(int(row["rest_of_season_bye_weeks"]), 1)
        self.assertEqual(row["rest_of_season_status"], "schedule_aware_games_baseline")

    def test_non_improving_matchup_factor_remains_descriptive_only(self) -> None:
        """Design source: docs/data_contract.md; non-improving holdout evidence cannot alter scores."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "wr", "player_name": "Descriptive Receiver", "position": "WR",
            "team": "WAS", "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projection_confidence": "high", "source_trace": "season_projection",
        }])
        weekly = pd.DataFrame([{
            "season": "2026", "week": 2, "player_id": "wr", "position": "WR", "projected_fantasy_points": 16,
        }])
        roster = pd.DataFrame([{
            "season": "2026", "player_id": "wr", "position": "WR", "nfl_team": "WAS", "roster_id": 2,
        }])
        teams = ["WAS", "NYJ"] + [f"T{index:02d}" for index in range(30)]
        schedule_rows = []
        for week in range(1, 18):
            pairs = [(teams[index], teams[index + 1]) for index in range(0, 32, 2)]
            if week == 2:
                pairs[0] = ("WAS", "NYJ")
            if week == 8:
                pairs = pairs[1:]
            schedule_rows.extend(
                {"season": "2026", "week": week, "game_type": "REG", "away_team": away, "home_team": home}
                for away, home in pairs
            )
        defense = pd.DataFrame([{
            "team": "NYJ", "position": "WR", "matchup_factor": 1.25,
            "validation_status": "validated_no_improvement", "validation_games": 24, "validation_mae_delta": 0,
        }])

        row = build_player_horizon_market_scores(
            season,
            weekly,
            pd.DataFrame(),
            roster,
            {"current_season": "2026", "current_week": 1},
            schedule_df=pd.DataFrame(schedule_rows),
            defense_df=defense,
        ).iloc[0]

        self.assertEqual(row["next_game_matchup_adjustment_status"], "descriptive_only")
        self.assertEqual(row["next_game_status"], "schedule_aware_opponent_context")
        self.assertAlmostEqual(float(row["next_game_expected_points"]), 16.0)
        self.assertIn("not applied", row["next_game_basis"])
        self.assertIn("descriptive only", row["risk"])

    def test_partial_schedule_withholds_opponent_and_bye_claims(self) -> None:
        """Design source: AGENTS.md anti-recursive guardrails; fail closed at the seam."""
        season = pd.DataFrame([{
            "season": "2026", "player_id": "wr", "player_name": "Partial Schedule Receiver", "position": "WR",
            "team": "WAS", "roster_id": 2, "team_name": "My Team", "projected_fantasy_points": 272,
            "projected_ppg": 16, "projection_confidence": "high", "source_trace": "season_projection",
        }])
        weekly = pd.DataFrame([{
            "season": "2026", "week": 2, "player_id": "wr", "position": "WR", "projected_fantasy_points": 16,
        }])
        roster = pd.DataFrame([{
            "season": "2026", "player_id": "wr", "position": "WR", "nfl_team": "WAS", "roster_id": 2,
        }])
        partial_schedule = pd.DataFrame([
            {"season": "2026", "week": 2, "game_type": "REG", "away_team": "WAS", "home_team": "NYJ"},
            {"season": "2026", "week": 8, "game_type": "REG", "away_team": "WAS", "home_team": "NYJ"},
        ])

        row = build_player_horizon_market_scores(
            season,
            weekly,
            pd.DataFrame(),
            roster,
            {"current_season": "2026", "current_week": 1},
            schedule_df=partial_schedule,
        ).iloc[0]

        self.assertEqual(row["schedule_status"], "schedule_partial")
        self.assertEqual(row["next_game_schedule_status"], "schedule_partial")
        self.assertEqual(row["next_game_opponent"], "")
        self.assertTrue(pd.isna(row["rest_of_season_games"]))
        self.assertIn("coverage is incomplete", row["next_game_basis"])
        self.assertIn("schedule source is partial", row["risk"])

    def test_defense_factor_aggregates_points_allowed_once_per_game(self) -> None:
        usage = pd.DataFrame([
            {"season": 2024, "game_id": "g1", "opponent_team": "NYJ", "position": "WR", "fantasy_points_ppr": 10},
            {"season": 2024, "game_id": "g1", "opponent_team": "NYJ", "position": "WR", "fantasy_points_ppr": 20},
            {"season": 2024, "game_id": "g2", "opponent_team": "NYJ", "position": "WR", "fantasy_points_ppr": 30},
            {"season": 2024, "game_id": "BUF1", "opponent_team": "BUF", "position": "WR", "fantasy_points_ppr": 20},
            {"season": 2024, "game_id": "BUF2", "opponent_team": "BUF", "position": "WR", "fantasy_points_ppr": 20},
        ])
        factors = build_team_defense_factors(usage, {"current_season": "2026"})
        jets = factors[(factors["team"] == "NYJ") & (factors["position"] == "WR")].iloc[0]
        self.assertEqual(int(jets["games_sample"]), 2)
        self.assertAlmostEqual(float(jets["fantasy_points_allowed_per_game"]), 30.0)
        self.assertTrue(float(jets["matchup_factor"]) > 1.0)

    def test_matchup_factor_carries_out_of_sample_calibration_receipt(self) -> None:
        """Design source: docs/data_contract.md; factor usefulness must be holdout-visible."""
        rows = []
        for season in (2021, 2022, 2023, 2024):
            for game_no in range(1, 5):
                rows.extend([
                    {
                        "season": season, "game_id": f"{season}-nyj-{game_no}", "opponent_team": "NYJ",
                        "position": "WR", "fantasy_points_ppr": 30 if season >= 2023 else 20,
                    },
                    {
                        "season": season, "game_id": f"{season}-buf-{game_no}", "opponent_team": "BUF",
                        "position": "WR", "fantasy_points_ppr": 20,
                    },
                ])

        factors = build_team_defense_factors(
            pd.DataFrame(rows),
            {"current_season": "2025", "matchup_validation_seasons": 2},
        )
        jets = factors[(factors["team"] == "NYJ") & (factors["position"] == "WR")].iloc[0]
        self.assertEqual(jets["validation_seasons"], "2023,2024")
        self.assertEqual(int(jets["validation_games"]), 8)
        self.assertIn(jets["validation_status"], {"limited_sample", "validated_improvement", "validated_no_improvement"})
        self.assertTrue(float(jets["validation_baseline_mae"]) >= 0)


if __name__ == "__main__":
    unittest.main()
