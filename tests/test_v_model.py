from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from src import operator
from src.analysis import build_analysis_artifacts
from src.browser_site import _data_room_delta, build_browser_site
from src.draft_room import build_draft_room
from src.economics import build_asset_market_gaps, build_economic_tables, build_league_standings, build_manager_behavior_signals, build_manager_event_log, build_opportunity_board
from src.external_sources import _normalize_dynastyprocess_market_sources, _normalize_pick_values, build_market_consensus_values, refresh_external_sources
from src.news import build_news_tables
from src.normalize import build_roster_maps, normalize_matchups, normalize_traded_picks, normalize_trades, normalize_waivers, to_dataframes
from src.pick_ownership import build_pick_ownership
from src.players import players_table
from src.priority_board import build_today_priority_board
from src.profile_intelligence import _availability_note, _player_confidence, build_player_dossiers, build_player_transaction_history, build_profile_intelligence_tables
from src.projection_accuracy import append_projection_accuracy_snapshot, build_projection_accuracy_table
from src.projections import _blend_projection_components, _build_projection_consensus, build_projection_tables, calculate_fantasy_points
from src.opportunity import build_opportunity_scores, score_players_from_weekly
from src.signals import _breakout_score, _classify_action, _normalize_market, build_news_market_edges, build_signal_tables
from scripts.refresh_all import _discover_league_history, _merge_maintenance_canonical_tables, normalize_refresh_mode
from scripts.serve import RailwayHTTPRequestHandler
from scripts.start import write_boot_page


EXPECTED_TABLE_COLUMNS = {
    "leagues": ["season", "league_id", "name", "status", "scoring_settings", "roster_positions", "playoff_week_start", "settings"],
    "teams": ["season", "league_id", "roster_id", "owner_id", "display_name", "team_name", "waiver_position", "waiver_budget_used", "total_moves"],
    "players": ["player_id", "full_name", "position", "team", "age", "years_exp", "fantasy_positions", "status", "injury_status", "injury_body_part"],
    "roster_players": ["season", "league_id", "roster_id", "owner_id", "player_id", "player_name", "position", "nfl_team", "age", "years_exp", "availability_scope", "injury_status", "injury_body_part", "roster_status", "is_my_team", "team_name"],
    "drafts": ["season", "league_id", "draft_id", "status", "type", "settings"],
    "draft_picks": ["season", "league_id", "draft_id", "pick_no", "round", "roster_id", "picked_by", "player_id", "player_name", "position", "nfl_team"],
    "traded_picks": ["season", "league_id", "original_roster_id", "original_team_name", "round", "pick_season", "current_owner_roster_id", "current_owner_team_name", "previous_owner_roster_id", "previous_owner_team_name", "is_my_original_pick", "is_currently_owned_by_me"],
    "transactions_raw": ["season", "league_id", "week", "transaction_id", "type", "status", "created", "raw"],
    "transactions_normalized": ["season", "league_id", "week", "transaction_id", "type", "status", "created_datetime", "roster_ids_involved", "manager_team_names_involved", "adds", "drops", "draft_picks_moved", "waiver_bid", "faab_moved", "failure_reason"],
    "trades": ["season", "league_id", "week", "transaction_id", "created_datetime", "team_a_roster_id", "team_a_name", "team_a_players_received", "team_a_player_ids_received", "team_a_picks_received", "team_a_faab_received", "team_b_roster_id", "team_b_name", "team_b_players_received", "team_b_player_ids_received", "team_b_picks_received", "team_b_faab_received", "raw"],
    "waivers": ["season", "league_id", "week", "transaction_id", "roster_id", "team_name", "player_added", "player_added_ids", "player_dropped", "player_dropped_ids", "waiver_bid", "status", "failure_reason"],
    "matchups": ["season", "league_id", "week", "matchup_id", "roster_id", "team_name", "opponent_roster_id", "opponent_team_name", "points_for", "points_against", "margin", "result", "source_trace", "evidence"],
    "player_usage_weekly": ["source", "season", "week", "player_id", "player_name", "position", "team", "opponent_team", "game_id", "targets", "carries", "receptions", "passing_attempts", "fantasy_points_ppr", "source_trace"],
    "nfl_schedule": ["season", "week", "game_id", "game_type", "gameday", "away_team", "home_team", "schedule_status", "source_trace"],
    "nfl_team_defense_factors": ["team", "position", "games_sample", "fantasy_points_allowed_per_game", "league_position_average", "matchup_factor", "confidence", "validation_seasons", "validation_games", "validation_mae", "validation_baseline_mae", "validation_mae_delta", "validation_direction_accuracy", "validation_status", "source_trace"],
    "market_value_sources": ["source", "source_access_type", "source_player_id", "player_id", "player_name", "position", "raw_value", "normalized_value", "market_rank", "value_format", "source_confidence", "source_trace", "checked_at"],
    "market_consensus_values": ["player_id", "player_name", "position", "consensus_value", "source_count", "disagreement_score", "best_source", "confidence", "source_trace"],
    "player_market_values": ["source", "source_player_id", "player_id", "player_name", "position", "market_value", "market_rank", "value_format", "source_trace"],
    "pick_market_values": ["source", "pick_label", "pick_season", "round", "market_value", "source_trace"],
    "source_freshness": ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"],
    "news_events": ["source", "event_id", "event_type", "published_at", "title", "summary", "url", "player_id", "player_name", "team", "position", "source_trace"],
    "player_news_matches": ["event_id", "source", "input_player_name", "player_id", "matched_player_name", "match_method", "match_confidence", "is_ambiguous", "source_trace"],
    "league_news_impact": ["event_id", "source", "published_at", "player_id", "player_name", "league_id", "season", "roster_id", "team_name", "impact_type", "evidence", "risk", "confidence", "source_trace"],
    "news_source_freshness": ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"],
    "player_projection_season": ["season", "player_id", "player_name", "position", "team", "roster_id", "team_name", "availability_scope", "current_availability_status", "availability_note", "projected_games", "projected_passing_yards", "projected_passing_tds", "projected_interceptions", "projected_rushing_yards", "projected_rushing_tds", "projected_receptions", "projected_receiving_yards", "projected_receiving_tds", "projected_fantasy_points", "projected_ppg", "projection_method", "projection_confidence", "source_trace", "projection_note"],
    "player_projection_weekly": ["season", "week", "player_id", "player_name", "position", "team", "roster_id", "team_name", "availability_scope", "current_availability_status", "availability_note", "projected_fantasy_points", "projected_snap_or_usage_note", "projection_method", "projection_confidence", "source_trace"],
    "player_horizon_market_scores": ["season", "league_id", "as_of_week", "horizon_model_version", "horizon_score_basis", "next_game_week", "player_id", "availability_scope", "current_availability_status", "market_value", "market_percentile", "next_game_market_score", "next_game_minus_market_delta", "next_game_opponent", "next_game_home_away", "next_game_schedule_status", "next_game_matchup_factor", "next_game_matchup_validation_status", "next_game_matchup_validation_games", "next_game_matchup_validation_mae_delta", "next_game_matchup_adjustment_status", "rest_of_season_market_score", "rest_of_season_minus_market_delta", "rest_of_season_minus_next_game_delta", "rest_of_season_games", "rest_of_season_bye_weeks", "dynasty_market_score", "dynasty_minus_market_delta", "dynasty_minus_rest_of_season_delta", "career_projection_years", "career_projection_points", "career_projection_ppg", "career_projection_score", "career_minus_market_delta", "career_minus_dynasty_delta", "career_projection_status", "career_projection_basis", "career_history_join_method", "career_history_source_player_id", "career_history_status", "career_history_seasons", "career_history_games", "career_history_ppg", "career_history_latest_season", "contender_fit_score", "rebuilder_fit_score", "fit_coverage", "fit_basis", "rebuilder_contender_spread", "value_lane", "evidence", "risk", "confidence", "source_trace"],
    "available_player_horizon_scores": ["league_id", "availability_status", "identity_status", "market_rank", "market_source_count", "market_source_confidence", "market_disagreement_score", "player_id", "market_value", "market_percentile", "fit_coverage", "evidence", "risk", "confidence", "source_trace"],
    "projection_source_freshness": ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"],
    "fantasy_nerds_projection_source": ["source", "fn_player_id", "player_name", "normalized_name", "position", "team", "projected_fantasy_points", "source_confidence", "source_trace", "checked_at"],
    "projection_source_components": ["season", "player_id", "player_name", "position", "team", "roster_id", "team_name", "availability_scope", "current_availability_status", "availability_note", "source", "projected_fantasy_points", "projected_ppg", "projected_games", "source_confidence", "source_trace", "projection_method", "detail_stats_json", "checked_at"],
    "source_accuracy_scores": ["source", "position", "season", "mean_absolute_error", "sample_size", "accuracy_confidence", "source_trace", "checked_at"],
    "today_priority_board": ["item_type", "item_type_label", "entity_type", "entity_id", "entity_name", "roster_id", "team_name", "priority_score", "why", "evidence", "risk", "confidence", "source_trace"],
    "player_signal_scores": ["player_id", "player_name", "position", "roster_id", "team_name", "projection_edge_score", "market_gap_score", "timeline_fit_score", "breakout_score", "sell_score", "opportunity_score", "xfp_regression_score", "role_trend_score", "fragility_score", "signal_label", "projection_percentile", "market_percentile", "market_gap_status", "evidence", "risk", "confidence", "source_trace"],
    "player_opportunity_scores": ["player_id", "player_name", "position", "league_id", "roster_id", "team_name", "games_sample", "opportunity_score", "production_score", "xfp_regression_score", "role_trend_score", "fragility_score", "opportunity_evidence", "source_trace"],
    "breakout_candidates": ["player_id", "player_name", "position", "current_availability_status", "current_team_name", "breakout_score", "projection_edge", "market_value", "evidence", "risk", "confidence", "source_trace"],
    "sell_candidates": ["player_id", "player_name", "position", "current_availability_status", "current_team_name", "sell_score", "projection_risk", "market_value", "evidence", "risk", "confidence", "source_trace"],
    "projection_market_gaps": ["player_id", "player_name", "position", "current_availability_status", "projected_fantasy_points", "projected_ppg", "market_value", "projection_percentile", "market_percentile", "market_gap_status", "gap_score", "gap_label", "evidence", "risk", "confidence", "source_trace"],
    "news_market_edges": ["player_id", "player_name", "position", "roster_id", "league_id", "season", "team_name", "news_direction", "edge_type", "news_impact", "news_event_count", "market_value", "projected_ppg", "market_gap_score", "sell_score", "news_market_edge_score", "evidence", "risk", "confidence", "source_trace"],
    "team_fit_scores": ["roster_id", "team_name", "player_id", "player_name", "position", "timeline_fit_score", "need_fit_score", "liquidity_fit_score", "fit_label", "evidence", "risk", "confidence", "source_trace"],
    "action_recommendations": ["roster_id", "team_name", "player_id", "player_name", "position", "action_label", "consumer_label", "action_rank", "action_score", "projected_ppg", "market_value", "why", "evidence", "risk", "confidence", "source_trace"],
    "manager_profiles": ["owner_id", "roster_id", "display_name", "team_name", "seasons_covered", "roster_ids_by_season", "team_names_by_season", "total_trades", "trades_by_season", "players_acquired", "players_sold", "picks_acquired", "picks_sold", "future_1sts_acquired", "future_1sts_sold", "future_2nds_acquired", "future_2nds_sold", "faab_spent_on_waivers", "number_of_waiver_claims", "average_waiver_bid", "max_waiver_bid", "most_common_transaction_partners", "qb_count", "rb_count", "pass_catcher_count", "contender_rebuilder_indicator", "notes"],
    "pick_ownership": ["original_roster_id", "original_team", "pick_season", "round", "current_owner_roster_id", "current_owner", "previous_owner_roster_id", "previous_owner", "is_my_original_pick", "is_currently_owned_by_me", "i_currently_own_it"],
    "team_asset_inventory": ["roster_id", "team_name", "asset_type", "asset_id", "asset_name", "position", "age", "current_availability_status", "availability_note", "market_value", "liquidity_tier", "timeline_fit", "source_trace"],
    "manager_event_log": ["season", "league_id", "owner_id", "event_type", "week", "created_datetime", "transaction_id", "roster_id", "team_name", "counterparty", "players_in", "picks_in", "faab_in", "players_out", "picks_out", "faab_out", "evidence"],
    "manager_season_history": ["owner_id", "season", "roster_id", "team_name", "trades", "waiver_claims", "faab_spent", "transaction_count", "first_transaction_week", "last_transaction_week", "peak_transaction_week", "active_weeks", "trade_weeks", "waiver_weeks", "players_acquired", "players_sold", "picks_acquired", "picks_sold", "trade_partners", "roster_player_count", "qb_count", "rb_count", "pass_catcher_count", "matchup_weeks", "played_weeks", "wins", "losses", "ties", "points_for", "points_against", "point_diff", "win_rate", "outcome_status", "source_trace", "evidence"],
    "league_standings": ["season", "league_id", "roster_id", "team_name", "matchup_rows", "played", "wins", "losses", "ties", "points_for", "points_against", "point_diff", "win_rate", "record", "outcome_status", "source_trace", "evidence"],
    "team_needs_matrix": ["roster_id", "team_name", "qb_count", "rb_count", "wr_count", "te_count", "pass_catcher_count", "future_firsts_owned", "need_qb", "need_rb", "need_pass_catcher", "need_picks", "team_shape"],
    "manager_behavior_signals": ["roster_id", "team_name", "trade_activity_score", "pick_buyer_score", "pick_seller_score", "faab_aggression_score", "waiver_activity_score", "rb_appetite_score", "pass_catcher_appetite_score", "plain_language_label", "evidence"],
    "manager_valuation_profiles": ["owner_id", "roster_id", "team_name", "asset_type", "position_group", "preference_score", "evidence_count", "recency_weighted_score", "confidence", "label", "evidence"],
    "liquidity_scores": ["roster_id", "team_name", "asset_type", "asset_name", "position", "market_value", "liquidity_score", "liquidity_tier", "demand_signal", "source_trace"],
    "asset_market_gaps": ["target_roster_id", "target_team", "asset_type", "asset_name", "position", "current_availability_status", "availability_note", "market_value", "market_gap_score", "opportunity_type", "timeline_fit", "evidence", "risk", "confidence", "source_trace"],
    "opportunity_board": ["action_type", "target_team", "asset_in", "asset_out", "manager_signal", "evidence", "risk", "confidence", "source_trace"],
    "counterparty_trade_edges": ["target_roster_id", "target_team", "player_id", "player_name", "position", "target_team_lens", "target_horizon_fit_score", "active_horizon_fit_score", "horizon_fit_edge", "horizon_fit_read", "horizon_fit_basis", "horizon_model_version", "horizon_market_percentile", "next_game_market_score", "rest_of_season_market_score", "dynasty_market_score", "career_projection_score", "next_game_minus_market_delta", "rest_of_season_minus_market_delta", "dynasty_minus_market_delta", "career_minus_market_delta", "rest_of_season_minus_next_game_delta", "dynasty_minus_rest_of_season_delta", "career_minus_dynasty_delta", "horizon_market_disagreement_window", "horizon_market_disagreement_delta", "horizon_market_disagreement_magnitude", "horizon_market_disagreement_read", "our_value_score", "market_consensus_value", "estimated_owner_value_score", "trade_edge_score", "edge_type", "evidence", "risk", "confidence", "source_trace"],
    "counterparty_asset_interest": ["active_roster_id", "active_team", "asset_id", "asset_name", "asset_type", "position", "market_value", "target_roster_id", "target_team", "target_team_lens", "transaction_lane_read", "transaction_acquired_count", "transaction_sold_count", "transaction_net_acquired_count", "transaction_current_roster_overlap", "transaction_history_status", "transaction_lane_confidence", "target_need", "target_need_fit_score", "target_horizon_fit_score", "active_horizon_fit_score", "horizon_fit_edge", "horizon_fit_read", "horizon_model_version", "horizon_market_percentile", "next_game_market_score", "rest_of_season_market_score", "dynasty_market_score", "career_projection_score", "next_game_minus_market_delta", "rest_of_season_minus_market_delta", "dynasty_minus_market_delta", "career_minus_market_delta", "rest_of_season_minus_next_game_delta", "dynasty_minus_rest_of_season_delta", "career_minus_dynasty_delta", "horizon_market_disagreement_window", "horizon_market_disagreement_delta", "horizon_market_disagreement_magnitude", "horizon_market_disagreement_read", "observed_acquisition_signal", "conversation_fit_score", "conversation_fit_label", "evidence", "risk", "confidence", "source_trace"],
    "manager_profile_tags": ["entity_id", "entity_name", "tag", "score", "confidence", "evidence", "risk", "source_trace", "generated_at"],
    "manager_cycle_profiles": ["owner_id", "roster_id", "team_name", "dynasty_cycle", "trade_temperature", "pick_posture", "waiver_posture", "likely_needs", "likely_sells", "confidence", "evidence"],
    "player_dossiers": ["player_id", "player_name", "position", "age", "roster_id", "team_name", "roster_status", "availability_scope", "current_availability_status", "injury_status", "injury_body_part", "availability_note", "market_value", "projected_fantasy_points", "projected_ppg", "projection_confidence", "signal_label", "breakout_score", "sell_score", "news_impact", "transaction_count", "last_transaction", "source_trace"],
    "player_transaction_history": ["player_id", "identity_method", "player_name", "event_type", "season", "week", "created_datetime", "roster_id", "team_name", "counterparty", "direction", "evidence", "source_trace"],
    "player_profile_tags": ["entity_id", "entity_name", "tag", "score", "confidence", "evidence", "risk", "source_trace", "generated_at"],
    "refresh_metadata": ["generated_at", "refresh_mode", "current_season", "configured_league_ids", "configured_seasons", "ingested_seasons", "historical_league_ids_configured", "transaction_week_start", "transaction_week_end", "requested_week_end", "current_week", "historical_refresh_scope", "matchups_status", "matchup_rows", "source_scope", "raw_cache_root", "raw_external_cache_root", "browser_is_primary_surface", "recommendation_packets_status", "analysis_artifacts_status", "analysis_generated_at", "analysis_context_packet_count", "target_thesis_count", "sell_thesis_count", "trade_thesis_count", "market_source_rows", "market_consensus_rows", "projection_source_rows", "projection_accuracy_rows", "manager_valuation_profile_rows", "manager_transaction_preference_rows", "counterparty_edge_rows", "counterparty_asset_interest_rows", "manager_profile_tag_rows", "player_profile_tag_rows", "player_dossier_rows", "player_horizon_market_rows", "available_player_horizon_rows", "horizon_snapshot_rows", "horizon_accuracy_rows", "horizon_movement_rows", "nfl_schedule_rows", "nfl_team_defense_factor_rows"],
}

EXPECTED_TABLE_COLUMNS["player_horizon_market_scores"][9:9] = [
    "market_source_count",
    "market_disagreement_score",
    "market_source_confidence",
]


class VModelTests(unittest.TestCase):
    def test_railway_handler_uses_http_11(self) -> None:
        self.assertEqual(RailwayHTTPRequestHandler.protocol_version, "HTTP/1.1")

    def test_startup_boot_page_allows_healthcheck_before_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_boot_page(Path(tmp))
            html = path.read_text(encoding="utf-8")

        self.assertIn("Fantasy Dominator", html)
        self.assertIn("Data refresh is running", html)

    def test_operator_token_is_required_for_write_actions(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(operator.operator_enabled())
            self.assertFalse(operator.token_valid({"x-front-office-token": "anything"}))

        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "secret"}, clear=True):
            self.assertTrue(operator.operator_enabled())
            self.assertTrue(operator.token_valid({"x-front-office-token": "secret"}))
            self.assertFalse(operator.token_valid({"x-front-office-token": "wrong"}))

    def test_normalized_transactions_preserve_sleeper_player_ids(self) -> None:
        """Encodes docs/data_contract.md's rule that human labels cannot replace source IDs."""
        transactions = {
            1: [
                {
                    "type": "trade",
                    "roster_ids": [1, 2],
                    "adds": {"101": 1, "202": 2},
                    "draft_picks": [],
                    "waiver_budget": [],
                    "transaction_id": "trade-1",
                    "created": 1_700_000_000_000,
                },
                {
                    "type": "waiver",
                    "roster_ids": [1],
                    "adds": {"303": 1},
                    "drops": {"404": 1},
                    "settings": {"waiver_bid": 5},
                    "status": "complete",
                    "transaction_id": "waiver-1",
                    "created": 1_700_000_000_000,
                },
            ]
        }
        roster_map = {1: {"team_name": "Alpha Team"}, 2: {"team_name": "Beta Team"}}
        players = {
            "101": {"full_name": "Alpha Player"},
            "202": {"full_name": "Beta Player"},
            "303": {"full_name": "Added Player"},
            "404": {"full_name": "Dropped Player"},
        }

        trades = normalize_trades("2026", "league", transactions, roster_map, players)
        waivers = normalize_waivers("2026", "league", transactions, roster_map, players)

        self.assertEqual(trades[0]["team_a_player_ids_received"], "101")
        self.assertEqual(trades[0]["team_b_player_ids_received"], "202")
        self.assertEqual(waivers[0]["player_added_ids"], "303")
        self.assertEqual(waivers[0]["player_dropped_ids"], "404")

    def test_normalized_matchups_preserve_exact_opponents_and_unplayed_state(self) -> None:
        """Encodes docs/data_contract.md's source-ID and absence-is-not-a-result rule."""
        roster_map = {1: {"team_name": "Alpha Team"}, 2: {"team_name": "Beta Team"}}
        matchups = normalize_matchups(
            "2025",
            "league",
            {
                1: [
                    {"roster_id": 1, "matchup_id": 1, "points": 120.5},
                    {"roster_id": 2, "matchup_id": 1, "points": 100},
                ],
                2: [{"roster_id": 1, "matchup_id": "", "points": ""}],
            },
            roster_map,
        )

        alpha = next(row for row in matchups if row["week"] == 1 and row["roster_id"] == 1)
        unplayed = next(row for row in matchups if row["week"] == 2)
        self.assertEqual(alpha["opponent_roster_id"], 2)
        self.assertEqual(alpha["opponent_team_name"], "Beta Team")
        self.assertEqual(alpha["result"], "win")
        self.assertEqual(alpha["margin"], 20.5)
        self.assertIn("/matchups/1", alpha["source_trace"])
        self.assertEqual(unplayed["result"], "unplayed")
        self.assertEqual(unplayed["opponent_roster_id"], "")
        zero_placeholder = normalize_matchups(
            "2026",
            "league",
            {1: [{"roster_id": 1, "matchup_id": 1, "points": 0}, {"roster_id": 2, "matchup_id": 1, "points": 0}]},
            roster_map,
        )
        self.assertTrue(all(row["result"] == "unplayed" for row in zero_placeholder))
        self.assertEqual(list(to_dataframes({"matchups": []})["matchups"].columns), EXPECTED_TABLE_COLUMNS["matchups"])

    def test_league_standings_preserve_outcome_coverage_and_quiet_teams(self) -> None:
        """Encodes docs/data_contract.md: standings are derived from exact matchup evidence."""
        teams = pd.DataFrame(
            [
                {"season": "2026", "league_id": "league", "roster_id": 1, "team_name": "Alpha"},
                {"season": "2026", "league_id": "league", "roster_id": 2, "team_name": "Beta"},
                {"season": "2026", "league_id": "league", "roster_id": 3, "team_name": "Quiet"},
            ]
        )
        matchups = pd.DataFrame(
            [
                {"season": "2026", "league_id": "league", "week": 1, "roster_id": 1, "team_name": "Alpha", "points_for": 120, "points_against": 100, "result": "win"},
                {"season": "2026", "league_id": "league", "week": 2, "roster_id": 1, "team_name": "Alpha", "points_for": "", "points_against": "", "result": "unplayed"},
                {"season": "2026", "league_id": "league", "week": 1, "roster_id": 2, "team_name": "Beta", "points_for": 100, "points_against": 120, "result": "loss"},
            ]
        )

        standings = build_league_standings(matchups, teams)
        alpha = standings[standings["roster_id"] == 1].iloc[0]
        quiet = standings[standings["roster_id"] == 3].iloc[0]
        self.assertEqual(alpha["record"], "1-0-0")
        self.assertEqual(alpha["outcome_status"], "partial")
        self.assertEqual(alpha["points_for"], 120)
        self.assertEqual(quiet["outcome_status"], "not_recorded")
        self.assertEqual(quiet["record"], "not recorded")
        self.assertIsNone(quiet["points_for"])

        future = build_league_standings(
            pd.DataFrame([{
                "season": "2026",
                "league_id": "league",
                "week": 1,
                "roster_id": 1,
                "team_name": "Alpha",
                "points_for": 0,
                "points_against": 0,
                "result": "unplayed",
            }]),
            teams.iloc[[0]],
        ).iloc[0]
        self.assertEqual(future["outcome_status"], "not_recorded")
        self.assertEqual(future["record"], "not recorded")

    def test_maintenance_merge_preserves_history_and_replaces_current_source_rows(self) -> None:
        """Encodes AGENTS.md's additive, idempotent maintenance rule."""
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            processed.mkdir()
            pd.DataFrame(
                [
                    {"season": "2025", "league_id": "league", "roster_id": 1, "team_name": "Alpha 2025"},
                    {"season": "2026", "league_id": "league", "roster_id": 1, "team_name": "Old Alpha"},
                ]
            ).to_csv(processed / "teams.csv", index=False)
            merged = _merge_maintenance_canonical_tables(
                {"teams": [{"season": "2026", "league_id": "league", "roster_id": 1, "team_name": "New Alpha"}, {"season": "2026", "league_id": "league", "roster_id": 2, "team_name": "Beta"}]},
                processed,
            )
            rows = pd.DataFrame(merged["teams"])
        self.assertEqual(set(rows["season"]), {"2025", "2026"})
        self.assertEqual(rows.loc[rows["season"] == "2026", "team_name"].iloc[0], "New Alpha")
        self.assertEqual(normalize_refresh_mode("maintenance"), "maintenance")
        with self.assertRaises(ValueError):
            normalize_refresh_mode("unknown")

    def test_operator_packet_loop_validates_insight_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            inbox = root / "operator" / "inbox"
            outbox = root / "operator" / "outbox"
            status_dir = root / "operator" / "status"
            analysis.mkdir(parents=True)
            (analysis / "manager_dossiers.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "roster_id": 2,
                                "team_name": "Melkor Lord of Light",
                                "tags": "rebuilder, pick accumulator",
                                "confidence": "high",
                                "risk": "medium",
                                "analysis_text": "Manager shows rebuild signals.",
                                "evidence": "future firsts owned=4",
                                "source_trace": "manager_cycle_profiles",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (analysis / "player_dossiers.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "player_id": "1",
                                "player_name": "Jayden Daniels",
                                "tags": "franchise cornerstone, breakout candidate",
                                "confidence": "high",
                                "risk": "medium",
                                "analysis_text": "Player has strong projection and market profile.",
                                "evidence": "ppg=20.5; market=53",
                                "source_trace": "player_dossiers",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.multiple(
                operator,
                ANALYSIS_DIR=analysis,
                OPERATOR_INBOX_DIR=inbox,
                OPERATOR_OUTBOX_DIR=outbox,
                OPERATOR_STATUS_DIR=status_dir,
                STATUS_PATH=status_dir / "operator_status.json",
                INSIGHT_PACKET_PATH=inbox / "front_office_insight_packet.json",
                INSIGHT_OUTPUT_PATH=outbox / "front_office_insight_cards.json",
                VALIDATED_INSIGHTS_PATH=analysis / "validated_insight_cards.json",
                INSIGHT_VALIDATION_PATH=analysis / "insight_card_validation.json",
            ):
                packet_result = operator.build_insight_packet()
                packet = json.loads(operator.INSIGHT_PACKET_PATH.read_text(encoding="utf-8"))
                self.assertEqual(packet_result["evidence_count"], 2)
                self.assertIn("Do not claim manager intent as fact.", packet["instructions"]["forbidden"])

                operator.INSIGHT_OUTPUT_PATH.parent.mkdir(parents=True)
                operator.INSIGHT_OUTPUT_PATH.write_text(
                    json.dumps(
                        {
                            "generation_mode": "operator_packet_loop",
                            "items": [
                                {
                                    "card_id": "manager-2",
                                    "entity_type": "manager",
                                    "entity_id": "2",
                                    "headline": "Rebuild-leaning manager with pick leverage",
                                    "one_line_read": "Treat this team as a pick-rich counterparty, not a mystery box.",
                                    "why_it_matters": "The evidence supports a trade approach built around timeline fit.",
                                    "watchouts": "Confidence is an estimate from observed behavior.",
                                    "confidence": "high",
                                    "cited_evidence_ids": ["manager:2:1"],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                validation = operator.validate_insight_output()
                self.assertTrue(validation["valid"])
                self.assertTrue(operator.VALIDATED_INSIGHTS_PATH.exists())

                operator.INSIGHT_OUTPUT_PATH.write_text(
                    json.dumps(
                        {
                            "items": [
                                {
                                    "card_id": "bad-player",
                                    "entity_type": "player",
                                    "entity_id": "1",
                                    "headline": "Guaranteed breakout",
                                    "one_line_read": "This will happen.",
                                    "why_it_matters": "Unsupported certainty.",
                                    "watchouts": "",
                                    "confidence": "high",
                                    "cited_evidence_ids": ["missing"],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                invalid = operator.validate_insight_output()
                self.assertFalse(invalid["valid"])
                self.assertGreaterEqual(len(invalid["errors"]), 2)

                # Real production failure: an entity card was rejected for containing the bare
                # word "sent" in an ordinary, non-transactional sentence about usage/role.
                operator.INSIGHT_OUTPUT_PATH.write_text(
                    json.dumps(
                        {
                            "items": [
                                {
                                    "card_id": "player-decline",
                                    "entity_type": "player",
                                    "entity_id": "1",
                                    "headline": "Target share decline",
                                    "one_line_read": "The scheme change sent his snap count down this month.",
                                    "why_it_matters": "Role, not talent, explains the dip in production.",
                                    "watchouts": "Confidence is an estimate only.",
                                    "confidence": "medium",
                                    "cited_evidence_ids": ["manager:2:1"],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                non_transactional = operator.validate_insight_output()
                self.assertTrue(non_transactional["valid"], non_transactional["errors"])

    def _operator_dirs(self, root: Path) -> dict:
        analysis = root / "analysis"
        inbox = root / "operator" / "inbox"
        outbox = root / "operator" / "outbox"
        status_dir = root / "operator" / "status"
        analysis.mkdir(parents=True)
        return {
            "ANALYSIS_DIR": analysis,
            "OPERATOR_INBOX_DIR": inbox,
            "OPERATOR_OUTBOX_DIR": outbox,
            "OPERATOR_STATUS_DIR": status_dir,
            "STATUS_PATH": status_dir / "operator_status.json",
            "INSIGHT_PACKET_PATH": inbox / "front_office_insight_packet.json",
            "INSIGHT_OUTPUT_PATH": outbox / "front_office_insight_cards.json",
            "VALIDATED_INSIGHTS_PATH": analysis / "validated_insight_cards.json",
            "INSIGHT_VALIDATION_PATH": analysis / "insight_card_validation.json",
            "DAILY_GM_BRIEF_PATH": analysis / "daily_gm_brief.md",
            "DAILY_GM_BRIEF_VALIDATION_PATH": analysis / "daily_gm_brief_validation.json",
        }

    def _seed_dossiers(self, analysis_dir: Path) -> None:
        (analysis_dir / "manager_dossiers.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "roster_id": 2,
                            "team_name": "Melkor Lord of Light",
                            "tags": "rebuilder, pick accumulator",
                            "confidence": "high",
                            "risk": "medium",
                            "analysis_text": "Manager shows rebuild signals.",
                            "evidence": "future firsts owned=4",
                            "source_trace": "manager_cycle_profiles",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (analysis_dir / "player_dossiers.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "player_id": "1",
                            "player_name": "Jayden Daniels",
                            "tags": "franchise cornerstone, breakout candidate",
                            "confidence": "high",
                            "risk": "medium",
                            "analysis_text": "Player has strong projection and market profile.",
                            "evidence": "ppg=20.5; market=53",
                            "source_trace": "player_dossiers",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_generate_insights_fails_loud_without_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.operator.requests.post") as mock_post:
                result = operator.generate_insights_automatically()

        self.assertEqual(result["state"], "failed")
        self.assertIn("OPENAI_API_KEY", result["message"])
        mock_post.assert_not_called()

    def test_generate_insight_output_via_llm_uses_tool_forced_request(self) -> None:
        packet = {
            "instructions": {"role": "Test role.", "allowed": ["Say things."], "forbidden": ["Do not lie."]},
            "evidence": [{"evidence_id": "player:1:1", "entity_type": "player", "entity_id": "1"}],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [
                {"type": "tool_use", "name": "emit_insight_cards", "input": {"items": [{"card_id": "player-1"}]}}
            ]
        }
        mock_response.raise_for_status.return_value = None

        with patch("src.operator.requests.post", return_value=mock_response) as mock_post:
            result = operator.generate_insight_output_via_llm(packet, "test-key", "claude-haiku-4-5-20251001")

        self.assertEqual(result["items"], [{"card_id": "player-1"}])
        self.assertEqual(result["_provider_receipt"]["provider"], "anthropic")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["tool_choice"], {"type": "tool", "name": "emit_insight_cards"})
        self.assertEqual(kwargs["json"]["tools"][0]["name"], "emit_insight_cards")
        self.assertEqual(kwargs["headers"]["x-api-key"], "test-key")

    def _dispatching_llm_response(self, tool_name: str):
        responses = {
            "emit_insight_cards": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "emit_insight_cards",
                        "input": {
                            "items": [
                                {
                                    "card_id": "player-1",
                                    "entity_type": "player",
                                    "entity_id": "1",
                                    "headline": "Cornerstone with strong projection",
                                    "one_line_read": "Hold, do not shop.",
                                    "why_it_matters": "Evidence supports continued investment.",
                                    "watchouts": "Estimate only.",
                                    "confidence": "high",
                                    "cited_evidence_ids": ["player:1:1"],
                                }
                            ]
                        },
                    }
                ]
            },
            "emit_daily_gm_brief": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "emit_daily_gm_brief",
                        "input": {
                            "narrative_markdown": (
                                "## Target Theses\nJayden Daniels remains the play here.\n\n"
                                "## Sell Windows\nNothing urgent this week.\n\n"
                                "## Manager Angles\nMelkor Lord of Light is stockpiling picks."
                            ),
                            "cited_evidence_ids": ["player:1:1"],
                        },
                    }
                ]
            },
        }
        mock_response = MagicMock()
        mock_response.json.return_value = responses[tool_name]
        mock_response.raise_for_status.return_value = None
        return mock_response

    def test_generate_insights_automatically_imports_and_validates_llm_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])

            def dispatching_post(*args, **kwargs):
                return self._dispatching_llm_response(kwargs["json"]["tool_choice"]["name"])

            with patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                clear=True,
            ):
                with patch.multiple(operator, **dirs):
                    with patch("src.operator.requests.post", side_effect=dispatching_post):
                        result = operator.generate_insights_automatically()

                    self.assertEqual(result["state"], "complete")
                    self.assertTrue(operator.VALIDATED_INSIGHTS_PATH.exists())
                    validated = json.loads(operator.VALIDATED_INSIGHTS_PATH.read_text(encoding="utf-8"))
                    self.assertEqual(validated["items"][0]["card_id"], "player-1")
                    self.assertEqual(validated["generation_mode"], "automatic_llm")
                    brief_text = operator.DAILY_GM_BRIEF_PATH.read_text(encoding="utf-8")
                    self.assertIn("## Target Theses", brief_text)
                    self.assertIn("model_mode: automatic_llm", brief_text)

    def test_generate_insights_automatically_fails_loud_on_api_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])

            with patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                clear=True,
            ):
                with patch.multiple(operator, **dirs):
                    with patch("src.operator.requests.post", side_effect=RuntimeError("network down")):
                        result = operator.generate_insights_automatically()

                    self.assertEqual(result["state"], "failed")
                    self.assertIn("network down", result["insight_cards"]["message"])
                    self.assertIn("network down", result["daily_gm_brief"]["message"])
                    self.assertFalse(operator.INSIGHT_OUTPUT_PATH.exists())
                    self.assertFalse(operator.VALIDATED_INSIGHTS_PATH.exists())

    def test_generate_insights_automatically_reports_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])

            def cards_only_post(*args, **kwargs):
                if kwargs["json"]["tool_choice"]["name"] == "emit_daily_gm_brief":
                    raise RuntimeError("brief model overloaded")
                return self._dispatching_llm_response("emit_insight_cards")

            with patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                clear=True,
            ):
                with patch.multiple(operator, **dirs):
                    with patch("src.operator.requests.post", side_effect=cards_only_post):
                        result = operator.generate_insights_automatically()

                    self.assertEqual(result["state"], "partial")
                    self.assertEqual(result["insight_cards"]["state"], "complete")
                    self.assertEqual(result["daily_gm_brief"]["state"], "failed")
                    self.assertIn("brief model overloaded", result["daily_gm_brief"]["message"])
                    self.assertTrue(operator.VALIDATED_INSIGHTS_PATH.exists())

    def test_daily_gm_brief_validates_and_writes_narrative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])
            with patch.multiple(operator, **dirs):
                operator.build_insight_packet()
                output = {
                    "narrative_markdown": (
                        "## Target Theses\nJayden Daniels remains the play here.\n\n"
                        "## Sell Windows\nNothing urgent this week.\n\n"
                        "## Manager Angles\nMelkor Lord of Light is stockpiling picks."
                    ),
                    "cited_evidence_ids": ["player:1:1"],
                }
                validation = operator.validate_daily_gm_brief_output(output)
                self.assertTrue(validation["valid"])
                self.assertTrue(operator.DAILY_GM_BRIEF_PATH.exists())
                brief_text = operator.DAILY_GM_BRIEF_PATH.read_text(encoding="utf-8")
                self.assertIn("## Sell Windows", brief_text)
                self.assertIn("model_mode: automatic_llm", brief_text)

    def test_daily_gm_brief_rejects_forbidden_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])
            with patch.multiple(operator, **dirs):
                operator.build_insight_packet()
                output = {
                    "narrative_markdown": (
                        "## Target Theses\nThe trade was sent and accepted already.\n\n"
                        "## Sell Windows\nNothing urgent this week.\n\n"
                        "## Manager Angles\nMelkor Lord of Light is stockpiling picks."
                    ),
                    "cited_evidence_ids": ["player:1:1"],
                }
                validation = operator.validate_daily_gm_brief_output(output)
                self.assertFalse(validation["valid"])
                self.assertTrue(any("forbidden language" in error for error in validation["errors"]))
                self.assertFalse(operator.DAILY_GM_BRIEF_PATH.exists())

    def test_daily_gm_brief_allows_common_words_used_non_transactionally(self) -> None:
        # Real production failure: a 388-word narrative was rejected for containing the bare
        # word "sent" in an ordinary, non-transactional football sentence. The narrative
        # validator must not flag common English words that happen to overlap with
        # FORBIDDEN_TERMS unless they appear near trade/offer/deal vocabulary.
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])
            with patch.multiple(operator, **dirs):
                operator.build_insight_packet()
                output = {
                    "narrative_markdown": (
                        "## Target Theses\nHis expanded role sent his value climbing this month.\n\n"
                        "## Sell Windows\nThe defense offered little resistance, which is not a signal here.\n\n"
                        "## Manager Angles\nIt is widely accepted that Melkor is rebuilding."
                    ),
                    "cited_evidence_ids": ["player:1:1"],
                }
                validation = operator.validate_daily_gm_brief_output(output)
                self.assertTrue(validation["valid"], validation["errors"])
                self.assertTrue(operator.DAILY_GM_BRIEF_PATH.exists())

    def test_daily_gm_brief_rejects_unknown_evidence_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])
            with patch.multiple(operator, **dirs):
                operator.build_insight_packet()
                output = {
                    "narrative_markdown": (
                        "## Target Theses\nSome text.\n\n## Sell Windows\nSome text.\n\n## Manager Angles\nSome text."
                    ),
                    "cited_evidence_ids": ["player:999:1"],
                }
                validation = operator.validate_daily_gm_brief_output(output)
                self.assertFalse(validation["valid"])
                self.assertTrue(any("unknown evidence" in error for error in validation["errors"]))

    def test_daily_gm_brief_tolerates_partial_citation_mismatch(self) -> None:
        # A narrative synthesizes dozens of evidence items across four sections; unlike a
        # single-entity card, dropping or misformatting one citation among several correct ones
        # shouldn't sink the whole brief. Only zero valid citations should be fatal.
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])
            with patch.multiple(operator, **dirs):
                operator.build_insight_packet()
                output = {
                    "narrative_markdown": (
                        "## Target Theses\nSome text.\n\n## Sell Windows\nSome text.\n\n## Manager Angles\nSome text."
                    ),
                    "cited_evidence_ids": ["player:1:1", "player:999:1"],
                }
                validation = operator.validate_daily_gm_brief_output(output)
                self.assertTrue(validation["valid"], validation["errors"])
                self.assertTrue(any("player:999:1" in warning for warning in validation["warnings"]))
                self.assertTrue(operator.DAILY_GM_BRIEF_PATH.exists())

    # --- Sprint 17: per-section article workflow ---------------------------------------

    def test_article_registry_has_synthesis_desks_and_loadable_prompts(self) -> None:
        from src import articles

        summaries = [article for article in articles.ARTICLES if article.is_summary]
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0].key, "daily_brief")
        self.assertEqual(summaries[1].key, "horizon_watch")
        # daily_brief keeps its long-standing filename so the existing bundle/badge wiring holds.
        self.assertEqual(summaries[0].output_filename, "daily_gm_brief.md")
        for article in articles.ARTICLES:
            self.assertTrue(articles.load_prompt(article.prompt_filename).strip(), article.key)

    def test_validate_article_output_rules(self) -> None:
        evidence_ids = {"player:1:1", "player:2:2"}
        headers = ("## Cornerstones", "## Shop Candidates")
        good = {
            "narrative_markdown": "## Cornerstones\nHis role sent his value climbing.\n\n## Shop Candidates\nSome names.",
            "cited_evidence_ids": ["player:1:1"],
        }
        good_validation = operator.validate_article_output(good, evidence_ids, headers)
        self.assertTrue(good_validation["valid"])
        self.assertEqual(good_validation["evidence_ids"], ["player:1:1"])

        forbidden = {
            "narrative_markdown": "## Cornerstones\nThe trade was sent and accepted.\n\n## Shop Candidates\nx.",
            "cited_evidence_ids": ["player:1:1"],
        }
        self.assertFalse(operator.validate_article_output(forbidden, evidence_ids, headers)["valid"])

        missing_header = {"narrative_markdown": "## Cornerstones\nOnly one header here.", "cited_evidence_ids": ["player:1:1"]}
        self.assertFalse(operator.validate_article_output(missing_header, evidence_ids, headers)["valid"])

        all_unknown = {
            "narrative_markdown": "## Cornerstones\nx.\n\n## Shop Candidates\nx.",
            "cited_evidence_ids": ["player:999:9"],
        }
        self.assertFalse(operator.validate_article_output(all_unknown, evidence_ids, headers)["valid"])

        partial = {
            "narrative_markdown": "## Cornerstones\nx.\n\n## Shop Candidates\nx.",
            "cited_evidence_ids": ["player:1:1", "player:999:9"],
        }
        partial_result = operator.validate_article_output(partial, evidence_ids, headers)
        self.assertTrue(partial_result["valid"])
        self.assertTrue(partial_result["warnings"])

    def test_article_editor_blocks_unqualified_projection_for_player_without_team(self) -> None:
        """Design source: AGENTS.md; historical baselines cannot print as active forecasts."""
        evidence = [
            {
                "evidence_id": "player:hill:1",
                "player_name": "Tyreek Hill",
                "current_availability_status": "no_current_nfl_team",
                "availability_note": "No current NFL team in Sleeper; historical baseline is conditional on signing",
                "source_ids": ["sleeper:players"],
            }
        ]
        bad = {
            "narrative_markdown": (
                "## Cornerstones\nTyreek Hill is projected for 15 points per game.\n\n"
                "## Shop Candidates\nReview the market."
            ),
            "cited_evidence_ids": ["player:hill:1"],
        }
        result = operator.validate_article_output(bad, {"player:hill:1"}, ("## Cornerstones", "## Shop Candidates"), evidence)
        self.assertFalse(result["valid"])
        self.assertTrue(any("no current NFL team" in error for error in result["errors"]))

        safe = {
            "narrative_markdown": (
                "## Cornerstones\nTyreek Hill has no current NFL team; his conditional baseline "
                "PPG is 15 if signed.\n\n## Shop Candidates\nReview the market."
            ),
            "cited_evidence_ids": ["player:hill:1"],
        }
        safe_result = operator.validate_article_output(
            safe, {"player:hill:1"}, ("## Cornerstones", "## Shop Candidates"), evidence
        )
        self.assertTrue(safe_result["valid"], safe_result["errors"])
        self.assertEqual(safe_result["boundary_checks"]["no_current_team_claims_reviewed"], 1)

    def test_article_editor_warns_when_injury_baseline_lacks_recovery_caveat(self) -> None:
        """Design source: docs/data_contract.md; rest-of-season PPG is not recovery-adjusted."""
        evidence = [
            {
                "evidence_id": "player:mix:1",
                "player_name": "Joe Mixon",
                "current_availability_status": "available",
                "injury_status": "Questionable",
                "source_ids": ["sleeper:players"],
            }
        ]
        output = {
            "narrative_markdown": (
                "## Cornerstones\nJoe Mixon projects for 15 points per game for the rest of season.\n\n"
                "## Shop Candidates\nReview the market."
            ),
            "cited_evidence_ids": ["player:mix:1"],
        }
        result = operator.validate_article_output(
            output, {"player:mix:1"}, ("## Cornerstones", "## Shop Candidates"), evidence
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(any("not recovery-adjusted" in warning for warning in result["warnings"]))

    def test_reporter_persona_contract_is_bounded_and_reaches_article_prompt(self) -> None:
        from src import articles
        from src.context import FantasyContext
        from src.personas import DEFAULT_PERSONA_ID, normalize_writer_preferences, persona_prompt_block, public_reporter_personas

        self.assertEqual(len(public_reporter_personas()), 4)
        normalized = normalize_writer_preferences({"persona_id": "not-real", "custom_instructions": "x" * 1200})
        self.assertEqual(normalized["persona_id"], DEFAULT_PERSONA_ID)
        self.assertEqual(len(normalized["custom_instructions"]), 800)

        prompt = operator._article_system_prompt(
            articles.ARTICLES[0],
            {"persona_id": "quant", "custom_instructions": "Compare picks to market value."},
        )
        self.assertIn("Reporter persona: The Quant", prompt)
        self.assertIn("Compare picks to market value.", prompt)
        self.assertIn("Never claim a trade", prompt)
        self.assertIn("The persona controls tone and emphasis only", persona_prompt_block(normalized))
        self.assertIn("rest-of-season baseline is not recovery-adjusted", articles.load_prompt("team_report.md"))
        self.assertIn("rest-of-season baseline is not recovery-adjusted", articles.load_prompt("market_watch.md"))
        self.assertIn("not dollar market values or cross-position price rankings", articles.load_prompt("team_report.md"))
        self.assertIn("dollar market values, or cross-position price rankings", articles.load_prompt("market_watch.md"))
        self.assertIn("fit_coverage", articles.load_prompt("market_watch.md"))

    def test_topline_article_scope_carries_news_matchup_and_move_context(self) -> None:
        """Encodes docs/front_office_realization_epic.md's authored-publication evidence seam."""
        from src import articles

        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp)
            (processed / "player_dossiers.csv").write_text(
                "roster_id,player_id,player_name,position,market_value,projected_ppg,availability_note,signal_label,news_impact,source_trace\n"
                "2,101,Anchor QB,QB,70,20.0,No current Sleeper injury flag; baseline projection,core_hold,,projection\n",
                encoding="utf-8",
            )
            (processed / "league_news_impact.csv").write_text(
                "event_id,published_at,player_id,player_name,roster_id,impact_type,evidence,risk,confidence,source_trace\n"
                "news-1,2026-08-25T12:00:00Z,101,Anchor QB,2,role_or_value_change,Anchor QB named starter,medium,high,source-news\n"
                "news-2,2026-08-25T13:00:00Z,202,League Rival,4,market_heat,Rival player trending,medium,medium,source-news\n",
                encoding="utf-8",
            )
            (processed / "matchups.csv").write_text(
                "season,league_id,week,matchup_id,roster_id,opponent_roster_id,opponent_team_name,points_for,points_against,margin,result,source_trace\n"
                "2026,league-1,1,match-1,2,4,Rival Team,18.0,14.0,4.0,win,source-matchup\n",
                encoding="utf-8",
            )
            (processed / "trades.csv").write_text(
                "season,week,transaction_id,team_a_roster_id,team_a_name,team_a_players_received,team_a_picks_received,team_a_faab_received,team_b_roster_id,team_b_name,team_b_players_received,team_b_picks_received,team_b_faab_received\n"
                "2026,1,trade-1,2,My Team,Anchor QB,,0,4,Rival Team,Other Player,2027 R2,0\n",
                encoding="utf-8",
            )
            (processed / "waivers.csv").write_text(
                "season,week,transaction_id,roster_id,player_added,player_dropped,waiver_bid\n"
                "2026,1,waiver-1,2,Depth WR,Depth RB,12\n",
                encoding="utf-8",
            )

            context = articles.ArticleContext(
                analysis_dir=Path(tmp),
                active_roster_id=2,
                processed_dir=processed,
                league_id="league-1",
                season="2026",
            )
            evidence = articles._scope_team_report(context)
            by_type = {kind: [row for row in evidence if row["entity_type"] == kind] for kind in ("player", "news", "matchup", "transaction")}
            self.assertTrue(by_type["player"])
            self.assertEqual(len(by_type["news"]), 2)
            self.assertEqual(len(by_type["matchup"]), 1)
            self.assertEqual(len(by_type["transaction"]), 2)
            self.assertTrue(any(row["scope"] == "selected_roster" for row in by_type["news"]))
            self.assertTrue(any(row["scope"] == "league_context" for row in by_type["news"]))
            self.assertEqual({row["league_id"] for row in by_type["news"]}, {"league-1"})
            self.assertTrue(all("league-1" not in row["text"] or row["entity_type"] != "matchup" for row in evidence))

    def test_two_league_vertical_keeps_profiles_writers_and_reader_bundles_isolated(self) -> None:
        """The core personalized-reader path must work for two leagues in one account.

        This intentionally crosses the persistence, writer, and browser boundaries in one
        test.  A passing unit test for each layer alone would not catch a legacy singleton
        being read again between those handoffs.
        """
        from app import db
        from src.browser_site import build_browser_site
        from src.context import context_from_league_row, scoped_config
        from src.league_paths import LeaguePaths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "app.db"
            users_root = root / "users"
            with patch.object(db, "DB_PATH", database_path), patch("src.league_paths.USERS_ROOT", users_root):
                db.init_db()
                user_id = int(db.get_or_create_user("vertical-user")["id"])
                leagues = {
                    "league-alpha": {
                        "team_name": "Alpha Custom",
                        "persona_id": "scout",
                        "strategy": "Role-first rebuild",
                        "roster_id": 2,
                    },
                    "league-beta": {
                        "team_name": "Beta Custom",
                        "persona_id": "quant",
                        "strategy": "Numbers-first contender",
                        "roster_id": 7,
                    },
                }
                paths_by_league: dict[str, LeaguePaths] = {}
                contexts: dict[str, FantasyContext] = {}

                for league_id, details in leagues.items():
                    profile = db.upsert_team_profile(
                        user_id,
                        league_id,
                        {
                            "roster_id": details["roster_id"],
                            "season": "2026",
                            "team_name": details["team_name"],
                            "strategy_profile": {"name": details["strategy"], "team_direction": "rebuild"},
                            "writer_preferences": {
                                "persona_id": details["persona_id"],
                                "custom_instructions": f"Keep the {league_id} read distinctive.",
                            },
                        },
                    )
                    league = {
                        "league_id": league_id,
                        "season": "2026",
                        "league_type": "dynasty",
                        "name": league_id.title(),
                        "roster_id": details["roster_id"],
                    }
                    db.upsert_user_league(user_id, league)
                    db.upsert_manager_trade_profile(
                        user_id,
                        league_id,
                        11,
                        {
                            "manager_name": f"{league_id} manager",
                            "trade_style": "pick seller",
                            "preferred_assets": "young receivers",
                            "protected_assets": "future firsts",
                            "editor_note": f"Keep the {league_id} manager note private and contextual.",
                        },
                    )
                    paths = LeaguePaths.for_user_league(user_id, league_id)
                    paths.ensure()
                    paths_by_league[league_id] = paths
                    contexts[league_id] = context_from_league_row(
                        str(user_id),
                        league,
                        profile,
                        manager_trade_profiles=db.list_manager_trade_profiles(user_id, league_id),
                    )

                    prefix = "Alpha" if league_id.endswith("alpha") else "Beta"
                    pd.DataFrame(
                        [{
                            "roster_id": details["roster_id"],
                            "player_id": f"{prefix.lower()}-player",
                            "player_name": f"{prefix} Player",
                            "position": "WR",
                            "market_value": 70,
                            "projected_ppg": 16,
                            "signal_label": "productive_hold",
                            "news_impact": "role stable",
                        }]
                    ).to_csv(paths.processed_dir / "player_dossiers.csv", index=False)
                    pd.DataFrame(
                        [{
                            "season": "2026",
                            "roster_id": details["roster_id"],
                            "team_name": f"Sleeper {prefix}",
                            "display_name": f"manager-{prefix.lower()}",
                            "is_my_team": "true",
                        }]
                    ).to_csv(paths.processed_dir / "teams.csv", index=False)
                    pd.DataFrame(
                        [{
                            "season": "2026",
                            "roster_id": details["roster_id"],
                            "player_id": f"{prefix.lower()}-player",
                            "player_name": f"{prefix} Player",
                            "is_my_team": "true",
                        }]
                    ).to_csv(paths.processed_dir / "roster_players.csv", index=False)
                    for filename, items in (
                        ("target_theses.json", [{"player_id": f"{prefix.lower()}-target", "player_name": f"{prefix} Target", "analysis_text": f"{prefix} target evidence."}]),
                        ("sell_theses.json", [{"player_id": f"{prefix.lower()}-sell", "player_name": f"{prefix} Sell", "analysis_text": f"{prefix} sell evidence."}]),
                        ("trade_theses.json", [{"target_manager_roster_id": 11, "target_manager_name": f"{prefix} Manager", "analysis_text": f"{prefix} manager angle."}]),
                        ("manager_dossiers.json", [{"dossier_id": "manager-001", "roster_id": 11, "team_name": f"{prefix} Manager", "dynasty_cycle": "rebuild", "analysis_text": f"{prefix} manager evidence.", "outcome_summary": {"status": "not_recorded", "record": "not recorded", "narrative": "Season outcomes are not recorded in this source snapshot.", "evidence": "manager_season_history; outcome_status=not_recorded"}, "sample_size": {"matchups": 0}}]),
                    ):
                        (paths.analysis_dir / filename).write_text(json.dumps({"items": items}), encoding="utf-8")

                prompts: dict[str, list[str]] = {"alpha": [], "beta": []}

                def fake_article(system_prompt, evidence, api_key, model, editorial_context=None):
                    key = "alpha" if "Team: Alpha Custom" in system_prompt else "beta"
                    prompts[key].append(system_prompt)
                    marker = "Alpha" if key == "alpha" else "Beta"
                    evidence_id = evidence[0]["evidence_id"]
                    return {
                        "narrative_markdown": (
                            f"## Cornerstones\n{marker} report.\n\n## Shop Candidates\n{marker} names.\n\n"
                            f"## Buy-Low Targets\n{marker} buys.\n\n## Sell-High Windows\n{marker} sells.\n\n"
                            f"## Best Fits\n{marker} fits.\n\n## Steer Clear\n{marker} fades.\n\n"
                            f"## Contenders\n{marker} contenders.\n\n## Rebuilders\n{marker} rebuilders.\n\n"
                            f"## Target Theses\n{marker} targets.\n\n## Sell Windows\n{marker} windows.\n\n"
                            f"## Manager Angles\n{marker} angles."
                        ),
                        "cited_evidence_ids": [evidence_id],
                    }

                with patch.dict(
                    os.environ,
                    {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                    clear=False,
                ), patch.object(
                    operator, "generate_article_via_llm", side_effect=fake_article
                ):
                    results = {
                        league_id: operator.generate_articles_workflow(paths_by_league[league_id], contexts[league_id])
                        for league_id in leagues
                    }

                for league_id, details in leagues.items():
                    paths = paths_by_league[league_id]
                    result = results[league_id]
                    self.assertEqual(result["state"], "complete")
                    report = (paths.analysis_dir / "team_report.md").read_text(encoding="utf-8")
                    self.assertIn("model_mode: automatic_llm", report)
                    self.assertIn(f"reporter_persona: {details['persona_id']}", report)

                    build_browser_site(
                        paths.site_dir,
                        paths.processed_dir,
                        paths.analysis_dir,
                        league_id=league_id,
                        config=scoped_config({}, contexts[league_id]),
                    )
                    html = (paths.site_dir / "index.html").read_text(encoding="utf-8")
                    self.assertIn("manager-outcome-receipt", html)
                    self.assertIn("league-standings", html)
                    self.assertIn("Scored Matchups", html)
                    bundle = json.loads((paths.site_dir / "data" / "app_bundle.json").read_text(encoding="utf-8"))
                    self.assertEqual(bundle["leagueId"], league_id)
                    self.assertEqual(bundle["myTeamName"], details["team_name"])
                    self.assertEqual(bundle["reporterPersona"]["persona_id"], details["persona_id"])
                    self.assertEqual(bundle["strategyProfile"]["name"], details["strategy"])
                    self.assertEqual(bundle["managerTradeProfiles"][0]["trade_style"], "pick seller")
                    self.assertIn("Alpha" if league_id.endswith("alpha") else "Beta", bundle["analysis"]["teamReport"])
                    editorial = json.loads((paths.site_dir / "data" / "editorial_issue.json").read_text(encoding="utf-8"))
                    self.assertEqual(editorial["signal_summary"]["custom_manager_profiles"], 1)
                    profile_story = next(
                        story for story in editorial["stories"] if story["story_id"] == "manager:note:11"
                    )
                    self.assertIn(league_id, profile_story["dek"])

                self.assertTrue(prompts["alpha"])
                self.assertTrue(prompts["beta"])
                self.assertTrue(all("Team: Beta Custom" not in prompt for prompt in prompts["alpha"]))
                self.assertTrue(all("Team: Alpha Custom" not in prompt for prompt in prompts["beta"]))

                connection = sqlite3.connect(database_path)
                try:
                    artifact_rows = connection.execute(
                        "SELECT league_id, path, source_json FROM content_artifacts ORDER BY league_id"
                    ).fetchall()
                finally:
                    connection.close()
                artifact_leagues = {row[0] for row in artifact_rows}
                self.assertEqual(artifact_leagues, set(leagues))
                for league_id, path, source_json in artifact_rows:
                    self.assertIn(f"/leagues/{league_id}/", path.replace("\\", "/"))
                    self.assertIn(leagues[league_id]["persona_id"], source_json)

    def _seed_article_inputs(self, analysis_dir: Path, processed_dir: Path) -> None:
        processed_dir.mkdir(parents=True, exist_ok=True)
        (processed_dir / "player_dossiers.csv").write_text(
            "player_id,player_name,position,roster_id,market_value,projected_ppg,signal_label,news_impact,source_trace\n"
            "1,Jayden Daniels,QB,2,90,21.1,productive_hold,,nflverse:test\n"
            "2,Tank Dell,WR,2,40,10.6,sell_candidate,,nflverse:test\n",
            encoding="utf-8",
        )
        for filename, items in (
            ("target_theses.json", [{"player_id": "1", "player_name": "Jayden Daniels", "analysis_text": "Buy-low angle.", "source_trace": "analysis:target_theses"}]),
            ("sell_theses.json", [{"player_id": "2", "player_name": "Tank Dell", "analysis_text": "Sell-high angle.", "source_trace": "analysis:sell_theses"}]),
            ("trade_theses.json", [{"target_manager_roster_id": 3, "target_manager_name": "The Clapper", "analysis_text": "Trade angle.", "source_trace": "analysis:trade_theses"}]),
            ("manager_dossiers.json", [{"roster_id": 3, "team_name": "The Clapper", "dynasty_cycle": "rebuild", "analysis_text": "Rebuild read.", "source_trace": "analysis:manager_dossiers"}]),
        ):
            (analysis_dir / filename).write_text(json.dumps({"items": items}), encoding="utf-8")

    def test_generate_articles_workflow_reports_partial_success(self) -> None:
        from src import articles

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)

            def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002 - match requests signature
                import json as _json

                system = json["system"]
                evidence = _json.loads(json["messages"][0]["content"])["evidence"]
                eid = evidence[0]["evidence_id"] if evidence else "player:1:1"
                # Every article shares one narrative carrying all possible headers, but the Team
                # Report call deliberately trips the forbidden-language check so exactly one fails.
                narrative = (
                    "## Cornerstones\nSolid core.\n\n## Shop Candidates\nSome names.\n\n"
                    "## Buy-Low Targets\nx\n\n## Sell-High Windows\nx\n\n## Best Fits\nx\n\n## Steer Clear\nx\n\n"
                    "## Contenders\nx\n\n## Rebuilders\nx\n\n## Target Theses\nx\n\n## Sell Windows\nx\n\n## Manager Angles\nx"
                )
                if "Your Team Report" in system:
                    narrative = narrative.replace("Solid core.", "The trade was sent and accepted already.")
                resp = MagicMock()
                resp.raise_for_status = lambda: None
                resp.json = lambda: {
                    "stop_reason": "end_turn",
                    "content": [{"type": "tool_use", "name": "emit_article", "input": {"narrative_markdown": narrative, "cited_evidence_ids": [eid]}}],
                }
                return resp

            with patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
            ), \
                 patch.object(operator, "ANALYSIS_DIR", analysis), \
                 patch.object(articles, "PROCESSED_DIR", processed), \
                 patch.object(articles, "resolve_active_roster_id", return_value=2), \
                 patch.object(operator.requests, "post", side_effect=fake_post):
                result = operator.generate_articles_workflow()

            self.assertEqual(result["state"], "partial")
            self.assertEqual(result["articles"]["team_report"]["state"], "failed")
            self.assertEqual(result["articles"]["market_watch"]["state"], "complete")
            self.assertEqual(result["articles"]["daily_brief"]["state"], "complete")
            # The failed article was never written; a successful one carries the LLM marker.
            self.assertFalse((analysis / "team_report.md").exists())
            market_watch_text = (analysis / "market_watch.md").read_text(encoding="utf-8")
            self.assertIn("model_mode: automatic_llm", market_watch_text)
            self.assertIn("source_receipt_json:", market_watch_text)

    def test_targeted_writer_retry_skips_unselected_desks(self) -> None:
        from src import articles

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)
            calls = []

            def fake_article(system_prompt, evidence, api_key, model, editorial_context=None):
                calls.append(system_prompt)
                return {
                    "narrative_markdown": "## Buy-Low Targets\nInvestigate the evidence.\n\n## Sell-High Windows\nKeep the price discipline.",
                    "cited_evidence_ids": [evidence[0]["evidence_id"]],
                }

            with patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                clear=False,
            ), patch.object(operator, "ANALYSIS_DIR", analysis), patch.object(operator, "PROCESSED_DIR", processed), patch.object(
                articles, "PROCESSED_DIR", processed
            ), patch.object(operator, "generate_article_via_llm", side_effect=fake_article):
                result = operator.generate_articles_workflow(article_keys={"market_watch"})

            self.assertEqual(result["state"], "complete")
            self.assertEqual(set(result["articles"]), {"market_watch"})
            self.assertEqual(len(calls), 1)
            self.assertTrue((analysis / "market_watch.md").is_file())
            self.assertFalse((analysis / "team_report.md").exists())

    def test_generate_articles_reuses_current_receipts_without_another_llm_call(self) -> None:
        from app import db
        from src.context import FantasyContext

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)
            database_path = root / "app.db"
            narrative = (
                "## Cornerstones\nCore report.\n\n## Shop Candidates\nNames.\n\n"
                "## Buy-Low Targets\nBuys.\n\n## Sell-High Windows\nSells.\n\n"
                "## Best Fits\nFits.\n\n## Steer Clear\nFades.\n\n"
                "## Contenders\nContenders.\n\n## Rebuilders\nRebuilders.\n\n"
                "## Target Theses\nTargets.\n\n## Sell Windows\nWindows.\n\n## Manager Angles\nAngles."
            )
            calls = []

            def fake_article(system_prompt, evidence, api_key, model, editorial_context=None):
                calls.append(system_prompt)
                return {"narrative_markdown": narrative, "cited_evidence_ids": [evidence[0]["evidence_id"]]}

            with patch.object(db, "DB_PATH", database_path), patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                clear=False,
            ), patch.object(operator, "ANALYSIS_DIR", analysis), patch.object(operator, "PROCESSED_DIR", processed), patch.object(
                operator, "generate_article_via_llm", side_effect=fake_article
            ):
                db.init_db()
                user_id = int(db.get_or_create_user("receipt-reuse")["id"])
                context = FantasyContext(
                    user_id=str(user_id),
                    league_id="receipt-league",
                    season="2026",
                    roster_id=2,
                    team_name="Receipt Team",
                )
                first = operator.generate_articles_workflow(context=context)
                first_call_count = len(calls)
                second = operator.generate_articles_workflow(context=context)

            self.assertEqual(first["state"], "complete")
            self.assertEqual(second["state"], "complete")
            self.assertEqual(first_call_count, len(calls))
            self.assertTrue(all(item["state"] in {"unchanged", "skipped"} for item in second["articles"].values()))

    def test_writer_plan_matches_reuse_after_a_multi_desk_run(self) -> None:
        """Design source: AGENTS.md; the no-cost plan must use the same reuse key as the real run."""
        from app import db
        from src import articles
        from src.context import FantasyContext

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)
            (processed / "player_horizon_market_scores.csv").write_text(
                "season,league_id,player_id,player_name,position,value_lane,next_game_market_score,source_trace\n"
                "2026,writer-plan-league,horizon-1,Horizon Player,WR,balanced_window,50,test:horizon\n",
                encoding="utf-8",
            )
            database_path = root / "app.db"
            narrative = (
                "## Cornerstones\nCore report.\n\n## Shop Candidates\nNames.\n\n"
                "## Buy-Low Targets\nBuys.\n\n## Sell-High Windows\nSells.\n\n"
                "## Best Fits\nFits.\n\n## Steer Clear\nFades.\n\n"
                "## Contenders\nContenders.\n\n## Rebuilders\nRebuilders.\n\n"
                "## Target Theses\nTargets.\n\n## Sell Windows\nWindows.\n\n"
                "## Manager Angles\nAngles.\n\n## This Week\nThis week.\n\n"
                "## Rest of Season\nSeason.\n\n## Dynasty Window\nDynasty.\n\n"
                "## Market vs Clock\nCompare the clocks.\n\n## Contender vs Rebuilder\nFit."
            )

            def fake_article(system_prompt, evidence, api_key, model, editorial_context=None):
                return {
                    "headline": "Desk read",
                    "dek": "A bounded read.",
                    "lede": "The packet supports a bounded read.",
                    "thesis": "The evidence supports a measured decision.",
                    "what_changed": "The current packet changed.",
                    "counter_evidence": "The sample remains limited.",
                    "action": "Compare the evidence before acting.",
                    "risk": "The estimate may be wrong.",
                    "confidence": "medium",
                    "visual_brief": "Use a simple evidence rail.",
                    "narrative_markdown": narrative,
                    "cited_evidence_ids": [evidence[0]["evidence_id"]],
                }

            with patch.object(db, "DB_PATH", database_path), patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"},
                clear=False,
            ), patch.object(operator, "ANALYSIS_DIR", analysis), patch.object(operator, "PROCESSED_DIR", processed), patch.object(
                articles, "PROCESSED_DIR", processed
            ), patch.object(operator, "generate_article_via_llm", side_effect=fake_article):
                db.init_db()
                user_id = int(db.get_or_create_user("writer-plan-parity")["id"])
                context = FantasyContext(
                    user_id=str(user_id),
                    league_id="writer-plan-league",
                    season="2026",
                    roster_id=2,
                    team_name="Plan Parity Team",
                )
                generated = operator.generate_articles_workflow(context=context)
                plan = operator.plan_articles_workflow(context=context)
                dossier_path = processed / "player_dossiers.csv"
                dossier_path.write_text(
                    dossier_path.read_text(encoding="utf-8").replace("Jayden Daniels", "Jayden Daniels Updated"),
                    encoding="utf-8",
                )
                changed_plan = operator.plan_articles_workflow(context=context)

            self.assertEqual(generated["state"], "complete")
            self.assertEqual(plan["state"], "ready")
            self.assertEqual(plan["counts"]["generate"], 0)
            self.assertEqual(plan["counts"]["reuse"], len(articles.ARTICLES))
            self.assertTrue(all(item["decision"] == "reuse" for item in plan["articles"].values()))
            self.assertEqual(changed_plan["articles"]["daily_brief"]["decision"], "generate")
            self.assertEqual(changed_plan["articles"]["daily_brief"]["state"], "ready")

    def test_explicit_llm_editor_reviews_each_writer_draft_and_persists_receipt(self) -> None:
        from src import articles

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)
            narrative = (
                "## Cornerstones\nCore report.\n\n## Shop Candidates\nNames.\n"
                "\n## Buy-Low Targets\nBuys.\n\n## Sell-High Windows\nSells.\n"
                "\n## Best Fits\nFits.\n\n## Steer Clear\nFades.\n"
                "\n## Contenders\nContenders.\n\n## Rebuilders\nRebuilders.\n"
                "\n## Target Theses\nTargets.\n\n## Sell Windows\nWindows.\n"
                "\n## Manager Angles\nAngles.\n\n## This Week\nThis week.\n"
                "\n## Rest of Season\nSeason.\n\n## Dynasty Window\nDynasty.\n"
                "\n## Market vs Clock\nCompare the clocks.\n\n## Contender vs Rebuilder\nFit."
            )
            writer_calls: list[str] = []
            editor_calls: list[str] = []

            def fake_article(system_prompt, evidence, api_key, model, editorial_context=None):
                writer_calls.append(model)
                return {
                    "headline": "Desk read",
                    "dek": "A bounded read.",
                    "lede": "The packet supports a bounded read.",
                    "thesis": "The evidence supports a measured decision.",
                    "what_changed": "The current packet changed.",
                    "counter_evidence": "The sample remains limited.",
                    "action": "Compare the evidence before acting.",
                    "risk": "The estimate may be wrong.",
                    "confidence": "medium",
                    "visual_brief": "Use a simple evidence rail.",
                    "narrative_markdown": narrative,
                    "cited_evidence_ids": [evidence[0]["evidence_id"]],
                }

            def fake_editor(system_prompt, evidence, draft, api_key, model):
                editor_calls.append(model)
                return {
                    **draft,
                    "decision": "modify",
                    "editor_notes": "Added a bounded evidence caveat.",
                    "changes": ["Clarified that the read is not a universal price."],
                    "narrative_markdown": narrative.replace("Core report.", "Core report with a bounded caveat."),
                    "cited_evidence_ids": [evidence[0]["evidence_id"]],
                }

            with patch.dict(
                os.environ,
                {
                    "FRONT_OFFICE_LLM_PROVIDER": "anthropic",
                    "ANTHROPIC_API_KEY": "test-key",
                    "FRONT_OFFICE_EDITOR_MODE": "llm",
                },
                clear=False,
            ), patch.object(operator, "ANALYSIS_DIR", analysis), patch.object(operator, "PROCESSED_DIR", processed), patch.object(
                articles, "PROCESSED_DIR", processed
            ), patch.object(operator, "generate_article_via_llm", side_effect=fake_article), patch.object(
                operator, "review_article_via_llm", side_effect=fake_editor
            ):
                result = operator.generate_articles_workflow()

            self.assertEqual(result["state"], "complete", result)
            self.assertEqual(result["editor_mode"], "llm")
            self.assertEqual(len(writer_calls), len(editor_calls))
            self.assertGreaterEqual(len(editor_calls), 5)
            report = (analysis / "team_report.md").read_text(encoding="utf-8")
            self.assertIn("editorial_review_json:", report)
            front_matter = report.split("editorial_review_json: ", 1)[1].split("\n---", 1)[0]
            review = json.loads(front_matter)
            self.assertEqual(review["mode"], "llm")
            self.assertEqual(review["status"], "approved")
            self.assertEqual(review["decision"], "modify")

    def test_editor_provider_failure_persists_a_held_receipt_instead_of_silent_fallback(self) -> None:
        from src import articles

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)
            narrative = (
                "## Cornerstones\nCore report.\n\n## Shop Candidates\nNames.\n"
                "\n## Buy-Low Targets\nBuys.\n\n## Sell-High Windows\nSells.\n"
                "\n## Best Fits\nFits.\n\n## Steer Clear\nFades.\n"
                "\n## Contenders\nContenders.\n\n## Rebuilders\nRebuilders.\n"
                "\n## Target Theses\nTargets.\n\n## Sell Windows\nWindows.\n"
                "\n## Manager Angles\nAngles.\n\n## This Week\nThis week.\n"
                "\n## Rest of Season\nSeason.\n\n## Dynasty Window\nDynasty.\n"
                "\n## Market vs Clock\nCompare the clocks.\n\n## Contender vs Rebuilder\nFit."
            )

            def fake_article(system_prompt, evidence, api_key, model, editorial_context=None):
                return {
                    "headline": "Desk read",
                    "dek": "A bounded read.",
                    "lede": "The packet supports a bounded read.",
                    "thesis": "The evidence supports a measured decision.",
                    "what_changed": "The current packet changed.",
                    "counter_evidence": "The sample remains limited.",
                    "action": "Compare the evidence before acting.",
                    "risk": "The estimate may be wrong.",
                    "confidence": "medium",
                    "visual_brief": "Use a simple evidence rail.",
                    "narrative_markdown": narrative,
                    "cited_evidence_ids": [evidence[0]["evidence_id"]],
                }

            with patch.dict(
                os.environ,
                {
                    "FRONT_OFFICE_LLM_PROVIDER": "anthropic",
                    "ANTHROPIC_API_KEY": "test-key",
                    "FRONT_OFFICE_EDITOR_MODE": "llm",
                },
                clear=False,
            ), patch.object(operator, "ANALYSIS_DIR", analysis), patch.object(operator, "PROCESSED_DIR", processed), patch.object(
                articles, "PROCESSED_DIR", processed
            ), patch.object(operator, "generate_article_via_llm", side_effect=fake_article), patch.object(
                operator, "review_article_via_llm", side_effect=RuntimeError("provider unavailable")
            ):
                result = operator.generate_articles_workflow()

            self.assertEqual(result["state"], "partial", result)
            self.assertEqual(result["articles"]["team_report"]["state"], "held")
            report = (analysis / "team_report.md").read_text(encoding="utf-8")
            front_matter = report.split("editorial_review_json: ", 1)[1].split("\n---", 1)[0]
            review = json.loads(front_matter)
            self.assertEqual(review["status"], "held")
            self.assertEqual(review["decision"], "hold")
            self.assertIn("RuntimeError", review["errors"][-1])

    def test_article_generation_plan_is_read_only_and_reports_missing_writer_key(self) -> None:
        """Encodes the cost gate: plan the six desks without invoking the provider."""
        from app import db
        from src import articles
        from src.context import FantasyContext

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            processed = root / "processed"
            analysis.mkdir(parents=True)
            self._seed_article_inputs(analysis, processed)
            database_path = root / "app.db"

            with patch.object(db, "DB_PATH", database_path), patch.dict(
                os.environ,
                {"FRONT_OFFICE_LLM_PROVIDER": "openai", "OPENAI_API_KEY": ""},
                clear=False,
            ), patch.object(operator, "ANALYSIS_DIR", analysis), patch.object(operator, "PROCESSED_DIR", processed), patch.object(
                operator, "generate_article_via_llm"
            ) as generate:
                db.init_db()
                user_id = int(db.get_or_create_user("generation-plan")['id'])
                context = FantasyContext(
                    user_id=str(user_id),
                    league_id="generation-plan-league",
                    season="2026",
                    roster_id=2,
                    team_name="Plan Team",
                )
                plan = operator.plan_articles_workflow(context=context)

            generate.assert_not_called()
            self.assertEqual(set(plan["articles"]), {article.key for article in articles.ARTICLES})
            self.assertGreater(plan["counts"]["blocked"], 0)
            self.assertIn("No provider request was made", plan["message"])
            self.assertNotIn("OPENAI_API_KEY=", json.dumps(plan))

    def test_chat_context_markdown_includes_manager_and_player_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._operator_dirs(Path(tmp))
            self._seed_dossiers(dirs["ANALYSIS_DIR"])

            with patch.multiple(operator, **dirs):
                result = operator.build_chat_context_markdown()

        self.assertEqual(result["state"], "complete")
        markdown = result["markdown"]
        self.assertTrue(markdown.startswith("# Dynasty League Context"))
        self.assertIn("## Managers", markdown)
        self.assertIn("## Players", markdown)
        self.assertIn("Melkor Lord of Light", markdown)
        self.assertIn("Jayden Daniels", markdown)

    def test_processed_table_contract_columns_exist(self) -> None:
        processed = Path(__file__).resolve().parents[1] / "data" / "processed"
        missing_files = []
        for table, required_columns in EXPECTED_TABLE_COLUMNS.items():
            path = processed / f"{table}.csv"
            if not path.exists():
                missing_files.append(path.name)
                continue
            columns = set(pd.read_csv(path, nrows=0).columns)
            missing = [column for column in required_columns if column not in columns]
            self.assertEqual(missing, [], f"{table}.csv missing required columns")
        self.assertEqual(missing_files, [])

    def test_decision_support_tables_have_trace_or_evidence_columns(self) -> None:
        expected = {
            "market_value_sources": ["source", "source_access_type", "source_confidence", "source_trace", "checked_at"],
            "market_consensus_values": ["source_count", "disagreement_score", "confidence", "source_trace"],
            "player_market_values": ["source", "source_trace"],
            "pick_market_values": ["source", "source_trace"],
            "team_asset_inventory": ["source_trace"],
            "liquidity_scores": ["source_trace"],
            "asset_market_gaps": ["evidence", "risk", "confidence", "source_trace"],
            "opportunity_board": ["evidence", "risk", "confidence", "source_trace"],
            "source_freshness": ["source", "dataset", "status", "source_url", "cache_path"],
            "news_events": ["source", "source_trace"],
            "player_news_matches": ["source", "source_trace", "match_confidence"],
            "league_news_impact": ["evidence", "risk", "confidence", "source_trace"],
            "news_source_freshness": ["source", "dataset", "status", "source_url", "cache_path"],
            "player_projection_season": ["projection_method", "projection_confidence", "source_trace"],
            "player_projection_weekly": ["projection_method", "projection_confidence", "source_trace"],
            "available_player_horizon_scores": ["availability_status", "identity_status", "market_value", "fit_coverage", "evidence", "risk", "confidence", "source_trace"],
            "projection_source_freshness": ["source", "dataset", "status", "source_url", "cache_path"],
            "projection_source_components": ["source", "source_confidence", "source_trace", "checked_at"],
            "source_accuracy_scores": ["sample_size", "accuracy_confidence", "source_trace"],
            "today_priority_board": ["item_type", "priority_score", "why", "evidence", "source_trace"],
            "player_signal_scores": ["evidence", "risk", "confidence", "source_trace"],
            "breakout_candidates": ["evidence", "risk", "confidence", "source_trace"],
            "sell_candidates": ["evidence", "risk", "confidence", "source_trace"],
            "projection_market_gaps": ["evidence", "risk", "confidence", "source_trace"],
            "news_market_edges": ["evidence", "risk", "confidence", "source_trace"],
            "team_fit_scores": ["evidence", "risk", "confidence", "source_trace"],
            "action_recommendations": ["consumer_label", "why", "evidence", "risk", "confidence", "source_trace"],
            "manager_valuation_profiles": ["evidence", "confidence", "label"],
            "counterparty_trade_edges": ["evidence", "risk", "confidence", "source_trace"],
            "manager_profile_tags": ["evidence", "risk", "confidence", "source_trace"],
            "manager_cycle_profiles": ["evidence", "confidence"],
            "player_dossiers": ["source_trace"],
            "player_transaction_history": ["evidence", "source_trace"],
            "player_profile_tags": ["evidence", "risk", "confidence", "source_trace"],
        }
        processed = Path(__file__).resolve().parents[1] / "data" / "processed"
        for table, required_columns in expected.items():
            columns = set(pd.read_csv(processed / f"{table}.csv", nrows=0).columns)
            self.assertTrue(set(required_columns).issubset(columns), table)

    def test_refresh_metadata_contract_is_present(self) -> None:
        processed = Path(__file__).resolve().parents[1] / "data" / "processed"
        metadata = pd.read_csv(processed / "refresh_metadata.csv").fillna("")
        self.assertEqual(len(metadata), 1)
        row = metadata.iloc[0]
        for column in EXPECTED_TABLE_COLUMNS["refresh_metadata"]:
            self.assertIn(column, metadata.columns)
            self.assertNotEqual(str(row[column]), "", column)

    def test_generated_csv_outputs_are_replace_style_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.csv"
            first = pd.DataFrame([{"id": 1}, {"id": 2}])
            second = pd.DataFrame([{"id": 3}])
            first.to_csv(path, index=False)
            second.to_csv(path, index=False)

            result = pd.read_csv(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(int(result.iloc[0]["id"]), 3)

    def test_identity_resolution_uses_configured_roster_id(self) -> None:
        users = [
            {"user_id": "u1", "display_name": "other", "metadata": {"team_name": "Other"}},
            {"user_id": "u2", "display_name": "joe3489", "metadata": {"team_name": "Melkor Lord of Light"}},
        ]
        rosters = [{"roster_id": 1, "owner_id": "u1"}, {"roster_id": 2, "owner_id": "u2"}]

        roster_map, my_roster_id = build_roster_maps(rosters, users, "joe3489", "Melkor Lord of Light", 2)

        self.assertEqual(my_roster_id, 2)
        self.assertEqual(roster_map[2]["team_name"], "Melkor Lord of Light")

    def test_stale_team_name_cannot_override_configured_roster_id(self) -> None:
        users = [
            {"user_id": "u2", "display_name": "joe3489", "metadata": {"team_name": "Melkor Lord of Light"}},
            {"user_id": "u4", "display_name": "Crumplesacks", "metadata": {"team_name": "Moose Caboose"}},
        ]
        rosters = [{"roster_id": 2, "owner_id": "u2"}, {"roster_id": 4, "owner_id": "u4"}]

        _, my_roster_id = build_roster_maps(rosters, users, "joe3489", "Moose Caboose", 2)

        self.assertEqual(my_roster_id, 2)

    def test_players_table_exports_canonical_fields(self) -> None:
        rows = players_table(
            {
                "4881": {
                    "full_name": "Lamar Jackson",
                    "position": "QB",
                    "team": "BAL",
                    "age": 29,
                    "years_exp": 8,
                    "fantasy_positions": ["QB"],
                    "status": "Active",
                }
            }
        )

        self.assertEqual(rows[0]["player_id"], "4881")
        self.assertEqual(rows[0]["full_name"], "Lamar Jackson")
        self.assertEqual(rows[0]["fantasy_positions"], "QB")

    def test_player_availability_is_preserved_and_baseline_projection_is_explicit(self) -> None:
        rows = players_table(
            {
                "3321": {
                    "full_name": "Tyreek Hill",
                    "position": "WR",
                    "team": "MIA",
                    "injury_status": "Questionable",
                    "injury_body_part": "Knee - ACL",
                }
            }
        )

        self.assertEqual(rows[0]["injury_status"], "Questionable")
        self.assertEqual(rows[0]["injury_body_part"], "Knee - ACL")
        self.assertIn("baseline projection", _availability_note("Questionable", "Knee - ACL"))
        self.assertIn("No current Sleeper injury flag", _availability_note("", ""))

    def test_pick_ownership_flags_melkor_2027_first(self) -> None:
        roster_map = {
            2: {"team_name": "Melkor Lord of Light"},
            8: {"team_name": "The Clapper"},
        }
        traded = normalize_traded_picks(
            "2026",
            "league",
            [{"season": "2027", "round": 1, "roster_id": 2, "owner_id": 8, "previous_owner_id": 2}],
            roster_map,
            2,
        )
        teams = pd.DataFrame(
            [
                {"roster_id": 2, "team_name": "Melkor Lord of Light"},
                {"roster_id": 8, "team_name": "The Clapper"},
            ]
        )

        ownership = build_pick_ownership(pd.DataFrame(traded), teams, 2)

        self.assertEqual(ownership.iloc[0]["current_owner"], "The Clapper")
        self.assertTrue(bool(ownership.iloc[0]["is_my_original_pick"]))
        self.assertFalse(bool(ownership.iloc[0]["is_currently_owned_by_me"]))

    def test_pick_ownership_can_scope_repeated_roster_ids_to_current_league(self) -> None:
        traded = pd.DataFrame(
            [
                {"league_id": "current", "season": "2026", "original_roster_id": 2, "original_team_name": "Current", "pick_season": "2027", "round": 1, "current_owner_roster_id": 2, "current_owner_team_name": "Current"},
                {"league_id": "historical", "season": "2025", "original_roster_id": 2, "original_team_name": "Historical", "pick_season": "2027", "round": 1, "current_owner_roster_id": 8, "current_owner_team_name": "Other"},
            ]
        )
        teams = pd.DataFrame([{"roster_id": 2, "team_name": "Current"}, {"roster_id": 8, "team_name": "Other"}])

        ownership = build_pick_ownership(traded, teams, 2, league_id="current", season="2026")

        self.assertEqual(len(ownership), 1)
        self.assertEqual(ownership.iloc[0]["original_team"], "Current")

    def test_league_history_discovery_walks_previous_league_chain(self) -> None:
        class FakeAPI:
            def __init__(self) -> None:
                self.leagues = {
                    "2026": {"previous_league_id": "league-2025"},
                    "2025": {"previous_league_id": "league-2024"},
                    "2024": {"previous_league_id": ""},
                }

            def league(self, season: str, league_id: str, force: bool = False) -> dict:
                return self.leagues[season]

        discovered = _discover_league_history(
            {
                "current_season": "2026",
                "leagues": {"2026": "league-2026", "2025": "", "2024": ""},
                "historical_ingestion": {"max_previous_seasons": 4},
            },
            FakeAPI(),
        )

        self.assertEqual(discovered["2026"], "league-2026")
        self.assertEqual(discovered["2025"], "league-2025")
        self.assertEqual(discovered["2024"], "league-2024")

    def test_manager_profiles_aggregate_history_by_owner_id(self) -> None:
        from src.manager_profiles import build_manager_profiles

        teams = pd.DataFrame(
            [
                {"season": "2025", "league_id": "old", "roster_id": 7, "owner_id": "owner-a", "display_name": "same", "team_name": "Old Name"},
                {"season": "2026", "league_id": "new", "roster_id": 2, "owner_id": "owner-a", "display_name": "same", "team_name": "New Name"},
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "season": "2025",
                    "team_a_roster_id": 7,
                    "team_a_name": "Old Name",
                    "team_a_players_received": "Young WR",
                    "team_a_picks_received": "2026 R1 original roster 2",
                    "team_a_faab_received": 0,
                    "team_b_roster_id": 8,
                    "team_b_name": "Other",
                    "team_b_players_received": "Veteran RB",
                    "team_b_picks_received": "",
                    "team_b_faab_received": 0,
                },
                {
                    "season": "2026",
                    "team_a_roster_id": 3,
                    "team_a_name": "Other",
                    "team_a_players_received": "Bench WR",
                    "team_a_picks_received": "",
                    "team_a_faab_received": 0,
                    "team_b_roster_id": 2,
                    "team_b_name": "New Name",
                    "team_b_players_received": "QB",
                    "team_b_picks_received": "",
                    "team_b_faab_received": 0,
                },
            ]
        )
        waivers = pd.DataFrame(
            [
                {"season": "2025", "roster_id": 7, "waiver_bid": 11},
                {"season": "2026", "roster_id": 2, "waiver_bid": 22},
            ]
        )
        roster_players = pd.DataFrame(
            [
                {"season": "2026", "roster_id": 2, "position": "QB"},
                {"season": "2026", "roster_id": 2, "position": "WR"},
            ]
        )

        profiles = build_manager_profiles(teams, trades, waivers, roster_players)

        self.assertEqual(len(profiles), 1)
        row = profiles.iloc[0]
        self.assertEqual(row["owner_id"], "owner-a")
        self.assertEqual(row["roster_id"], 2)
        self.assertEqual(row["total_trades"], 2)
        self.assertEqual(row["faab_spent_on_waivers"], 33)
        self.assertIn("2025", row["seasons_covered"])
        self.assertIn("2026", row["seasons_covered"])

    def test_manager_season_history_preserves_activity_grain_and_identity(self) -> None:
        """Encodes docs/data_contract.md and docs/front_office_research.md's historical-dossier rule."""
        from src.manager_profiles import build_manager_season_history

        teams = pd.DataFrame(
            [
                {"season": "2025", "roster_id": 7, "owner_id": "owner-a", "team_name": "Old Name"},
                {"season": "2026", "roster_id": 2, "owner_id": "owner-a", "team_name": "New Name"},
                {"season": "2025", "roster_id": 8, "owner_id": "owner-b", "team_name": "Other"},
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "season": "2025",
                    "week": 3,
                    "team_a_roster_id": 7,
                    "team_a_name": "Old Name",
                    "team_a_players_received": "Young WR",
                    "team_a_picks_received": "2026 R1 original roster 2",
                    "team_b_roster_id": 8,
                    "team_b_name": "Other",
                    "team_b_players_received": "Veteran RB",
                    "team_b_picks_received": "",
                }
            ]
        )
        waivers = pd.DataFrame(
            [{"season": "2025", "week": 12, "roster_id": 7, "team_name": "Old Name", "player_added": "Depth WR", "waiver_bid": 11}]
        )
        roster_players = pd.DataFrame(
            [
                {"season": "2025", "roster_id": 7, "position": "WR"},
                {"season": "2025", "roster_id": 7, "position": "RB"},
                {"season": "2026", "roster_id": 2, "position": "QB"},
            ]
        )
        matchups = pd.DataFrame(
            [
                {"season": "2025", "week": 1, "matchup_id": "1", "roster_id": 7, "team_name": "Old Name", "points_for": 120, "points_against": 100, "result": "win"},
                {"season": "2025", "week": 2, "matchup_id": "2", "roster_id": 7, "team_name": "Old Name", "points_for": 90, "points_against": 110, "result": "loss"},
            ]
        )

        history = build_manager_season_history(teams, trades, waivers, roster_players, matchups)
        old = history[(history["owner_id"] == "owner-a") & (history["season"].astype(str) == "2025")].iloc[0]
        quiet = history[(history["owner_id"] == "owner-a") & (history["season"].astype(str) == "2026")].iloc[0]

        self.assertEqual(old["roster_id"], 7)
        self.assertEqual(old["trades"], 1)
        self.assertEqual(old["waiver_claims"], 1)
        self.assertEqual(old["faab_spent"], 11)
        self.assertEqual(old["transaction_count"], 2)
        self.assertEqual(old["first_transaction_week"], 3)
        self.assertEqual(old["last_transaction_week"], 12)
        self.assertEqual(old["peak_transaction_week"], 3)
        self.assertEqual(old["active_weeks"], "3; 12")
        self.assertEqual(old["trade_weeks"], "3")
        self.assertEqual(old["waiver_weeks"], "12")
        self.assertEqual(old["roster_player_count"], 2)
        self.assertIn("Other:1", old["trade_partners"])
        self.assertIn("Young WR", old["players_acquired"])
        self.assertEqual(old["matchup_weeks"], "1; 2")
        self.assertEqual(old["played_weeks"], "1; 2")
        self.assertEqual(old["wins"], 1)
        self.assertEqual(old["losses"], 1)
        self.assertEqual(old["ties"], 0)
        self.assertEqual(old["points_for"], 210)
        self.assertEqual(old["points_against"], 210)
        self.assertEqual(old["point_diff"], 0)
        self.assertEqual(old["win_rate"], 0.5)
        self.assertEqual(old["outcome_status"], "recorded")
        self.assertIn("matchups", old["source_trace"])
        self.assertEqual(quiet["roster_id"], 2)
        self.assertEqual(quiet["transaction_count"], 0)
        self.assertEqual(quiet["outcome_status"], "not_recorded")
        self.assertEqual(quiet["wins"], 0)
        self.assertEqual(quiet["losses"], 0)
        self.assertIn("roster_id=2", quiet["evidence"])

    def test_player_transaction_history_preserves_ids_directions_and_resolution(self) -> None:
        """Encodes docs/data_contract.md's stable player identity and labeled fallback rule."""
        roster_players = pd.DataFrame(
            [
                {"player_id": "101", "player_name": "A.J. Brown"},
                {"player_id": "201", "player_name": "Twin Player"},
                {"player_id": "202", "player_name": "Twin Player"},
                {"player_id": "999", "player_name": "Counterparty Player"},
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "season": "2026",
                    "week": 4,
                    "created_datetime": "2026-06-10",
                    "team_a_roster_id": 1,
                    "team_a_name": "Alpha Team",
                    "team_a_players_received": "A.J. Brown",
                    "team_a_player_ids_received": "101",
                    "team_b_roster_id": 2,
                    "team_b_name": "Beta Team",
                    "team_b_players_received": "Counterparty Player",
                    "team_b_player_ids_received": "999",
                },
                {
                    "season": "2025",
                    "week": 8,
                    "created_datetime": "2025-07-10",
                    "team_a_roster_id": 1,
                    "team_a_name": "Alpha Team",
                    "team_a_players_received": "A.J. Brown; Twin Player; Unknown Player",
                    "team_b_roster_id": 2,
                    "team_b_name": "Beta Team",
                    "team_b_players_received": "Counterparty Player",
                },
            ]
        )
        waivers = pd.DataFrame(
            [
                {
                    "season": "2026",
                    "week": 5,
                    "roster_id": 1,
                    "team_name": "Alpha Team",
                    "player_added": "A.J. Brown",
                    "player_added_ids": "101",
                    "player_dropped": "Unknown Player",
                    "player_dropped_ids": "",
                }
            ]
        )

        history = build_player_transaction_history(trades, waivers, pd.DataFrame(), roster_players)
        alpha_acquired = history[(history["roster_id"].astype(str) == "1") & (history["player_id"] == "101") & (history["direction"] == "acquired")]
        beta_sold = history[(history["roster_id"].astype(str) == "2") & (history["player_id"] == "101") & (history["direction"] == "sold")]

        self.assertGreaterEqual(len(alpha_acquired), 2)
        self.assertGreaterEqual(len(beta_sold), 1)
        self.assertTrue((alpha_acquired["identity_method"] == "source_id").any())
        self.assertTrue(((history["player_name"] == "A.J. Brown") & (history["identity_method"] == "normalized_name")).any())
        self.assertTrue(((history["player_name"] == "Twin Player") & (history["identity_method"] == "ambiguous_name")).any())
        self.assertTrue(((history["player_name"] == "Unknown Player") & (history["identity_method"] == "unmatched_name")).any())
        self.assertTrue(((history["event_type"] == "waiver_add") & (history["player_id"] == "101") & (history["identity_method"] == "source_id")).any())

    def test_profile_intelligence_builds_manager_cycle_and_player_tags(self) -> None:
        manager_profiles = pd.DataFrame(
            [
                {
                    "owner_id": "owner-a",
                    "roster_id": 2,
                    "team_name": "Rebuild Crew",
                    "seasons_covered": "2024; 2025; 2026",
                    "total_trades": 18,
                    "future_1sts_acquired": 8,
                    "future_1sts_sold": 1,
                    "future_2nds_acquired": 4,
                    "future_2nds_sold": 1,
                    "faab_spent_on_waivers": 45,
                    "number_of_waiver_claims": 24,
                    "rb_count": 4,
                    "pass_catcher_count": 11,
                },
                {
                    "owner_id": "owner-b",
                    "roster_id": 8,
                    "team_name": "Go For It",
                    "seasons_covered": "2024; 2025; 2026",
                    "total_trades": 60,
                    "future_1sts_acquired": 1,
                    "future_1sts_sold": 8,
                    "future_2nds_acquired": 1,
                    "future_2nds_sold": 5,
                    "faab_spent_on_waivers": 360,
                    "number_of_waiver_claims": 90,
                    "rb_count": 9,
                    "pass_catcher_count": 16,
                },
            ]
        )
        roster = pd.DataFrame(
            [
                {"season": "2026", "roster_id": 2, "player_id": "1", "player_name": "Young WR", "position": "WR", "age": 23, "team_name": "Rebuild Crew", "roster_status": "starter"},
                {"season": "2026", "roster_id": 8, "player_id": "2", "player_name": "Old RB", "position": "RB", "age": 29, "team_name": "Go For It", "roster_status": "starter"},
            ]
        )
        tables = build_profile_intelligence_tables(
            manager_profiles,
            pd.DataFrame(columns=["event_type"]),
            pd.DataFrame(columns=["roster_id", "position_group", "preference_score"]),
            pd.DataFrame(
                [
                    {"roster_id": 2, "team_name": "Rebuild Crew", "team_shape": "rebuild_asset_bank", "future_firsts_owned": 5, "need_qb": "low", "need_rb": "high", "need_pass_catcher": "medium", "need_picks": "low"},
                    {"roster_id": 8, "team_name": "Go For It", "team_shape": "contender_shape", "future_firsts_owned": 1, "need_qb": "low", "need_rb": "low", "need_pass_catcher": "low", "need_picks": "high"},
                ]
            ),
            pd.DataFrame(
                [
                    {"current_owner_roster_id": 2, "round": 1},
                    {"current_owner_roster_id": 2, "round": 1},
                    {"current_owner_roster_id": 2, "round": 1},
                    {"current_owner_roster_id": 2, "round": 1},
                    {"current_owner_roster_id": 2, "round": 1},
                ]
            ),
            roster,
            pd.DataFrame(
                [
                    {"season": "2026", "week": 1, "created_datetime": "2026-06-01", "team_a_roster_id": 2, "team_a_name": "Rebuild Crew", "team_a_players_received": "Young WR", "team_b_roster_id": 8, "team_b_name": "Go For It", "team_b_players_received": "Old RB"}
                ]
            ),
            pd.DataFrame([{"season": "2026", "week": 1, "roster_id": 2, "team_name": "Rebuild Crew", "player_added": "Young WR", "player_dropped": "", "waiver_bid": 5}]),
            pd.DataFrame([{"season": "2026", "pick_no": 1, "round": 1, "roster_id": 2, "player_id": "1", "player_name": "Young WR"}]),
            pd.DataFrame([{"player_id": "1", "player_name": "Young WR", "consensus_value": 30, "source_trace": "market"}]),
            pd.DataFrame([{"player_id": "1", "player_name": "Young WR", "projected_fantasy_points": 170, "projected_ppg": 10, "projection_confidence": "high", "source_trace": "projection"}]),
            pd.DataFrame(columns=["player_id"]),
            pd.DataFrame([{"player_id": "1", "impact_type": "role_or_value_change", "source_trace": "news"}]),
            pd.DataFrame([{"player_id": "1", "player_name": "Young WR", "market_value": 30, "projection_edge_score": 70, "breakout_score": 72, "sell_score": 0, "signal_label": "breakout_target", "confidence": "high", "source_trace": "signal"}]),
        )

        cycles = tables["manager_cycle_profiles"]
        manager_tags = tables["manager_profile_tags"]
        player_tags = tables["player_profile_tags"]

        self.assertIn("rebuild", set(cycles["dynasty_cycle"]))
        self.assertIn("pick accumulator", set(manager_tags["tag"]))
        self.assertTrue((manager_tags["score"].astype(float) < 100).any())
        self.assertIn("breakout candidate", set(player_tags["tag"]))
        self.assertIn("source_trace", tables["player_dossiers"].columns)
        self.assertGreater(len(tables["player_transaction_history"]), 0)

    def test_browser_context_roster_id_overrides_stale_my_team_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            site = Path(tmp) / "site"
            processed.mkdir()
            self._write_minimal_processed_tables(processed)
            pd.DataFrame(
                [
                    {"roster_id": 2, "display_name": "joe3489", "team_name": "Lulu’s Potatoe’s"},
                    {"roster_id": 4, "display_name": "Crumplesacks", "team_name": "Moose Caboose"},
                ]
            ).to_csv(processed / "teams.csv", index=False)
            pd.DataFrame(
                [
                    {"roster_id": 2, "player_name": "Lulu Player", "position": "QB", "is_my_team": False},
                    {"roster_id": 4, "player_name": "Stale Player", "position": "QB", "is_my_team": True},
                ]
            ).to_csv(processed / "roster_players.csv", index=False)

            build_browser_site(
                site,
                processed,
                config={
                    "context": {
                        "user_id": "17",
                        "league_id": "league",
                        "season": "2026",
                        "roster_id": 2,
                        "identity_status": "verified_roster_match",
                    }
                },
            )
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))

        self.assertEqual(bundle["myRosterId"], 2)
        self.assertEqual(bundle["myTeamName"], "Lulu’s Potatoe’s")
        self.assertEqual(bundle["identityReceipt"]["roster_id"], 2)

    def test_browser_available_market_route_has_identity_and_boundary_contract(self) -> None:
        """Design source: AGENTS.md identity boundary and available-market research contract.

        The front page and horizon board link by Sleeper player ID. This entry-path
        contract keeps that link connected to the available evidence row even when
        no roster dossier exists, while requiring the page to disclose that roster
        absence is not a waiver-eligibility receipt.
        """
        from src.browser_site import build_browser_site

        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            site = Path(tmp) / "site"
            processed.mkdir()
            self._write_minimal_processed_tables(processed)
            pd.DataFrame(
                [{"player_id": "available-1", "full_name": "Available Clock WR", "position": "WR", "team": "FA"}]
            ).to_csv(processed / "players.csv", mode="a", header=False, index=False)
            pd.DataFrame(
                [{
                    "league_id": "league",
                    "season": "2026",
                    "player_id": "available-1",
                    "player_name": "Available Clock WR",
                    "position": "WR",
                    "identity_status": "sleeper_id",
                    "availability_status": "not_rostered_in_selected_league",
                    "market_value": "24",
                    "market_percentile": "72",
                    "next_game_market_score": "72",
                    "rest_of_season_market_score": "84",
                    "dynasty_market_score": "61",
                    "career_projection_score": "70",
                    "fit_coverage": "4/4",
                    "availability_note": "No current Sleeper injury flag",
                    "source_trace": "available_player_horizon_scores",
                }]
            ).to_csv(processed / "available_player_horizon_scores.csv", index=False)

            output = build_browser_site(site, processed, league_id="league")
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))
            html = output.read_text(encoding="utf-8")

        self.assertEqual(bundle["tables"]["available_player_horizon_scores"][0]["player_id"], "available-1")
        self.assertIn("const availableHorizon = scopedCurrentRows(tables.available_player_horizon_scores || [])", html)
        self.assertIn("const isAvailableMarket = Boolean(availableHorizon.player_id)", html)
        self.assertIn("available-player-boundary", html)
        self.assertIn("waiver or free-agent eligibility is not verified here", html)
        self.assertIn("available-market cross-position anchor", html)
        self.assertIn('data-testid="horizon-score-meter"', html)
        self.assertIn("horizonScoreMeter", html)

    def test_browser_data_room_exposes_player_history_identity_receipt(self) -> None:
        """The Data Room must expose semantic history coverage, not freshness alone."""
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            site = Path(tmp) / "site"
            processed.mkdir()
            self._write_minimal_processed_tables(processed)
            pd.DataFrame(
                [
                    {"player_id": "1", "identity_method": "source_id", "player_name": "Jayden Daniels", "event_type": "trade", "season": 2026, "week": 3, "created_datetime": "2026-06-20", "roster_id": 2, "team_name": "Melkor Lord of Light", "counterparty": "Other Team", "direction": "acquired", "evidence": "trade evidence", "source_trace": "trades"},
                    {"player_id": "1", "identity_method": "source_id", "player_name": "Jayden Daniels", "event_type": "trade", "season": 2026, "week": 3, "created_datetime": "2026-06-20", "roster_id": 8, "team_name": "Other Team", "counterparty": "Melkor Lord of Light", "direction": "sold", "evidence": "trade evidence", "source_trace": "trades"},
                    {"player_id": "", "identity_method": "unmatched_name", "player_name": "Legacy Player", "event_type": "waiver_add", "season": 2025, "week": 4, "created_datetime": "2025-06-10", "roster_id": 2, "team_name": "Melkor Lord of Light", "counterparty": "", "direction": "added", "evidence": "waiver evidence", "source_trace": "waivers"},
                ]
            ).to_csv(processed / "player_transaction_history.csv", index=False)

            output = build_browser_site(site, processed)
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))
            manifest = json.loads((site / "data" / "manifest.json").read_text(encoding="utf-8"))
            html = output.read_text(encoding="utf-8")

        receipt = bundle["dataQuality"]["player_history_identity"]
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["row_count"], 3)
        self.assertEqual(receipt["resolved_rows"], 2)
        self.assertEqual(receipt["unresolved_rows"], 1)
        self.assertEqual(receipt["trade_direction_status"], "balanced")
        self.assertEqual(manifest["dataQuality"], bundle["dataQuality"])
        self.assertIn("Historical identity receipt", html)
        self.assertIn("renderDataQualityReceipt", html)
        self.assertIn("Some rows still rely on ambiguous or unmatched names", html)

    def test_browser_data_room_history_receipt_fails_closed_on_contract_error(self) -> None:
        """Malformed history must be visible as a contract issue, not a healthy join."""
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            site = Path(tmp) / "site"
            processed.mkdir()
            self._write_minimal_processed_tables(processed)
            pd.DataFrame(
                [{"player_id": "", "identity_method": "source_id", "player_name": "Broken Player", "event_type": "trade", "season": 2026, "week": 2, "created_datetime": "2026-06-12", "roster_id": 2, "team_name": "Melkor Lord of Light", "counterparty": "Other Team", "direction": "received", "evidence": "bad fixture", "source_trace": "trades"}]
            ).to_csv(processed / "player_transaction_history.csv", index=False)

            build_browser_site(site, processed)
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))

        receipt = bundle["dataQuality"]["player_history_identity"]
        self.assertEqual(receipt["status"], "contract_error")
        self.assertFalse(receipt["valid"])
        self.assertTrue(receipt["errors"])

    def test_data_room_delta_requires_prior_scope_and_reports_added_events(self) -> None:
        """Encodes docs/front_office_realization_epic.md's return-later delta rule."""
        previous = {
            "bundleRevision": "prior-revision",
            "tables": {
                "league_news_impact": [
                    {"event_id": "news-old", "player_name": "Old Player", "published_at": "2026-08-24", "evidence": "old signal"}
                ],
                "trades": [],
                "waivers": [
                    {"transaction_id": "waiver-same", "created_datetime": "2026-08-23", "team_name": "Other Team", "player_added": "Old Add"}
                ],
            },
        }
        current = {
            "league_news_impact": [
                {"event_id": "news-old", "player_name": "Old Player", "published_at": "2026-08-24", "evidence": "old signal"},
                {"event_id": "news-new", "player_name": "New Player", "published_at": "2026-08-25", "evidence": "new signal"},
            ],
            "trades": [
                {"transaction_id": "trade-new", "created_datetime": "2026-08-25T12:00:00Z", "team_a_name": "A", "team_b_name": "B", "team_a_players_received": "New Player"}
            ],
            "waivers": [
                {"transaction_id": "waiver-same", "created_datetime": "2026-08-23", "team_name": "Other Team", "player_added": "Old Add"}
            ],
        }

        receipt = _data_room_delta(previous, current, "2026-08-25T13:00:00Z")

        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(receipt["from_bundle_revision"], "prior-revision")
        self.assertEqual(receipt["categories"]["news"]["added_rows"], 1)
        self.assertEqual(receipt["categories"]["trades"]["added_rows"], 1)
        self.assertEqual(receipt["categories"]["waivers"]["added_rows"], 0)
        self.assertEqual([row["event_id"] for row in receipt["added_events"]], ["trade-new", "news-new"])
        self.assertEqual(_data_room_delta({}, current, "now")["status"], "not_available")

        incomplete = {"tables": {"league_news_impact": [], "trades": []}}
        unavailable = _data_room_delta(incomplete, current, "now")
        self.assertEqual(unavailable["status"], "not_available")
        self.assertIn("waivers", unavailable["reason"])

        missing_key = {"tables": {**previous["tables"], "trades": [{"created_datetime": "2026-08-25"}]}}
        unavailable = _data_room_delta(missing_key, current, "now")
        self.assertEqual(unavailable["status"], "not_available")
        self.assertIn("transaction_id", unavailable["reason"])

    def test_browser_surface_contains_workflow_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            site = Path(tmp) / "site"
            processed.mkdir()
            self._write_minimal_processed_tables(processed)

            output = build_browser_site(site, processed)
            html = output.read_text(encoding="utf-8")
            manifest = json.loads((site / "data" / "manifest.json").read_text(encoding="utf-8"))
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))
            editorial = json.loads((site / "data" / "editorial_issue.json").read_text(encoding="utf-8"))
            media_manifest = json.loads((site / "data" / "media_manifest.json").read_text(encoding="utf-8"))
            players_audit_exists = (site / "data" / "audit" / "players.json").exists()
            draft_room_exists = (site / "data" / "draft_room.json").exists()

        self.assertIn("The Front Office", html)
        self.assertIn("front-office-manifest", html)
        self.assertIn("Standings &amp; outcome coverage", html)
        self.assertIn("issue-publication-nav", html)
        self.assertIn("publication-${escapeHtml", html)
        self.assertNotIn('id="app-data"', html)
        self.assertIn("Data Room", html)
        self.assertIn("Team Overview", html)
        self.assertIn("Today's Board", html)
        self.assertIn("brief-card", html)
        self.assertIn("brief-list", html)
        self.assertIn("today-priority-board", html)
        self.assertIn("function priorityCards", html)
        self.assertNotIn("Buy-Low Targets", html)
        # Today's Board collapsed into one deduplicated ranked list (Sprint 14) --
        # these sub-headings and their per-type render functions no longer exist.
        self.assertNotIn("today-action-board", html)
        self.assertNotIn("today-sell-window", html)
        self.assertNotIn("function actionCards", html)
        self.assertNotIn("function opportunityCards", html)
        self.assertIn("Roster Value Board", html)
        self.assertIn("Strategy alignment", html)
        self.assertIn("function strategyRosterRows", html)
        self.assertIn("team_needs_matrix", html)
        self.assertIn("strategy_fit", html)
        self.assertNotIn("Value tags are planned as a strategy overlay", html)
        self.assertIn("Projection Board", html)
        self.assertIn("Signal Board", html)
        self.assertIn("Four-Window Market Board", html)
        self.assertIn("horizon_market_movements", html)
        self.assertIn("Market clock changes", html)
        self.assertIn("changed market-clock rows", html)
        self.assertIn("Horizon movement rows", html)
        self.assertIn('id="horizon-market-board"', html)
        self.assertIn('data-horizon-scope="team"', html)
        self.assertIn('data-horizon-scope="league"', html)
        self.assertIn('id="horizon-lane-filter"', html)
        self.assertIn('id="horizon-sort-filter"', html)
        self.assertIn('id="horizon-view-note"', html)
        self.assertIn('data-horizon-view="this_week"', html)
        self.assertIn('data-horizon-view="rest_of_season"', html)
        self.assertIn('data-horizon-view="dynasty"', html)
        self.assertIn('data-horizon-view="fit"', html)
        self.assertIn('data-horizon-view="repricing"', html)
        self.assertIn("horizonTeamLens", html)
        self.assertIn("horizonTeamFit", html)
        self.assertIn("function filteredHorizonRows", html)
        self.assertIn("function horizonMarketCard", html)
        self.assertIn("function horizonMarketViewMarkup", html)
        self.assertIn("function horizonViewDefinition", html)
        self.assertIn("function renderHorizonMarketBoard", html)
        self.assertIn("renderHorizonMarketBoard();", html)
        self.assertIn("horizon-market-clock-grid", html)
        self.assertIn("horizonScoreMeter", html)
        self.assertIn("horizonCardMeter", html)
        self.assertIn("Next game", html)
        self.assertIn("Rest of season", html)
        self.assertIn("Career window", html)
        self.assertIn("position-relative percentile / 100", html)
        self.assertIn("not yet outcome-calibrated forecasts", html)
        self.assertIn("horizon-market-delta-grid", html)
        self.assertIn("horizon-market-reprice-grid", html)
        self.assertIn("horizonMarketDisagreement", html)
        self.assertIn("market_disagreement", html)
        self.assertIn("Career minus dynasty", html)
        self.assertIn("Horizon evidence receipt", html)
        self.assertIn("Projection percentile (position)", html)
        self.assertIn("Market percentile (position)", html)
        self.assertIn("Market price anchor", html)
        self.assertIn("This-week percentile", html)
        self.assertNotIn("Projection rank", html)
        self.assertNotIn("Market rank", html)
        self.assertIn("Analyst Brief", html)
        self.assertIn("Target Theses", html)
        self.assertIn("Sell Theses", html)
        self.assertIn("Trade Theses", html)
        self.assertIn("Recommendation outcome", html)
        self.assertIn("Manager-fit outcome", html)
        self.assertIn("manager-fit:", html)
        self.assertIn("decisionType: 'manager_fit'", html)
        self.assertIn("fit_alignment", html)
        self.assertIn("No direct historical lane in the observed profile", html)
        self.assertIn("decision_outcome", html)
        self.assertIn("Recommendation learning", html)
        self.assertIn("offer_candidates", html)
        self.assertIn("Potential assets from our roster to discuss (not a generated offer)", html)
        self.assertIn("Who Might Value Our Assets?", html)
        self.assertIn("counterparty-asset-interest", html)
        self.assertIn("conversation_fit_score", html)
        self.assertIn("manager-counterparty-interest", html)
        self.assertIn("assets_target_may_value", html)
        self.assertIn("Trade decision packet", html)
        self.assertIn("Do-not-chase conditions", html)
        self.assertIn("Alternative counterparties", html)
        self.assertIn("Risk of waiting", html)
        self.assertIn("Evidence and source trace", html)
        self.assertIn("Open the two-sided decision packet", html)
        self.assertIn("Trade-fit status", html)
        self.assertIn("Waiver Claims", html)
        self.assertIn("Observed Events", html)
        self.assertIn("Active Seasons", html)
        self.assertIn("No fit card is shown because the current evidence does not support one", html)
        self.assertIn("Manager Dossiers", html)
        self.assertIn("Manager trajectory", html)
        self.assertIn("manager-trajectory-snapshot", html)
        self.assertIn("manager-trajectory-dossier", html)
        self.assertIn("Observed Transaction Lanes", html)
        self.assertIn("manager-transaction-preferences-table", html)
        self.assertIn("manager-transaction-profile", html)
        self.assertIn("current context for historically moved players", html)
        self.assertIn("Observed transaction timeline", html)
        self.assertIn("Event-level evidence", html)
        self.assertIn("Team construction", html)
        self.assertIn("Position mix", html)
        self.assertIn("Market coverage", html)
        self.assertIn("market_proxy_rows", html)
        self.assertIn("team_asset_inventory", html)
        self.assertIn("internal_proxy_player_value", html)
        self.assertIn("Need lanes", html)
        self.assertIn("Construction evidence", html)
        self.assertIn("function managerTransactionTimelineMarkup", html)
        self.assertIn("transaction_timeline", html)
        self.assertIn("Breakout Candidates", html)
        self.assertIn("Sell Candidates", html)
        self.assertIn("Projection Market Gaps", html)
        self.assertIn("Manager Behavior", html)
        self.assertIn("Market Gaps", html)
        self.assertIn("Counterparty Edges", html)
        self.assertIn("target_team_lens", html)
        self.assertIn("horizon_fit_edge", html)
        self.assertIn("horizon_market_disagreement_window", html)
        self.assertIn("Market vs clock", html)
        self.assertIn("clock-market", html)
        self.assertIn("Timeline fit", html)
        self.assertIn("timeline fit unavailable", html)
        self.assertIn("We May Value More Than Owner", html)
        self.assertIn("Owner May Overvalue", html)
        self.assertIn("Market Lens Lab", html)
        self.assertIn("Scenario Targets", html)
        self.assertIn("Scenario Sells", html)
        self.assertIn("Biggest Movers", html)
        self.assertIn("Balanced Market", html)
        self.assertIn("Projection Contrarian", html)
        self.assertIn("Counterparty Exploit", html)
        self.assertIn("Manager Map", html)
        self.assertIn("Manager Valuation Profiles", html)
        self.assertIn("Asset Ledger", html)
        self.assertIn("Opportunity Board", html)
        self.assertIn("News Desk", html)
        self.assertIn("Manager Room", html)
        # Sprint 20 task-based IA: seven task views + two entity pages, hash-routed.
        self.assertIn('id="view-today"', html)
        self.assertIn('id="view-my-team"', html)
        self.assertIn('id="view-players"', html)
        self.assertIn('id="view-league"', html)
        self.assertIn('id="view-trade-desk"', html)
        self.assertIn('id="view-news"', html)
        self.assertIn('id="view-data-room"', html)
        self.assertIn('id="player-page"', html)
        self.assertIn('id="team-page"', html)
        self.assertIn("function renderPlayerPage", html)
        self.assertIn("function playerHorizonMarkup", html)
        self.assertIn("Availability source", html)
        self.assertIn("historical availability unavailable", html)
        self.assertIn("Market clocks &amp; career window", html)
        self.assertIn("Four-window fit", html)
        self.assertIn("Four-window weighting receipt", html)
        self.assertIn("career window ${horizon.career_projection_score || 'n/a'}", html)
        self.assertIn('data-testid="player-horizons"', html)
        self.assertIn("opponent-neutral until a schedule/bye source is available", html)
        self.assertIn("rest-of-season baseline is not recovery-adjusted", html)
        self.assertIn("function horizonRestSeasonPpgLabel", html)
        self.assertIn("function horizonHasCurrentAvailabilityFlag", html)
        self.assertIn("function projectionPointsText", html)
        self.assertIn("['none', 'healthy', 'active', 'available', 'no current injury', 'no current sleeper injury flag']", html)
        self.assertIn("['questionable', 'doubtful', 'out', 'injured', 'injury', 'ir', 'pup'", html)
        self.assertIn("conditional baseline PPG if active", html)
        self.assertIn("Baseline PPG (availability-aware)", html)
        self.assertIn("position-relative percentiles from 0–100, not dollar market values", html)
        self.assertIn("horizon_score_basis", html)
        self.assertIn("next_game_matchup_adjustment_status", html)
        self.assertIn("factor descriptive only", html)
        self.assertIn("cross-position price anchor", html)
        self.assertIn("market value unavailable", html)
        self.assertIn("scheduled game count unavailable", html)
        self.assertIn("function horizonRestSeasonCountLabel", html)
        self.assertIn("season projection unavailable", html)
        self.assertIn("career_projection_score", html)
        self.assertIn("Career window", html)
        self.assertIn("fit coverage", html)
        self.assertIn("ROS minus next", html)
        self.assertIn("dynasty minus ROS", html)
        self.assertIn("career minus dynasty", html)
        self.assertIn("internal age-curve scenario", html)
        self.assertIn("not a lifetime forecast", html)
        self.assertIn("career_history_status", html)
        self.assertIn("career_history_source_player_id", html)
        self.assertIn("source player id", html)
        self.assertIn("history anchor", html)
        self.assertIn("horizon_model_version", html)
        self.assertIn("fit_basis", html)
        self.assertIn("player_horizon_market_scores", bundle["tables"])
        self.assertIn("function renderTeamPage", html)
        self.assertIn("const inventoryAsset", html)
        self.assertIn("Market source", html)
        self.assertIn("asset ledger value unavailable", html)
        self.assertIn("Player dossier", html)
        self.assertIn("Evidence chain", html)
        self.assertIn("function scopedCurrentLeagueNews", html)
        self.assertIn("function scopedCurrentRows", html)
        self.assertIn("function currentRosterPlayerIds()", html)
        self.assertIn("currentRosterPlayerIds().has(String(row.player_id))", html)
        self.assertNotIn("currentRosterPlayerNames().has(String(row.player_name))", html)
        self.assertNotIn("String(row.current_team_name) === activeTeamName()", html)
        self.assertIn("scopedCurrentRows(tables.player_opportunity_scores || [])", html)
        self.assertIn("title: 'Which signals disagree for my team?'", html)
        self.assertIn("const horizonRows = scopedCurrentRows(tables.player_horizon_market_scores || [])", html)
        self.assertIn("sameIdentifier(row.league_id, leagueId)", html)
        self.assertIn("scopedCurrentLeagueNews().filter(row => String(row.player_id", html)
        self.assertIn("scopedCurrentRows(tables.manager_event_log || []).filter(row => Number(row.roster_id) === state.teamId)", html)
        self.assertIn(".side-rail .section-nav { display: flex;", html)
        self.assertIn("function publicationListItemMarkup", html)
        self.assertIn("news-market-edge-table", html)
        self.assertIn("function filteredNewsMarketEdges", html)
        self.assertIn("Show full source traces", html)
        self.assertIn("Opponent roster", html)
        self.assertIn("It does not imply a trade, waiver claim, or future outcome", html)
        self.assertIn("entity-search", html)
        self.assertIn("Manager Cycle Profiles", html)
        self.assertIn("Player Dossiers", html)
        self.assertIn("Coverage by clock", html)
        self.assertIn("horizon_coverage_detail", html)
        self.assertIn("League Impact", html)
        self.assertIn("Watchlist / Waiver", html)
        self.assertIn("Unmatched Feed Items", html)
        self.assertIn("Player News Matches", html)
        self.assertIn("Data Diagnostics", html)
        self.assertIn("Latest recorded league events", html)
        self.assertIn("historical delta unless a prior receipt says so", html)
        self.assertIn("dataRoomDelta", html)
        self.assertIn("Since the prior reader bundle", html)
        self.assertIn("Change receipt", html)
        self.assertIn("waiver-scope", html)
        self.assertIn("Source Freshness", html)
        self.assertIn("Player market rows", html)
        self.assertIn("Market source rows", html)
        self.assertIn("Market consensus rows", html)
        self.assertIn("Counterparty edge rows", html)
        self.assertIn("Manager profile tag rows", html)
        self.assertIn("Player dossier rows", html)
        self.assertIn("Player profile tag rows", html)
        self.assertIn("Draft Room", html)
        self.assertIn("Draft feed", html)
        self.assertIn('id="view-draft-room"', html)
        self.assertIn("function renderDraftRoom", html)
        self.assertIn("Usage rows", html)
        self.assertIn("Economic asset rows", html)
        self.assertIn("News event rows", html)
        self.assertIn("News impact rows", html)
        self.assertIn("News Source Freshness", html)
        self.assertIn("Projection season rows", html)
        self.assertIn("Projection Source Freshness", html)
        self.assertIn("Signal score rows", html)
        self.assertIn("Action recommendation rows", html)
        self.assertIn("Breakout candidate rows", html)
        self.assertIn("Analysis artifacts", html)
        self.assertIn("Target thesis rows", html)
        self.assertIn("Recommendation packets", html)
        self.assertIn("Operator Mode", html)
        self.assertIn("FRONT_OFFICE_OPERATOR_TOKEN", html)
        self.assertIn("api/operator/status?league_id=", html)
        self.assertIn("function overlayOperatorStatus", html)
        self.assertIn("Keep the live writer/readiness receipt visible", html)
        self.assertNotIn("Packet path", html)
        self.assertNotIn("Validated path", html)
        self.assertIn("Writer receipt detail", html)
        self.assertIn("Preview Writer Plan (no call)", html)
        self.assertIn("api/operator/generation-plan?league_id=", html)
        self.assertIn("function previewWriterPlan", html)
        self.assertIn("function writerPlanPanel", html)
        self.assertIn('data-testid="writer-generation-plan"', html)
        self.assertIn("No provider request was made", html)
        self.assertIn("No per-article writer receipts were returned", html)
        self.assertIn("Only articles marked complete or unchanged", html)
        self.assertIn("Legacy operator record; per-article writer receipts were not retained", html)
        self.assertIn("Build Insight Packet", html)
        self.assertIn("Import Insight JSON", html)
        self.assertIn("evidence-drawer", html)
        self.assertIn("topTags('manager'", html)
        self.assertIn("insightFor('player'", html)
        # Sprint 15 visual system: color-by-category, rank/headshot media, and
        # delta/score table cells all route through these shared helpers -- guard
        # against an accidental deletion the way the other function-name checks do.
        self.assertIn("function categoryFor", html)
        self.assertIn("function playerHeadshotUrl", html)
        self.assertIn("function renderCell", html)
        self.assertIn("cat-${bucket}", html)
        self.assertEqual(manifest["appName"], "The Front Office")
        self.assertEqual(manifest["editorialPath"], "data/editorial_issue.json")
        self.assertEqual(manifest["draftRoomPath"], "data/draft_room.json")
        self.assertEqual(manifest["mediaPath"], "data/media_manifest.json")
        self.assertEqual(media_manifest["schema_version"], "media_manifest_v1")
        self.assertEqual(editorial["schema_version"], "issue_v1")
        self.assertEqual(manifest["payloadPolicy"], "initial_shell_plus_fact_bundle; audit_only_tables_lazy_loaded")
        self.assertIn("players", manifest["auditTables"])
        self.assertIn("player_usage_weekly", manifest["auditTables"])
        self.assertIn("player_projection_weekly", manifest["auditTables"])
        self.assertNotIn("players", bundle["tables"])
        self.assertNotIn("player_usage_weekly", bundle["tables"])
        self.assertNotIn("player_projection_weekly", bundle["tables"])
        self.assertNotIn("scenario_rankings", bundle["tables"])
        self.assertFalse((processed / "scenario_rankings.csv").exists())
        self.assertTrue(players_audit_exists)
        # Regression guard: today_priority_board.csv existing on disk is not enough --
        # build_browser_site() bundles tables from an explicit dict, so a table the JS
        # references must actually be added there or tables.today_priority_board is
        # undefined client-side (this crashed render() until caught by manual browser
        # verification, since HTML-string assertions alone don't execute the JS).
        self.assertIn("today_priority_board", bundle["tables"])
        self.assertIn("drafts", bundle["tables"])
        self.assertEqual(bundle["draftRoom"]["schema_version"], "draft_room_v1")
        self.assertTrue(draft_room_exists)

    def test_draft_room_is_league_scoped_and_evidence_backed(self) -> None:
        room = build_draft_room(
            {
                "teams": [{"season": "2026", "roster_id": 2, "team_name": "Rebuild Crew"}],
                "roster_players": [{"season": "2026", "roster_id": 2, "player_id": "1", "player_name": "Core QB"}],
                "players": [
                    {"player_id": "sleeper-rb", "full_name": "Available RB", "position": "RB"},
                    {"player_id": "sleeper-james", "full_name": "James Cook", "position": "RB"},
                ],
                "team_needs_matrix": [{"roster_id": 2, "team_shape": "rebuild_asset_bank", "need_qb": "low", "need_rb": "high", "need_pass_catcher": "low", "need_picks": "low"}],
                "player_market_values": [
                    {"player_id": "1", "player_name": "Core QB", "position": "QB", "market_value": 80, "market_rank": 1, "source_trace": "market"},
                    {"player_id": "", "player_name": "Available RB", "position": "RB", "market_value": 70, "market_rank": 5, "source_trace": "market"},
                    {"player_id": "", "player_name": "Unknown RB", "position": "RB", "market_value": 65, "market_rank": 6, "source_trace": "market"},
                    {"player_id": "", "player_name": "James Cook III", "position": "RB", "market_value": 60, "market_rank": 7, "source_trace": "market"},
                ],
                "action_recommendations": [
                    {"roster_id": 8, "team_name": "Contender", "player_id": "2", "player_name": "Trade Target", "position": "WR", "action_label": "true_buy_low", "action_score": 90, "why": "Buy low", "evidence": "gap", "confidence": "high", "source_trace": "market"},
                    {"roster_id": 2, "team_name": "Rebuild Crew", "player_id": "3", "player_name": "Roster Fade", "position": "RB", "action_label": "sell_window", "action_score": 60, "why": "Sell", "evidence": "age", "confidence": "high", "source_trace": "market"},
                ],
                "pick_ownership": [
                    {"pick_season": "2027", "round": 1, "original_roster_id": 2, "original_team": "Rebuild Crew", "current_owner_roster_id": 2, "current_owner": "Rebuild Crew"},
                    {"pick_season": "2027", "round": 2, "original_roster_id": 2, "original_team": "Rebuild Crew", "current_owner_roster_id": 8, "current_owner": "Contender"},
                ],
                "pick_market_values": [{"pick_season": "2027", "round": 1, "market_value": "", "ranking_value": 33, "value_status": "rank_only"}],
                "source_freshness": [{"source": "dynastyprocess", "dataset": "pick_values", "status": "refreshed"}],
                "drafts": [{
                    "season": "2026",
                    "draft_id": "draft-2026",
                    "status": "complete",
                    "type": "linear",
                    "settings": json.dumps({"rounds": 4, "teams": 12, "pick_timer": 28800}),
                }],
            },
            {"current_season": "2026", "strategy_profile": {"name": "Rebuild"}, "tracked_picks": [{"pick_season": "2027", "round": 1, "priority": "major_reacquisition_target"}]},
            league_id="league-1",
            my_roster_id=2,
            my_team_name="Rebuild Crew",
        )

        self.assertEqual(room["schema_version"], "draft_room_v1")
        self.assertEqual(room["league_id"], "league-1")
        self.assertEqual(room["draft_board"][0]["player_name"], "Available RB")
        self.assertEqual(room["draft_board"][0]["player_id"], "sleeper-rb")
        self.assertEqual(room["draft_board"][0]["identity_status"], "sleeper_unique_name_match")
        unresolved = next(row for row in room["draft_board"] if row["player_name"] == "Unknown RB")
        self.assertEqual(unresolved["player_id"], "")
        self.assertEqual(unresolved["identity_status"], "unconfirmed_name_match")
        suffix_match = next(row for row in room["draft_board"] if row["player_name"] == "James Cook III")
        self.assertEqual(suffix_match["player_id"], "sleeper-james")
        self.assertEqual(suffix_match["identity_status"], "sleeper_unique_name_match")
        self.assertEqual(room["summary"]["unconfirmed_player_count"], 1)
        self.assertEqual(room["trade_targets"][0]["player_name"], "Trade Target")
        self.assertEqual(room["fades"][0]["player_name"], "Roster Fade")
        self.assertEqual(room["pick_leverage"][0]["value_source"], "internal_round_curve")
        self.assertEqual(room["pick_leverage"][0]["priority"], "major_reacquisition_target")
        self.assertTrue(room["pick_leverage"][1]["ownership_status"] == "your_original_pick_away")
        self.assertEqual(room["draft_context"]["status"], "complete")
        self.assertEqual(room["draft_context"]["rounds"], 4)
        self.assertEqual(room["draft_context"]["teams"], 12)
        self.assertIn("preparation board", room["draft_context"]["message"])

    def test_draft_room_does_not_call_another_manager_player_available(self) -> None:
        """Design source: docs/data_contract.md; availability is a league fact, not a name-label comparison."""
        room = build_draft_room(
            {
                "roster_players": [
                    {"season": "2026", "roster_id": 2, "player_id": "mine", "player_name": "My Player"},
                    {"season": "2026", "roster_id": 8, "player_id": "cook-id", "player_name": "James Cook"},
                ],
                "players": [{"player_id": "cook-id", "full_name": "James Cook", "position": "RB"}],
                "team_needs_matrix": [{"roster_id": 2, "team_shape": "rebuild_asset_bank", "need_rb": "high"}],
                "player_market_values": [{"player_id": "", "player_name": "James Cook III", "position": "RB", "market_value": 50, "source_trace": "market"}],
            },
            {"current_season": "2026"},
            league_id="league-1",
            my_roster_id=2,
            my_team_name="My Team",
        )

        self.assertFalse(any(row["player_name"] == "James Cook III" for row in room["draft_board"]))

    def test_draft_room_prefers_confirmed_active_event_over_completed_history(self) -> None:
        room = build_draft_room(
            {
                "drafts": [
                    {"season": "2026", "draft_id": "completed", "status": "complete", "type": "linear", "settings": {"rounds": 4, "teams": 12}},
                    {"season": "2026", "draft_id": "upcoming", "status": "pre_draft", "type": "linear", "settings": {"rounds": 4, "teams": 12, "pick_timer": 1800}},
                ]
            },
            {"current_season": "2026"},
            league_id="league-1",
            my_roster_id=2,
            my_team_name="Prep Team",
        )

        self.assertEqual(room["draft_context"]["draft_id"], "upcoming")
        self.assertEqual(room["draft_context"]["label"], "Upcoming draft")
        self.assertTrue(room["draft_context"]["is_upcoming"])
        self.assertFalse(room["draft_context"]["is_live"])

        future = build_draft_room(
            {"drafts": [{"season": "2027", "draft_id": "future", "status": "pre_draft", "type": "snake", "settings": {}}]},
            {"current_season": "2026"},
            league_id="league-1",
            my_roster_id=2,
            my_team_name="Prep Team",
        )
        self.assertEqual(future["draft_context"]["label"], "Upcoming 2027 draft")
        self.assertIn("no 2026 draft event", future["draft_context"]["message"])

    def test_dynastyprocess_pick_rank_file_is_not_presented_as_trade_value(self) -> None:
        frame = _normalize_pick_values(
            pd.DataFrame([{"player": "2027 Early 1st", "pos": "PICK", "ecr_2qb": 33.7, "pick": pd.NA}])
        )
        row = frame.iloc[0]
        self.assertEqual(row["pick_label"], "2027 Early 1st")
        self.assertEqual(row["pick_season"], "2027")
        self.assertEqual(row["round"], "1")
        self.assertEqual(row["market_value"], "")
        self.assertEqual(row["ranking_value"], 33.7)
        self.assertEqual(row["value_status"], "rank_only")

    def test_draft_room_is_honest_when_no_draft_event_is_confirmed(self) -> None:
        room = build_draft_room(
            {},
            {"current_season": "2026"},
            league_id="no-draft-event",
            my_roster_id=2,
            my_team_name="Prep Team",
        )

        self.assertEqual(room["draft_context"]["status"], "unavailable")
        self.assertIn("No 2026 draft event", room["draft_context"]["message"])

    def test_browser_surface_accepts_explicit_league_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            site = Path(tmp) / "site"
            processed.mkdir()
            self._write_minimal_processed_tables(processed)

            build_browser_site(
                site,
                processed,
                config={
                    "current_season": "2099",
                    "current_team": {"roster_id": 2, "team_name": "League Custom Team", "display_name": "custom"},
                    "strategy_profile": {"name": "League-specific rebuild", "team_direction": "rebuild"},
                    "writer_preferences": {"persona_id": "scout", "custom_instructions": "Stay close to role evidence."},
                    "tracked_picks": [{"pick_season": "2099", "round": 1}],
                },
            )
            bundle = json.loads((site / "data" / "app_bundle.json").read_text(encoding="utf-8"))
            editorial = json.loads((site / "data" / "editorial_issue.json").read_text(encoding="utf-8"))
            html = (site / "index.html").read_text(encoding="utf-8")

        self.assertEqual(bundle["currentSeason"], "2099")
        self.assertEqual(bundle["strategyProfile"]["name"], "League-specific rebuild")
        self.assertEqual(bundle["trackedPicks"][0]["round"], 1)
        self.assertEqual(bundle["reporterPersona"]["persona_id"], "scout")
        self.assertEqual(editorial["reporter_persona"]["name"], "The Scout")
        self.assertIn("projectionPpgText", html)
        self.assertIn("conditional baseline PPG if signed", html)

    def test_live_smoke_script_exists_with_required_markers(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_live.py"
        text = script.read_text(encoding="utf-8")

        self.assertIn("fantasy-dominator-production.up.railway.app", text)
        self.assertIn("The Front Office", text)
        self.assertIn("Personal Edition", text)
        self.assertIn("editorial-issue", text)
        self.assertIn("Signal pulse", text)
        self.assertIn("Show the evidence", text)
        self.assertIn("Today's Board", text)
        self.assertIn("brief-card", text)
        self.assertIn("Projection Board", text)
        self.assertIn("Signal Board", text)
        self.assertIn("Analyst Brief", text)
        self.assertIn("today-priority-board", text)
        self.assertIn("News Desk", text)
        self.assertIn("Data Room", text)
        self.assertIn("Data Diagnostics", text)
        self.assertIn("FRONT_OFFICE_SESSION_TOKEN", text)
        self.assertIn("validate_authenticated_edition", text)
        self.assertIn("data/manifest.json", text)
        self.assertIn("source revision", text)
        self.assertIn("/healthz", text)
        self.assertIn("FRONT_OFFICE_PUBLIC_ONLY", text)

    def test_projection_scoring_uses_league_settings_and_te_bonus(self) -> None:
        points = calculate_fantasy_points(
            {
                "projected_passing_yards": 250,
                "projected_passing_tds": 2,
                "projected_interceptions": 1,
                "projected_rushing_yards": 40,
                "projected_rushing_tds": 1,
                "projected_receptions": 5,
                "projected_receiving_yards": 50,
                "projected_receiving_tds": 1,
            },
            {"pass_yd": 0.04, "pass_td": 4, "pass_int": -1, "rush_yd": 0.1, "rush_td": 6, "rec": 0.5, "bonus_rec_te": 0.2, "rec_yd": 0.1, "rec_td": 6},
            "TE",
        )

        self.assertEqual(points, 41.5)

    def test_projection_consensus_blends_two_sources_and_flags_disagreement(self) -> None:
        components = [
            {
                "source": "nflverse_history",
                "projected_fantasy_points": 200.0,
                "projected_ppg": 11.76,
                "projected_games": 17,
                "source_confidence": "high",
                "source_trace": "nflverse",
                "projection_method": "recent_nflverse_per_game_2yr",
            },
            {
                "source": "fantasy_nerds",
                "projected_fantasy_points": 260.0,
                "projected_ppg": 15.29,
                "projected_games": 17,
                "source_confidence": "high",
                "source_trace": "fantasy_nerds",
                "projection_method": "fantasy_nerds_weekly_projection",
            },
        ]

        blended = _blend_projection_components(components, {})

        self.assertEqual(blended["source_count"], 2)
        self.assertEqual(blended["disagreement_score"], 60.0)
        self.assertEqual(blended["projected_fantasy_points"], 230.0)
        self.assertIn("consensus_2src_", blended["projection_method"])
        self.assertIn("nflverse", blended["source_trace"])
        self.assertIn("fantasy_nerds", blended["source_trace"])

    def test_projection_tables_degrade_to_single_source_when_fantasy_nerds_absent(self) -> None:
        raw_stats = pd.DataFrame(
            [
                {"player_display_name": "Solo Source WR", "position": "WR", "recent_team": "AAA", "season": 2025, "week": week, "season_type": "REG", "receptions": 6, "receiving_yards": 80, "receiving_tds": 1, "passing_yards": 0, "passing_tds": 0, "interceptions": 0, "rushing_yards": 0, "rushing_tds": 0}
                for week in range(1, 6)
            ]
        )
        roster_players = pd.DataFrame(
            [{"season": "2026", "player_id": "sw1", "player_name": "Solo Source WR", "position": "WR", "nfl_team": "AAA", "roster_id": 2, "team_name": "Melkor Lord of Light"}]
        )
        leagues = pd.DataFrame([{"scoring_settings": json.dumps({"rec": 1, "rec_yd": 0.1, "rec_td": 6})}])
        config = {"current_season": "2026"}

        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "raw_external" / "nflverse" / "2026" / "player_stats.csv"
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            raw_stats.to_csv(stats_path, index=False)
            with patch("src.projections.RAW_EXTERNAL_DIR", Path(tmp) / "raw_external"):
                tables = build_projection_tables(config, leagues, roster_players)

        self.assertEqual(list(tables["player_projection_season"].columns), EXPECTED_TABLE_COLUMNS["player_projection_season"])
        row = tables["player_projection_season"].iloc[0]
        self.assertEqual(row["projection_method"], "recent_nflverse_per_game_1yr")
        self.assertEqual(len(tables["projection_source_components"]), 1)
        self.assertEqual(tables["projection_source_components"].iloc[0]["source"], "nflverse_history")

    def test_projection_rows_carry_current_availability_into_the_projection_contract(self) -> None:
        raw_stats = pd.DataFrame(
            [
                {"player_display_name": "Unsigned Historical RB", "position": "RB", "recent_team": "AAA", "season": 2025, "week": week, "season_type": "REG", "rushing_yards": 80, "rushing_tds": 1, "receptions": 2, "receiving_yards": 10, "receiving_tds": 0, "passing_yards": 0, "passing_tds": 0, "interceptions": 0, "receiving_tds": 0}
                for week in range(1, 6)
            ]
        )
        roster_players = pd.DataFrame(
            [{
                "season": "2026",
                "player_id": "unsigned-rb",
                "player_name": "Unsigned Historical RB",
                "position": "RB",
                "nfl_team": "",
                "availability_scope": "current_season_snapshot",
                "injury_status": "Questionable",
                "roster_id": 2,
                "team_name": "Lulu's Potatoe's",
            }]
        )
        leagues = pd.DataFrame([{"scoring_settings": json.dumps({"rec": 1, "rec_yd": 0.1, "rec_td": 6})}])

        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "raw_external" / "nflverse" / "2026" / "player_stats.csv"
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            raw_stats.to_csv(stats_path, index=False)
            with patch("src.projections.RAW_EXTERNAL_DIR", Path(tmp) / "raw_external"):
                tables = build_projection_tables({"current_season": "2026"}, leagues, roster_players)

        season_row = tables["player_projection_season"].iloc[0]
        weekly_row = tables["player_projection_weekly"].iloc[0]
        component_row = tables["projection_source_components"].iloc[0]
        for row in (season_row, weekly_row, component_row):
            self.assertEqual(row["current_availability_status"], "no_current_nfl_team")
            self.assertIn("No current NFL team", row["availability_note"])
        self.assertIn("historical production evidence", season_row["projection_note"])

    def test_fantasy_nerds_source_is_disabled_without_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            frames = refresh_external_sources({"source_policy": "open_legal_only", "external_sources": {"enabled": ["fantasy_nerds"]}})

        self.assertTrue(frames["fantasy_nerds_projection_source"].empty)
        freshness = frames["source_freshness"]
        fn_rows = freshness[freshness["source"] == "fantasy_nerds"]
        self.assertEqual(len(fn_rows), 1)
        self.assertEqual(fn_rows.iloc[0]["status"], "disabled:fantasy_nerds_api_key_missing")

    def test_source_accuracy_scores_grade_nflverse_against_actuals(self) -> None:
        rows = []
        for week in range(1, 6):
            rows.append({"player_display_name": "Backtest WR", "position": "WR", "recent_team": "AAA", "season": 2025, "week": week, "season_type": "REG", "receptions": 6, "receiving_yards": 80, "receiving_tds": 1, "passing_yards": 0, "passing_tds": 0, "interceptions": 0, "rushing_yards": 0, "rushing_tds": 0})
        for week in range(1, 6):
            rows.append({"player_display_name": "Backtest WR", "position": "WR", "recent_team": "AAA", "season": 2026, "week": week, "season_type": "REG", "receptions": 7, "receiving_yards": 90, "receiving_tds": 1, "passing_yards": 0, "passing_tds": 0, "interceptions": 0, "rushing_yards": 0, "rushing_tds": 0})
        raw_stats = pd.DataFrame(rows)
        leagues = pd.DataFrame([{"scoring_settings": json.dumps({"rec": 1, "rec_yd": 0.1, "rec_td": 6})}])

        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "projection_snapshot_history.csv"
            accuracy = build_projection_accuracy_table(raw_stats, leagues, {"current_season": "2027"}, history_path)

        self.assertEqual(len(accuracy), 1)
        row = accuracy.iloc[0]
        self.assertEqual(row["source"], "nflverse_history")
        self.assertEqual(row["mean_absolute_error"], 2.0)
        self.assertEqual(row["accuracy_confidence"], "low")  # sample_size (5) < 8 floor, same games-matched gating precedent as _project_player

    def test_signal_tables_still_consume_blended_projection_contract_unmodified(self) -> None:
        projections = pd.DataFrame(
            [
                {"player_id": "1", "player_name": "Young WR", "position": "WR", "roster_id": 8, "team_name": "The Clapper", "projected_fantasy_points": 180, "projected_ppg": 10.6, "projection_confidence": "high", "source_trace": "consensus_2src_fantasy_nerds_nflverse_history"},
            ]
        )
        roster = pd.DataFrame([{"player_id": "1", "player_name": "Young WR", "age": 23, "roster_id": 8, "team_name": "The Clapper"}])
        market = pd.DataFrame([{"player_id": "1", "player_name": "Young WR", "market_value": 15, "source_trace": "market"}])
        needs = pd.DataFrame([{"roster_id": 2, "team_name": "Melkor Lord of Light", "need_qb": "low", "need_rb": "low", "need_pass_catcher": "high", "team_shape": "rebuild_asset_bank"}])
        behavior = pd.DataFrame([{"roster_id": 8, "plain_language_label": "trade active"}])
        news = pd.DataFrame([{"player_id": "1", "impact_type": "market_heat"}])

        tables = build_signal_tables(
            projections, roster, market, needs, behavior, news,
            {"current_team": {"roster_id": 2}, "strategy_profile": {"team_direction": "deep_rebuild"}},
        )

        self.assertIn("player_signal_scores", tables)
        self.assertEqual(len(tables["player_signal_scores"]), 1)
        self.assertIn("evidence", tables["player_signal_scores"].columns)

    def test_news_market_edges_are_scoped_and_explain_the_dislocation(self) -> None:
        scores = pd.DataFrame([
            {
                "player_id": "up",
                "player_name": "News Lag WR",
                "position": "WR",
                "roster_id": 2,
                "team_name": "My Team",
                "market_value": 18,
                "projected_ppg": 14.2,
                "market_gap_score": 44,
                "sell_score": 0,
                "confidence": "high",
                "source_trace": "signals",
            },
            {
                "player_id": "down",
                "player_name": "Pressure RB",
                "position": "RB",
                "roster_id": 2,
                "team_name": "My Team",
                "market_value": 78,
                "projected_ppg": 8.1,
                "market_gap_score": 0,
                "sell_score": 52,
                "confidence": "medium",
                "source_trace": "signals",
            },
            {
                "player_id": "quiet",
                "player_name": "No News Player",
                "position": "TE",
                "roster_id": 2,
                "team_name": "My Team",
                "market_value": 30,
                "projected_ppg": 10,
                "market_gap_score": 50,
                "sell_score": 0,
                "confidence": "high",
                "source_trace": "signals",
            },
        ])
        news = pd.DataFrame([
            {"player_id": "up", "player_name": "News Lag WR", "league_id": "league-a", "season": "2026", "impact_type": "market_heat", "evidence": "add volume is rising", "confidence": "high", "source_trace": "sleeper"},
            {"player_id": "up", "player_name": "News Lag WR", "league_id": "league-b", "season": "2026", "impact_type": "sell_pressure", "evidence": "other league drop signal", "confidence": "high", "source_trace": "wrong-league"},
            {"player_id": "down", "player_name": "Pressure RB", "league_id": "league-a", "season": "2026", "impact_type": "injury_risk", "evidence": "limited practice", "confidence": "medium", "source_trace": "rotowire"},
            {"player_id": "quiet", "player_name": "No News Player", "league_id": "league-b", "season": "2026", "impact_type": "market_heat", "evidence": "wrong league", "confidence": "high", "source_trace": "wrong-league"},
        ])

        edges = build_news_market_edges(
            scores,
            news,
            {"context": {"league_id": "league-a", "season": "2026"}},
        )

        self.assertEqual(set(edges["player_id"]), {"up", "down"})
        upside = edges.loc[edges["player_id"] == "up"].iloc[0]
        pressure = edges.loc[edges["player_id"] == "down"].iloc[0]
        self.assertEqual(upside["edge_type"], "news_lag_upside")
        self.assertEqual(pressure["edge_type"], "news_lag_pressure")
        self.assertEqual(upside["league_id"], "league-a")
        self.assertNotIn("wrong-league", str(upside["evidence"]))
        self.assertIn("market_gap=44", str(upside["evidence"]))
        self.assertIn("sell_score=52", str(pressure["evidence"]))
        self.assertIn("news_market_edges", str(upside["source_trace"]))

    def test_signal_evidence_keeps_injury_separate_from_baseline_ppg(self) -> None:
        projections = pd.DataFrame(
            [{
                "player_id": "3321",
                "player_name": "Tyreek Hill",
                "position": "WR",
                "roster_id": 2,
                "team_name": "Lulu's Potatoe's",
                "projected_fantasy_points": 255,
                "projected_ppg": 15.0,
                "projection_confidence": "high",
                "source_trace": "projection",
            }]
        )
        roster = pd.DataFrame(
            [{
                "player_id": "3321",
                "player_name": "Tyreek Hill",
                "position": "WR",
                "age": 32,
                "roster_id": 2,
                "team_name": "Lulu's Potatoe's",
                "injury_status": "Questionable",
                "injury_body_part": "Knee - ACL",
            }]
        )
        tables = build_signal_tables(
            projections,
            roster,
            pd.DataFrame([{"player_id": "3321", "player_name": "Tyreek Hill", "market_value": 40, "source_trace": "market"}]),
            pd.DataFrame([{"roster_id": 2, "team_name": "Lulu's Potatoe's", "need_pass_catcher": "medium", "team_shape": "balanced_or_unclear"}]),
            pd.DataFrame(columns=["roster_id"]),
            pd.DataFrame(columns=["player_id"]),
            {"current_team": {"roster_id": 2}},
        )

        signal = tables["player_signal_scores"].iloc[0]
        self.assertIn("baseline_ppg=15.0", str(signal["evidence"]))
        self.assertIn("Questionable (Knee - ACL)", str(signal["evidence"]))
        self.assertIn("baseline projection does not adjust for availability", str(signal["risk"]))

    def test_canonical_high_market_values_are_not_divided_again(self) -> None:
        """Encodes docs/data_contract.md: ingestion owns source-scale normalization."""
        self.assertEqual(_normalize_market(102.32), 102.32)
        self.assertEqual(_normalize_market(75.92), 75.92)

        projections = pd.DataFrame([
            {"player_id": "qb", "player_name": "High Value QB", "position": "QB", "roster_id": 1, "team_name": "Rival", "projected_fantasy_points": 408.51, "projected_ppg": 24.03, "projection_confidence": "high", "source_trace": "projection"},
        ])
        roster = pd.DataFrame([{"player_id": "qb", "player_name": "High Value QB", "position": "QB", "age": 28, "roster_id": 1, "team_name": "Rival"}])
        signals = build_signal_tables(
            projections,
            roster,
            pd.DataFrame([{"player_id": "qb", "player_name": "High Value QB", "market_value": 102.32, "source_trace": "market"}]),
            pd.DataFrame([{"roster_id": 1, "team_name": "Rival", "need_qb": "low", "team_shape": "contender_shape"}]),
            pd.DataFrame(columns=["roster_id"]),
            pd.DataFrame(columns=["player_id"]),
            {"current_team": {"roster_id": 2}},
        )
        self.assertLess(float(signals["player_signal_scores"].iloc[0]["market_gap_score"]), 80.0)

        aging = build_signal_tables(
            projections.assign(player_id="old-qb", player_name="Aging Backup", projected_ppg=18.57, projected_fantasy_points=315.69),
            roster.assign(player_id="old-qb", player_name="Aging Backup", age=41),
            pd.DataFrame([{"player_id": "old-qb", "player_name": "Aging Backup", "market_value": 0.03, "source_trace": "market"}]),
            pd.DataFrame([{"roster_id": 1, "team_name": "Rival", "need_qb": "low", "team_shape": "contender_shape"}]),
            pd.DataFrame(columns=["roster_id"]),
            pd.DataFrame(columns=["player_id"]),
            {"current_team": {"roster_id": 2}},
        )
        aging_signal = aging["player_signal_scores"].iloc[0]
        self.assertEqual(aging_signal["signal_label"], "role_uncertain_watch")
        self.assertIn("age/role uncertainty", str(aging_signal["risk"]))
        self.assertEqual(aging["projection_market_gaps"].iloc[0]["gap_label"], "role_uncertain_gap")

    def test_market_gap_is_position_relative_not_raw_ppg_minus_market(self) -> None:
        """Encodes docs/data_contract.md: disagreement must compare calibrated peer ranks."""
        projections = pd.DataFrame([
            {"player_id": "qb1", "player_name": "Low QB", "position": "QB", "roster_id": 1, "team_name": "A", "projected_fantasy_points": 170, "projected_ppg": 10, "projection_confidence": "high", "source_trace": "projection"},
            {"player_id": "qb2", "player_name": "Mid QB", "position": "QB", "roster_id": 2, "team_name": "B", "projected_fantasy_points": 255, "projected_ppg": 15, "projection_confidence": "high", "source_trace": "projection"},
            {"player_id": "qb3", "player_name": "Elite QB", "position": "QB", "roster_id": 3, "team_name": "C", "projected_fantasy_points": 340, "projected_ppg": 20, "projection_confidence": "high", "source_trace": "projection"},
            {"player_id": "qb4", "player_name": "Top QB", "position": "QB", "roster_id": 4, "team_name": "D", "projected_fantasy_points": 408, "projected_ppg": 24, "projection_confidence": "high", "source_trace": "projection"},
        ])
        roster = projections[["player_id", "player_name", "position", "roster_id", "team_name"]].assign(age=25)
        market = pd.DataFrame([
            {"player_id": "qb1", "player_name": "Low QB", "position": "QB", "market_value": 10, "source_trace": "market"},
            {"player_id": "qb2", "player_name": "Mid QB", "position": "QB", "market_value": 20, "source_trace": "market"},
            {"player_id": "qb3", "player_name": "Elite QB", "position": "QB", "market_value": 75, "source_trace": "market"},
            {"player_id": "qb4", "player_name": "Top QB", "position": "QB", "market_value": 102, "value_format": "consensus_sources=1", "source_trace": "market"},
        ])
        signals = build_signal_tables(
            projections,
            roster,
            market,
            pd.DataFrame([{"roster_id": 1, "team_name": "A", "need_qb": "medium", "need_rb": "low", "need_pass_catcher": "low", "team_shape": "balanced_or_unclear"}]),
            pd.DataFrame(columns=["roster_id"]),
            pd.DataFrame(columns=["player_id"]),
            {"current_team": {"roster_id": 2}},
        )
        top = signals["player_signal_scores"].loc[lambda frame: frame["player_id"] == "qb4"].iloc[0]
        elite = signals["player_signal_scores"].loc[lambda frame: frame["player_id"] == "qb3"].iloc[0]
        self.assertLessEqual(float(top["market_gap_score"]), 5.0)
        self.assertLessEqual(float(elite["market_gap_score"]), 5.0)
        self.assertEqual(top["market_gap_status"], "position_percentile_aligned")
        self.assertEqual(top["confidence"], "medium")
        self.assertIn("single-source market evidence", str(top["risk"]))
        self.assertIn("projection_percentile=", str(top["evidence"]))

    def test_proxy_market_flows_into_signals_and_player_dossiers_with_receipt(self) -> None:
        """Encodes docs/data_contract.md: proxy values are explicit fallback evidence, not zero market."""
        projections = pd.DataFrame([
            {"player_id": "proxy", "player_name": "Proxy WR", "position": "WR", "roster_id": 8, "team_name": "The Clapper", "projected_fantasy_points": 180, "projected_ppg": 10.6, "projection_confidence": "high", "source_trace": "projection"},
        ])
        roster = pd.DataFrame([
            {"player_id": "proxy", "player_name": "Proxy WR", "position": "WR", "age": 23, "roster_id": 8, "team_name": "The Clapper", "season": "2026"},
        ])
        needs = pd.DataFrame([{"roster_id": 8, "team_name": "The Clapper", "need_pass_catcher": "medium", "team_shape": "balanced_or_unclear"}])
        inventory = pd.DataFrame([
            {"roster_id": 8, "team_name": "The Clapper", "asset_type": "player", "asset_id": "proxy", "asset_name": "Proxy WR", "market_value": 43, "source_trace": "internal_proxy_player_value"},
        ])
        tables = build_signal_tables(
            projections,
            roster,
            pd.DataFrame(columns=["player_id", "market_value", "source_trace"]),
            needs,
            pd.DataFrame(columns=["roster_id"]),
            pd.DataFrame(columns=["player_id"]),
            {"current_team": {"roster_id": 2}, "strategy_profile": {"team_direction": "deep_rebuild"}},
            team_asset_inventory_df=inventory,
        )
        signal = tables["player_signal_scores"].iloc[0]
        action = tables["action_recommendations"].iloc[0]
        dossiers = build_player_dossiers(
            roster,
            pd.DataFrame(columns=["player_id", "consensus_value", "source_trace"]),
            projections,
            pd.DataFrame(),
            pd.DataFrame(),
            tables["player_signal_scores"],
            pd.DataFrame(),
            inventory,
        )

        self.assertEqual(float(signal["market_value"]), 43.0)
        self.assertEqual(float(action["market_value"]), 43.0)
        self.assertIn("internal_proxy_player_value", str(signal["source_trace"]))
        self.assertIn("internal proxy used", str(signal["risk"]))
        self.assertEqual(float(dossiers.iloc[0]["market_value"]), 43.0)
        self.assertIn("internal_proxy_player_value", str(dossiers.iloc[0]["source_trace"]))
        self.assertEqual(_player_confidence(dossiers.iloc[0]), "medium")

    def test_signal_tables_create_breakouts_and_sell_candidates(self) -> None:
        projections = pd.DataFrame(
            [
                {"player_id": "1", "player_name": "Young WR", "position": "WR", "roster_id": 8, "team_name": "The Clapper", "projected_fantasy_points": 180, "projected_ppg": 10.6, "projection_confidence": "high", "source_trace": "projection"},
                {"player_id": "2", "player_name": "Aging RB", "position": "RB", "roster_id": 2, "team_name": "Melkor Lord of Light", "projected_fantasy_points": 130, "projected_ppg": 7.6, "projection_confidence": "medium", "source_trace": "projection"},
            ]
        )
        roster = pd.DataFrame(
            [
                {"player_id": "1", "player_name": "Young WR", "age": 23, "roster_id": 8, "team_name": "The Clapper"},
                {"player_id": "2", "player_name": "Aging RB", "age": 29, "roster_id": 2, "team_name": "Melkor Lord of Light"},
            ]
        )
        market = pd.DataFrame(
            [{"player_id": "1", "player_name": "Young WR", "market_value": 15, "source_trace": "market"}]
        )
        needs = pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "need_qb": "low", "need_rb": "low", "need_pass_catcher": "high", "team_shape": "rebuild_asset_bank"}]
        )
        behavior = pd.DataFrame(
            [{"roster_id": 8, "plain_language_label": "trade active"}]
        )
        news = pd.DataFrame(
            [{"player_id": "1", "impact_type": "market_heat"}]
        )

        tables = build_signal_tables(
            projections,
            roster,
            market,
            needs,
            behavior,
            news,
            {"current_team": {"roster_id": 2}, "strategy_profile": {"team_direction": "deep_rebuild"}},
        )

        self.assertIn("player_signal_scores", tables)
        self.assertGreater(len(tables["breakout_candidates"]), 0)
        self.assertGreater(len(tables["sell_candidates"]), 0)
        self.assertIn("evidence", tables["player_signal_scores"].columns)
        self.assertIn("action_recommendations", tables)
        self.assertIn("consumer_label", tables["action_recommendations"].columns)
        self.assertIn("counterparty_trade_edges", tables)
        self.assertIn("edge_type", tables["counterparty_trade_edges"].columns)

    def test_action_labels_are_consumer_calibrated(self) -> None:
        projections = pd.DataFrame(
            [
                {"player_id": "elite", "player_name": "Elite QB", "position": "QB", "roster_id": 2, "team_name": "Melkor Lord of Light", "projected_fantasy_points": 360, "projected_ppg": 21.2, "projection_confidence": "high", "source_trace": "projection"},
                {"player_id": "rb", "player_name": "Aging RB", "position": "RB", "roster_id": 2, "team_name": "Melkor Lord of Light", "projected_fantasy_points": 240, "projected_ppg": 14.1, "projection_confidence": "high", "source_trace": "projection"},
                {"player_id": "wr", "player_name": "Young WR", "position": "WR", "roster_id": 8, "team_name": "The Clapper", "projected_fantasy_points": 170, "projected_ppg": 10.0, "projection_confidence": "high", "source_trace": "projection"},
                {"player_id": "noise", "player_name": "Rookie Noise", "position": "WR", "roster_id": 2, "team_name": "Melkor Lord of Light", "projected_fantasy_points": 0, "projected_ppg": 0, "projection_confidence": "low", "source_trace": "projection"},
            ]
        )
        roster = pd.DataFrame(
            [
                {"player_id": "elite", "age": 25, "roster_id": 2, "team_name": "Melkor Lord of Light"},
                {"player_id": "rb", "age": 29, "roster_id": 2, "team_name": "Melkor Lord of Light"},
                {"player_id": "wr", "age": 23, "roster_id": 8, "team_name": "The Clapper"},
                {"player_id": "noise", "age": 21, "roster_id": 2, "team_name": "Melkor Lord of Light"},
            ]
        )
        market = pd.DataFrame(
            [
                {"player_id": "elite", "player_name": "Elite QB", "position": "QB", "market_value": 8000, "source_trace": "market"},
                {"player_id": "rb", "player_name": "Aging RB", "position": "RB", "market_value": 1200, "source_trace": "market"},
                {"player_id": "wr", "player_name": "Young WR", "position": "WR", "market_value": 20, "source_trace": "market"},
                {"player_id": "noise", "player_name": "Rookie Noise", "position": "WR", "market_value": 60, "source_trace": "market"},
                {"player_id": "wr-peer-1", "player_name": "WR Peer One", "position": "WR", "market_value": 70, "source_trace": "market"},
                {"player_id": "wr-peer-2", "player_name": "WR Peer Two", "position": "WR", "market_value": 80, "source_trace": "market"},
            ]
        )
        needs = pd.DataFrame([{"roster_id": 2, "team_name": "Melkor Lord of Light", "team_shape": "rebuild_asset_bank"}])
        behavior = pd.DataFrame(columns=["roster_id", "plain_language_label"])
        news = pd.DataFrame(columns=["player_id", "impact_type"])

        tables = build_signal_tables(
            projections,
            roster,
            market,
            needs,
            behavior,
            news,
            {"current_team": {"roster_id": 2}, "strategy_profile": {"team_direction": "deep_rebuild"}},
        )
        actions = tables["action_recommendations"].set_index("player_id")

        self.assertEqual(actions.loc["elite", "action_label"], "core_hold")
        self.assertEqual(actions.loc["rb", "action_label"], "sell_window")
        self.assertEqual(actions.loc["wr", "action_label"], "true_buy_low")
        self.assertEqual(actions.loc["noise", "action_label"], "avoid_noise")

    def test_analysis_artifacts_explain_signals_without_mutating_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = Path(tmp) / "analysis"
            dataframes = {
                "teams": pd.DataFrame(
                    [{"roster_id": 2, "display_name": "joe3489", "team_name": "Melkor Lord of Light"}]
                ),
                "breakout_candidates": pd.DataFrame(
                    [
                        {
                            "player_id": "1",
                            "player_name": "Young WR",
                            "position": "WR",
                            "current_team_name": "The Clapper",
                            "breakout_score": 72,
                            "projection_edge": 80,
                            "market_value": 25,
                            "evidence": "ppg=12; market=25",
                            "risk": "medium: verify role",
                            "confidence": "high",
                            "source_trace": "breakout_candidates;player_projection_season",
                        }
                    ]
                ),
                "sell_candidates": pd.DataFrame(
                    [
                        {
                            "player_id": "2",
                            "player_name": "Aging RB",
                            "position": "RB",
                            "current_team_name": "Melkor Lord of Light",
                            "sell_score": 61,
                            "projection_risk": "medium",
                            "market_value": 40,
                            "evidence": "age=29; ppg=8",
                            "risk": "medium: timing matters",
                            "confidence": "medium",
                            "source_trace": "sell_candidates;player_projection_season",
                        }
                    ]
                ),
                "manager_behavior_signals": pd.DataFrame(
                    [
                        {"roster_id": 8, "team_name": "The Clapper", "plain_language_label": "pick seller / win-now buyer", "evidence": "sold future first", "trade_activity_score": 70, "pick_seller_score": 80, "faab_aggression_score": 0}
                    ]
                ),
                "opportunity_board": pd.DataFrame(
                    [
                        {"action_type": "buy_low_target", "target_team": "The Clapper", "asset_in": "Young WR", "asset_out": "future offer packet only", "manager_signal": "pick seller", "evidence": "market gap", "risk": "medium", "confidence": "medium", "source_trace": "opportunity_board"}
                    ]
                ),
                "league_news_impact": pd.DataFrame(
                    [
                        {"player_name": "Young WR", "evidence": "trending add", "risk": "medium", "confidence": "medium", "source_trace": "league_news_impact"}
                    ]
                ),
                "action_recommendations": pd.DataFrame(
                    [
                        {"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "1", "player_name": "Young WR", "position": "WR", "age": 23, "action_label": "true_buy_low", "consumer_label": "True Buy Low", "action_rank": 1, "action_score": 72, "projected_ppg": 10, "market_value": 25, "why": "Projection and market inputs suggest the price may lag the role or production.", "evidence": "ppg=12; market=25", "risk": "medium: verify role", "confidence": "high", "source_trace": "action_recommendations;player_projection_season"},
                        {"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "2", "player_name": "Aging RB", "position": "RB", "age": 29, "action_label": "sell_window", "consumer_label": "Sell Window", "action_rank": 1, "action_score": 61, "projected_ppg": 12, "market_value": 40, "why": "Aging RB production is more valuable to contenders than to a rebuild timeline.", "evidence": "age=29; ppg=8", "risk": "medium: timing matters", "confidence": "medium", "source_trace": "action_recommendations;player_projection_season"},
                    ]
                ),
            }

            metadata = build_analysis_artifacts(
                analysis_dir,
                dataframes,
                {"current_team": {"roster_id": 2}},
                2,
            )

            target_payload = json.loads((analysis_dir / "target_theses.json").read_text(encoding="utf-8"))
            target_items = target_payload["items"]
            validation_text = (analysis_dir / "analysis_validation.json").read_text(encoding="utf-8")
            daily_brief = (analysis_dir / "daily_gm_brief.md").read_text(encoding="utf-8")

        self.assertEqual(metadata["status"], "generated")
        self.assertEqual(metadata["target_thesis_count"], 1)
        self.assertIn("source_trace", target_items[0])
        self.assertIn("analysis_text", target_items[0])
        self.assertIn("Target Theses", daily_brief)
        self.assertIn('"evidence_ids":["player:1:1"', daily_brief)
        self.assertNotIn("accepted", validation_text.lower())

    def test_external_sources_fail_soft_with_diagnostics(self) -> None:
        frames = refresh_external_sources({"source_policy": "open_legal_only", "external_sources": {"enabled": []}})

        self.assertIn("source_freshness", frames)
        self.assertEqual(frames["source_freshness"].iloc[0]["source"], "external_sources")
        self.assertEqual(frames["source_freshness"].iloc[0]["status"], "no_external_sources_enabled")
        self.assertIn("player_market_values", frames)
        self.assertIn("market_value_sources", frames)
        self.assertIn("market_consensus_values", frames)

    def test_user_market_files_are_explicit_components_in_consensus(self) -> None:
        """Design source: docs/data_contract.md; user market inputs stay labeled and never get rescaled."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pd.DataFrame([{
                "player_name": "Manual Receiver", "position": "WR", "market_value": 72,
                "confidence": "high", "market_rank": 10,
            }]).to_csv(root / "market-a.csv", index=False)
            pd.DataFrame([{
                "player_name": "Manual Receiver", "position": "WR", "market_value": 64,
                "confidence": "medium", "market_rank": 14,
            }]).to_csv(root / "market-b.csv", index=False)

            with patch("src.external_sources.DATA_DIR", root):
                frames = refresh_external_sources(
                    {
                        "current_season": "2026",
                        "source_policy": "restricted_for_test",
                        "external_sources": {
                            "enabled": [],
                            "market_value_files": [
                                {"path": "market-a.csv", "source": "analyst_a"},
                                {"path": "market-b.csv", "source": "analyst_b"},
                            ],
                        },
                    }
                )

        sources = frames["market_value_sources"]
        consensus = frames["market_consensus_values"]
        self.assertEqual(len(sources), 2)
        self.assertTrue((sources["source_access_type"] == "user_provided").all())
        self.assertEqual(len(consensus), 1)
        self.assertAlmostEqual(float(consensus.iloc[0]["consensus_value"]), 68.0)
        self.assertEqual(int(consensus.iloc[0]["source_count"]), 2)
        self.assertAlmostEqual(float(consensus.iloc[0]["disagreement_score"]), 8.0)
        self.assertEqual(consensus.iloc[0]["best_source"], "user_provided_analyst_a")
        self.assertIn("manual_file:market-a.csv", str(consensus.iloc[0]["source_trace"]))
        self.assertIn("manual_file:market-b.csv", str(consensus.iloc[0]["source_trace"]))

    def test_market_consensus_preserves_component_traces_and_access_policy(self) -> None:
        sources = pd.DataFrame(
            [
                {
                    "source": "dynastyprocess",
                    "source_access_type": "open_dataset",
                    "source_player_id": "1",
                    "player_id": "1",
                    "player_name": "Young WR",
                    "position": "WR",
                    "raw_value": 4200,
                    "normalized_value": 42,
                    "market_rank": 50,
                    "value_format": "superflex_preferred",
                    "source_confidence": "high",
                    "source_trace": "https://github.com/DynastyProcess/data",
                    "checked_at": "2026-06-07T00:00:00+00:00",
                },
                {
                    "source": "user_file",
                    "source_access_type": "user_provided",
                    "source_player_id": "1",
                    "player_id": "1",
                    "player_name": "Young WR",
                    "position": "WR",
                    "raw_value": 3800,
                    "normalized_value": 38,
                    "market_rank": 60,
                    "value_format": "manual_import",
                    "source_confidence": "medium",
                    "source_trace": "manual_file:data/manual/market_values/2026/example.csv",
                    "checked_at": "2026-06-07T00:00:00+00:00",
                },
            ]
        )

        consensus = build_market_consensus_values(sources)

        self.assertEqual(float(consensus.iloc[0]["consensus_value"]), 40.0)
        self.assertEqual(int(consensus.iloc[0]["source_count"]), 2)
        self.assertIn("DynastyProcess", consensus.iloc[0]["source_trace"])
        self.assertIn("manual_file", consensus.iloc[0]["source_trace"])

    def test_dynastyprocess_value_scale_normalizes_small_values_before_ranking(self) -> None:
        raw = pd.DataFrame(
            [
                {"sleeper_id": "11566", "player": "Jayden Daniels", "pos": "QB", "value_2qb": 7592},
                {"sleeper_id": "8180", "player": "Jalen Nailor", "pos": "WR", "value_2qb": 93},
            ]
        )

        normalized = _normalize_dynastyprocess_market_sources(raw)
        values = {row["player_name"]: float(row["normalized_value"]) for _, row in normalized.iterrows()}

        self.assertEqual(values["Jayden Daniels"], 75.92)
        self.assertEqual(values["Jalen Nailor"], 0.93)
        self.assertLess(values["Jalen Nailor"], values["Jayden Daniels"])
        self.assertIn("value_2qb/100", str(normalized.iloc[0]["source_trace"]))

    def test_news_tables_match_sleeper_trending_to_rostered_player(self) -> None:
        class FakeAPI:
            BASE_URL = "https://api.sleeper.app/v1"

            def trending_players(self, season: str, trend_type: str, force: bool = False):
                if trend_type == "add":
                    return [{"player_id": "1", "count": 25}]
                return []

        players = {
            "1": {
                "full_name": "Jayden Daniels",
                "position": "QB",
                "team": "WAS",
            }
        }
        teams = pd.DataFrame([{"roster_id": 2, "team_name": "Melkor Lord of Light"}])
        roster_players = pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB"}]
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.news.RAW_EXTERNAL_DIR", Path(tmp)):
                tables = build_news_tables(
                    {"current_season": "2026", "news_sources": {"enabled": ["sleeper_trending"]}},
                    FakeAPI(),
                    players,
                    teams,
                    roster_players,
                )

        self.assertEqual(tables["player_news_matches"].iloc[0]["player_id"], "1")
        self.assertEqual(tables["player_news_matches"].iloc[0]["match_confidence"], "high")
        self.assertEqual(tables["league_news_impact"].iloc[0]["team_name"], "Melkor Lord of Light")
        self.assertEqual(tables["league_news_impact"].iloc[0]["impact_type"], "market_heat")
        self.assertEqual(tables["news_source_freshness"].iloc[0]["status"], "refreshed")

    def test_news_impact_preserves_league_boundary_when_roster_ids_repeat(self) -> None:
        """Encodes AGENTS.md's Clerk -> Sleeper -> league -> roster identity rule for news."""
        class FakeAPI:
            BASE_URL = "https://api.sleeper.app/v1"

            def trending_players(self, season: str, trend_type: str, force: bool = False):
                return [{"player_id": "1", "count": 25}] if trend_type == "add" else []

        players = {"1": {"full_name": "Jayden Daniels", "position": "QB", "team": "WAS"}}
        teams = pd.DataFrame([
            {"season": "2026", "league_id": "league-a", "roster_id": 2, "team_name": "A Team"},
            {"season": "2026", "league_id": "league-b", "roster_id": 2, "team_name": "B Team"},
        ])
        roster_players = pd.DataFrame([
            {"season": "2026", "league_id": "league-a", "roster_id": 2, "team_name": "A Team", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB"},
            {"season": "2026", "league_id": "league-b", "roster_id": 2, "team_name": "B Team", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.news.RAW_EXTERNAL_DIR", Path(tmp)):
                tables = build_news_tables(
                    {"current_season": "2026", "news_sources": {"enabled": ["sleeper_trending"]}},
                    FakeAPI(),
                    players,
                    teams,
                    roster_players,
                )

        impact = tables["league_news_impact"]
        self.assertEqual(set(impact["league_id"]), {"league-a", "league-b"})
        self.assertEqual(set(impact["team_name"]), {"A Team", "B Team"})
        self.assertEqual(set(impact["roster_id"]), {2})

    def test_current_news_does_not_attach_to_completed_season_ownership(self) -> None:
        """Encodes the current-news versus historical-roster provenance boundary."""
        class FakeAPI:
            BASE_URL = "https://api.sleeper.app/v1"

            def trending_players(self, season: str, trend_type: str, force: bool = False):
                return [{"player_id": "1", "count": 25}] if trend_type == "add" else []

        players = {"1": {"full_name": "Jayden Daniels", "position": "QB", "team": "WAS"}}
        teams = pd.DataFrame([
            {"season": "2025", "league_id": "league-a", "roster_id": 2, "team_name": "Old Team"},
            {"season": "2026", "league_id": "league-a", "roster_id": 2, "team_name": "Current Team"},
        ])
        roster_players = pd.DataFrame([
            {"season": "2025", "league_id": "league-a", "roster_id": 2, "team_name": "Old Team", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB"},
            {"season": "2026", "league_id": "league-a", "roster_id": 2, "team_name": "Current Team", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.news.RAW_EXTERNAL_DIR", Path(tmp)):
                tables = build_news_tables(
                    {"current_season": "2026", "news_sources": {"enabled": ["sleeper_trending"]}},
                    FakeAPI(),
                    players,
                    teams,
                    roster_players,
                )

        impact = tables["league_news_impact"]
        self.assertEqual(len(impact), 1)
        self.assertEqual(str(impact.iloc[0]["season"]), "2026")
        self.assertEqual(impact.iloc[0]["team_name"], "Current Team")

    def test_news_tables_deduplicate_repeated_source_events(self) -> None:
        from src import news

        duplicate = {
            "source": "rotowire_rss",
            "event_id": "same-event",
            "event_type": "player_news",
            "published_at": "2026-08-22T10:00:00+00:00",
            "title": "Player: role update",
            "summary": "Role update.",
            "url": "https://news.example/same-event",
            "player_id": "",
            "player_name": "Player",
            "team": "",
            "position": "",
            "source_trace": "https://news.example/feed",
        }
        with patch.object(
            news,
            "_load_rotowire_rss",
            return_value=(
                [duplicate, duplicate.copy()],
                {"source": "rotowire_rss", "dataset": "nfl_player_news", "status": "refreshed", "source_url": "feed", "cache_path": "", "checked_at": "now"},
            ),
        ):
            tables = build_news_tables(
                {"current_season": "2026", "news_sources": {"enabled": ["rotowire_rss"]}},
                object(),
                {},
                pd.DataFrame(),
                pd.DataFrame(),
            )

        self.assertEqual(len(tables["news_events"]), 1)

    def test_cached_sleeper_trending_keeps_cache_time_instead_of_now(self) -> None:
        class FakeAPI:
            BASE_URL = "https://api.sleeper.app/v1"

            def trending_players(self, season: str, trend_type: str, force: bool = False):
                return [{"player_id": "1", "count": 25}] if trend_type == "add" else []

        players = {"1": {"full_name": "Jayden Daniels", "position": "QB", "team": "WAS"}}
        teams = pd.DataFrame([{"roster_id": 2, "team_name": "Melkor Lord of Light"}])
        roster_players = pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB"}]
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "raw_external"
            cache_path = cache_root / "sleeper" / "2026" / "trending_add.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("[]", encoding="utf-8")
            cached_at = (datetime.now(timezone.utc) - pd.Timedelta(seconds=30)).timestamp()
            os.utime(cache_path, (cached_at, cached_at))
            with patch("src.news.RAW_EXTERNAL_DIR", cache_root):
                tables = build_news_tables(
                    {"current_season": "2026", "news_sources": {"enabled": ["sleeper_trending"]}},
                    FakeAPI(),
                    players,
                    teams,
                    roster_players,
                    force=False,
                )

        self.assertEqual(tables["news_source_freshness"].iloc[0]["status"], "cached")
        observed_at = datetime.fromisoformat(str(tables["news_events"].iloc[0]["published_at"]))
        self.assertAlmostEqual(observed_at.timestamp(), cached_at, delta=1)

    def test_manager_event_log_preserves_league_and_owner_identity(self) -> None:
        teams = pd.DataFrame(
            [
                {"season": "2026", "league_id": "league-a", "roster_id": 2, "owner_id": "joe", "team_name": "Lulu's Potatoes"},
                {"season": "2026", "league_id": "league-b", "roster_id": 2, "owner_id": "kyle", "team_name": "Moose Caboose"},
            ]
        )
        trades = pd.DataFrame(
            [
                {"season": "2026", "league_id": "league-a", "week": 3, "transaction_id": "trade-a", "team_a_roster_id": 2, "team_a_name": "Lulu's Potatoes", "team_b_roster_id": 4, "team_b_name": "A Team"},
                {"season": "2026", "league_id": "league-b", "week": 3, "transaction_id": "trade-b", "team_a_roster_id": 2, "team_a_name": "Moose Caboose", "team_b_roster_id": 4, "team_b_name": "B Team"},
            ]
        )
        events = build_manager_event_log(teams, trades, pd.DataFrame())
        owned = events[events["roster_id"] == 2].sort_values("league_id")
        self.assertEqual(list(owned["league_id"]), ["league-a", "league-b"])
        self.assertEqual(list(owned["owner_id"]), ["joe", "kyle"])
        self.assertEqual(list(owned["team_name"]), ["Lulu's Potatoes", "Moose Caboose"])

    def test_economic_tables_create_market_gaps_and_behavior_signals(self) -> None:
        teams = pd.DataFrame(
            [
                {"roster_id": 2, "display_name": "joe3489", "team_name": "Melkor Lord of Light"},
                {"roster_id": 8, "display_name": "other", "team_name": "The Clapper"},
            ]
        )
        roster_players = pd.DataFrame(
            [
                {
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "age": 25,
                    "roster_status": "starter",
                },
                {
                    "roster_id": 8,
                    "team_name": "The Clapper",
                    "player_id": "2",
                    "player_name": "Young WR",
                    "position": "WR",
                    "age": 23,
                    "roster_status": "bench",
                },
            ]
        )
        pick_ownership = pd.DataFrame(
            [
                {
                    "original_roster_id": 2,
                    "original_team": "Melkor Lord of Light",
                    "pick_season": "2027",
                    "round": 1,
                    "current_owner_roster_id": 8,
                    "current_owner": "The Clapper",
                }
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "week": 1,
                    "transaction_id": "t1",
                    "created_datetime": "2026-06-06T00:00:00+00:00",
                    "team_a_roster_id": 2,
                    "team_a_name": "Melkor Lord of Light",
                    "team_a_players_received": "",
                    "team_a_picks_received": "2027 R1 original roster 8",
                    "team_a_faab_received": 0,
                    "team_b_roster_id": 8,
                    "team_b_name": "The Clapper",
                    "team_b_players_received": "Veteran RB",
                    "team_b_picks_received": "",
                    "team_b_faab_received": 0,
                }
            ]
        )
        waivers = pd.DataFrame(columns=["week", "transaction_id", "roster_id", "team_name", "player_added", "player_dropped", "waiver_bid", "status", "failure_reason"])
        manager_profiles = pd.DataFrame(
            [
                {"roster_id": 2, "team_name": "Melkor Lord of Light", "total_trades": 1, "future_1sts_acquired": 1, "future_1sts_sold": 0, "faab_spent_on_waivers": 0, "number_of_waiver_claims": 0},
                {"roster_id": 8, "team_name": "The Clapper", "total_trades": 1, "future_1sts_acquired": 0, "future_1sts_sold": 1, "faab_spent_on_waivers": 0, "number_of_waiver_claims": 0},
            ]
        )
        player_values = pd.DataFrame(
            [{"player_id": "2", "player_name": "Young WR", "market_value": 42, "source_trace": "test"}]
        )
        pick_values = pd.DataFrame(columns=["pick_season", "round", "market_value"])
        matchups = pd.DataFrame(
            [{"season": "2026", "week": 1, "matchup_id": "m1", "roster_id": 2, "team_name": "Melkor Lord of Light", "points_for": 110, "points_against": 100, "result": "win"}]
        )

        tables = build_economic_tables(
            teams,
            roster_players,
            pick_ownership,
            trades,
            waivers,
            manager_profiles,
            player_values,
            pick_values,
            {"current_team": {"roster_id": 2}, "strategy_profile": {"team_direction": "deep_rebuild"}},
            matchups,
        )

        self.assertIn("asset_market_gaps", tables)
        self.assertIn("manager_behavior_signals", tables)
        self.assertIn("manager_event_log", tables)
        self.assertIn("manager_valuation_profiles", tables)
        self.assertGreater(len(tables["asset_market_gaps"]), 0)
        self.assertGreater(len(tables["manager_valuation_profiles"]), 0)
        self.assertEqual(tables["manager_behavior_signals"].loc[tables["manager_behavior_signals"]["roster_id"] == 8, "plain_language_label"].iloc[0], "pick seller / win-now buyer")
        clapper_labels = set(tables["manager_valuation_profiles"].loc[tables["manager_valuation_profiles"]["roster_id"] == 8, "label"])
        self.assertTrue({"pick seller", "RB production buyer"}.intersection(clapper_labels))
        manager_history = tables["manager_season_history"]
        melkor_history = manager_history[manager_history["roster_id"] == 2].iloc[0]
        self.assertEqual(melkor_history["outcome_status"], "recorded")
        self.assertEqual(melkor_history["wins"], 1)

    def test_market_gap_ledger_keeps_no_team_rows_conditional_and_out_of_action_board(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "roster_id": 2,
                    "team_name": "My Team",
                    "asset_type": "player",
                    "asset_id": "free-agent-own",
                    "asset_name": "Free Agent Own",
                    "position": "RB",
                    "age": 29,
                    "current_availability_status": "no_current_nfl_team",
                    "availability_note": "No current NFL team in Sleeper; historical baseline is conditional on signing",
                    "market_value": 2,
                    "liquidity_tier": "thin",
                    "timeline_fit": "neutral_fit",
                    "source_trace": "market",
                },
                {
                    "roster_id": 8,
                    "team_name": "Rival",
                    "asset_type": "player",
                    "asset_id": "free-agent-rival",
                    "asset_name": "Free Agent Rival",
                    "position": "WR",
                    "age": 28,
                    "current_availability_status": "no_current_nfl_team",
                    "availability_note": "No current NFL team in Sleeper; historical baseline is conditional on signing",
                    "market_value": 3,
                    "liquidity_tier": "thin",
                    "timeline_fit": "neutral_fit",
                    "source_trace": "market",
                },
                {
                    "roster_id": 8,
                    "team_name": "Rival",
                    "asset_type": "player",
                    "asset_id": "active-rival",
                    "asset_name": "Active Rival",
                    "position": "WR",
                    "age": 24,
                    "current_availability_status": "available",
                    "availability_note": "No current Sleeper injury flag; baseline projection",
                    "market_value": 12,
                    "liquidity_tier": "medium",
                    "timeline_fit": "strong_rebuild_fit",
                    "source_trace": "market",
                },
            ]
        )
        needs = pd.DataFrame(
            [
                {"roster_id": 2, "team_shape": "rebuild_asset_bank", "need_rb": "high"},
                {"roster_id": 8, "team_shape": "contender_shape", "need_wr": "high"},
            ]
        )
        behavior = pd.DataFrame(
            [
                {"roster_id": 2, "trade_activity_score": 20, "plain_language_label": "patient builder"},
                {"roster_id": 8, "trade_activity_score": 40, "plain_language_label": "active trader"},
            ]
        )

        gaps = build_asset_market_gaps(inventory, needs, behavior, {"current_team": {"roster_id": 2}})
        by_name = {row["asset_name"]: row for _, row in gaps.iterrows()}
        self.assertEqual(by_name["Free Agent Own"]["opportunity_type"], "conditional_watch")
        self.assertEqual(by_name["Free Agent Rival"]["opportunity_type"], "conditional_target")
        self.assertEqual(by_name["Active Rival"]["opportunity_type"], "buy_low_target")
        self.assertEqual(by_name["Free Agent Rival"]["current_availability_status"], "no_current_nfl_team")

        board = build_opportunity_board(gaps, behavior, {"current_team": {"roster_id": 2}})
        self.assertNotIn("Free Agent Rival", set(board["asset_in"]))
        self.assertIn("Active Rival", set(board["asset_in"]))

    def _write_minimal_processed_tables(self, processed: Path) -> None:
        pd.DataFrame(
            [{"roster_id": 2, "display_name": "joe3489", "team_name": "Melkor Lord of Light"}]
        ).to_csv(processed / "teams.csv", index=False)
        pd.DataFrame(
            [
                {
                    "roster_id": 2,
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "nfl_team": "WAS",
                    "roster_status": "starter",
                    "age": 25,
                    "years_exp": 2,
                    "is_my_team": True,
                }
            ]
        ).to_csv(processed / "roster_players.csv", index=False)
        pd.DataFrame(
            [
                {
                    "owner_id": "u2",
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "seasons_covered": "2026",
                    "roster_ids_by_season": "2026:2",
                    "team_names_by_season": "2026:Melkor Lord of Light",
                    "total_trades": 0,
                    "future_1sts_acquired": 0,
                    "future_1sts_sold": 0,
                    "faab_spent_on_waivers": 0,
                    "number_of_waiver_claims": 0,
                    "contender_rebuilder_indicator": "neutral",
                }
            ]
        ).to_csv(processed / "manager_profiles.csv", index=False)
        pd.DataFrame(
            [
                {
                    "original_roster_id": 2,
                    "original_team": "Melkor Lord of Light",
                    "pick_season": "2027",
                    "round": 1,
                    "current_owner_roster_id": 8,
                    "current_owner": "The Clapper",
                    "previous_owner": "Melkor Lord of Light",
                    "is_my_original_pick": True,
                    "i_currently_own_it": False,
                }
            ]
        ).to_csv(processed / "pick_ownership.csv", index=False)
        pd.DataFrame(
            columns=[
                "week",
                "created_datetime",
                "team_a_roster_id",
                "team_a_name",
                "team_a_players_received",
                "team_a_picks_received",
                "team_a_faab_received",
                "team_b_roster_id",
                "team_b_name",
                "team_b_players_received",
                "team_b_picks_received",
                "team_b_faab_received",
            ]
        ).to_csv(processed / "trades.csv", index=False)
        pd.DataFrame(columns=["week", "roster_id", "team_name", "player_added", "player_dropped", "waiver_bid", "status", "failure_reason"]).to_csv(
            processed / "waivers.csv", index=False
        )
        pd.DataFrame(columns=["pick_no", "round", "roster_id", "player_name", "position", "nfl_team"]).to_csv(
            processed / "draft_picks.csv", index=False
        )
        pd.DataFrame(
            [{"player_id": "1", "full_name": "Jayden Daniels", "position": "QB", "team": "WAS"}]
        ).to_csv(processed / "players.csv", index=False)
        pd.DataFrame(
            [
                {
                    "generated_at": "2026-06-06T00:00:00+00:00",
                    "current_season": "2026",
                    "configured_league_ids": "league",
                    "configured_seasons": "2026",
                    "ingested_seasons": "2026",
                    "historical_league_ids_configured": 0,
                    "transaction_week_start": 1,
                    "transaction_week_end": 18,
                    "source_scope": "Sleeper public API only",
                    "raw_cache_root": "data/raw",
                    "raw_external_cache_root": "data/raw_external",
                    "browser_is_primary_surface": True,
                    "recommendation_packets_status": "planned_contract_only",
                    "analysis_artifacts_status": "missing",
                    "analysis_generated_at": "2026-06-06T00:00:00+00:00",
                    "analysis_context_packet_count": 0,
                    "target_thesis_count": 0,
                    "sell_thesis_count": 0,
                    "trade_thesis_count": 0,
                    "market_source_rows": 1,
                    "market_consensus_rows": 1,
                    "manager_valuation_profile_rows": 1,
                    "counterparty_edge_rows": 1,
                    "manager_profile_tag_rows": 1,
                    "player_profile_tag_rows": 1,
                    "player_dossier_rows": 1,
                }
            ]
        ).to_csv(processed / "refresh_metadata.csv", index=False)
        pd.DataFrame(columns=["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"]).to_csv(
            processed / "source_freshness.csv", index=False
        )
        pd.DataFrame(
            [
                {
                    "source": "sleeper_trending",
                    "event_id": "sleeper_trending_add_1",
                    "event_type": "trending_add",
                    "published_at": "2026-06-06T00:00:00+00:00",
                    "title": "Sleeper trending add: Jayden Daniels",
                    "summary": "Jayden Daniels is trending as an add with count 25.",
                    "url": "https://api.sleeper.app/v1/players/nfl/trending/add",
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "team": "WAS",
                    "position": "QB",
                    "source_trace": "https://api.sleeper.app/v1/players/nfl/trending/add",
                }
            ]
        ).to_csv(processed / "news_events.csv", index=False)
        pd.DataFrame(
            [
                {
                    "event_id": "sleeper_trending_add_1",
                    "source": "sleeper_trending",
                    "input_player_name": "Jayden Daniels",
                    "player_id": "1",
                    "matched_player_name": "Jayden Daniels",
                    "match_method": "sleeper_id",
                    "match_confidence": "high",
                    "is_ambiguous": False,
                    "source_trace": "https://api.sleeper.app/v1/players/nfl/trending/add",
                }
            ]
        ).to_csv(processed / "player_news_matches.csv", index=False)
        pd.DataFrame(
            [
                {
                    "event_id": "sleeper_trending_add_1",
                    "source": "sleeper_trending",
                    "published_at": "2026-06-06T00:00:00+00:00",
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "impact_type": "market_heat",
                    "evidence": "Sleeper trending add: Jayden Daniels",
                    "risk": "medium",
                    "confidence": "high",
                    "source_trace": "https://api.sleeper.app/v1/players/nfl/trending/add",
                }
            ]
        ).to_csv(processed / "league_news_impact.csv", index=False)
        pd.DataFrame(
            [{"source": "sleeper_trending", "dataset": "trending_add", "status": "cached", "source_url": "https://api.sleeper.app/v1/players/nfl/trending/add", "cache_path": "data/raw_external/sleeper/2026/trending_add.json", "checked_at": "2026-06-06T00:00:00+00:00", "row_count": 1}]
        ).to_csv(processed / "news_source_freshness.csv", index=False)
        pd.DataFrame(
            [
                {
                    "season": "2026",
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "team": "WAS",
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "projected_games": 17,
                    "projected_passing_yards": 3800,
                    "projected_passing_tds": 25,
                    "projected_interceptions": 8,
                    "projected_rushing_yards": 700,
                    "projected_rushing_tds": 6,
                    "projected_receptions": 0,
                    "projected_receiving_yards": 0,
                    "projected_receiving_tds": 0,
                    "projected_fantasy_points": 350,
                    "projected_ppg": 20.59,
                    "projection_method": "fixture",
                    "projection_confidence": "high",
                    "source_trace": "test",
                    "projection_note": "fixture projection",
                }
            ]
        ).to_csv(processed / "player_projection_season.csv", index=False)
        pd.DataFrame(
            [
                {
                    "season": "2026",
                    "week": 1,
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "team": "WAS",
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "projected_fantasy_points": 20.59,
                    "projected_snap_or_usage_note": "fixture",
                    "projection_method": "fixture",
                    "projection_confidence": "high",
                    "source_trace": "test",
                }
            ]
        ).to_csv(processed / "player_projection_weekly.csv", index=False)
        pd.DataFrame(
            [
                {
                    "source": "nflverse",
                    "dataset": "player_stats_projection_input",
                    "status": "cached",
                    "source_url": "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv",
                    "cache_path": "data/raw_external/nflverse/2026/player_stats.csv",
                    "checked_at": "2026-06-06T00:00:00+00:00",
                    "row_count": 1,
                }
            ]
        ).to_csv(processed / "projection_source_freshness.csv", index=False)
        pd.DataFrame(
            [
                {
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "age": 25,
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "projected_fantasy_points": 350,
                    "projected_ppg": 20.59,
                    "market_value": 53,
                    "projection_edge_score": 86,
                    "market_gap_score": 35,
                    "timeline_fit_score": 85,
                    "breakout_score": 70,
                    "sell_score": 0,
                    "signal_label": "breakout_target",
                    "evidence": "fixture signal",
                    "risk": "medium",
                    "confidence": "high",
                    "source_trace": "test",
                }
            ]
        ).to_csv(processed / "player_signal_scores.csv", index=False)
        pd.DataFrame(
            [{"player_id": "1", "player_name": "Jayden Daniels", "position": "QB", "current_team_name": "Melkor Lord of Light", "breakout_score": 70, "projection_edge": 86, "market_value": 53, "evidence": "fixture signal", "risk": "medium", "confidence": "high", "source_trace": "test"}]
        ).to_csv(processed / "breakout_candidates.csv", index=False)
        pd.DataFrame(
            [{"player_id": "2", "player_name": "Veteran RB", "position": "RB", "current_team_name": "Melkor Lord of Light", "sell_score": 55, "projection_risk": "medium", "market_value": 40, "evidence": "fixture signal", "risk": "medium", "confidence": "medium", "source_trace": "test"}]
        ).to_csv(processed / "sell_candidates.csv", index=False)
        pd.DataFrame(
            [{"player_id": "1", "player_name": "Jayden Daniels", "position": "QB", "projected_fantasy_points": 350, "projected_ppg": 20.59, "market_value": 53, "gap_score": 35, "gap_label": "projection_value_gap", "evidence": "fixture signal", "risk": "medium", "confidence": "high", "source_trace": "test"}]
        ).to_csv(processed / "projection_market_gaps.csv", index=False)
        pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB", "timeline_fit_score": 85, "need_fit_score": 55, "liquidity_fit_score": 53, "fit_label": "strong_fit", "evidence": "fixture signal", "risk": "medium", "confidence": "high", "source_trace": "test"}]
        ).to_csv(processed / "team_fit_scores.csv", index=False)
        pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "1", "player_name": "Jayden Daniels", "position": "QB", "age": 25, "action_label": "core_hold", "consumer_label": "Core Hold", "action_rank": 2, "action_score": 148, "projected_ppg": 20.59, "market_value": 53, "why": "Keep this player as a roster pillar unless another manager overpays.", "evidence": "fixture signal", "risk": "medium", "confidence": "high", "source_trace": "test"}]
        ).to_csv(processed / "action_recommendations.csv", index=False)
        pd.DataFrame(columns=["source", "season", "week", "player_id", "player_name", "position", "team", "targets", "carries", "receptions", "passing_attempts", "fantasy_points_ppr", "source_trace"]).to_csv(
            processed / "player_usage_weekly.csv", index=False
        )
        pd.DataFrame(
            [
                {
                    "source": "dynastyprocess",
                    "source_access_type": "open_dataset",
                    "source_player_id": "1",
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "raw_value": 5300,
                    "normalized_value": 53,
                    "market_rank": 1,
                    "value_format": "superflex_preferred",
                    "source_confidence": "high",
                    "source_trace": "https://github.com/DynastyProcess/data",
                    "checked_at": "2026-06-06T00:00:00+00:00",
                }
            ]
        ).to_csv(processed / "market_value_sources.csv", index=False)
        pd.DataFrame(
            [
                {
                    "player_id": "1",
                    "player_name": "Jayden Daniels",
                    "position": "QB",
                    "consensus_value": 53,
                    "source_count": 1,
                    "disagreement_score": 0,
                    "best_source": "dynastyprocess",
                    "confidence": "high",
                    "source_trace": "https://github.com/DynastyProcess/data",
                }
            ]
        ).to_csv(processed / "market_consensus_values.csv", index=False)
        pd.DataFrame(columns=["source", "source_player_id", "player_id", "player_name", "position", "market_value", "market_rank", "value_format", "source_trace"]).to_csv(
            processed / "player_market_values.csv", index=False
        )
        pd.DataFrame(columns=["source", "pick_label", "pick_season", "round", "market_value", "source_trace"]).to_csv(
            processed / "pick_market_values.csv", index=False
        )
        pd.DataFrame(
            [
                {
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
                    "asset_type": "player",
                    "asset_id": "1",
                    "asset_name": "Jayden Daniels",
                    "position": "QB",
                    "age": 25,
                    "market_value": 53,
                    "liquidity_tier": "high",
                    "timeline_fit": "core_or_rebuild_fit",
                    "source_trace": "internal_proxy_player_value",
                }
            ]
        ).to_csv(processed / "team_asset_inventory.csv", index=False)
        pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "trade_activity_score": 0, "pick_buyer_score": 0, "pick_seller_score": 0, "faab_aggression_score": 0, "waiver_activity_score": 0, "plain_language_label": "quiet market participant", "evidence": "test"}]
        ).to_csv(processed / "manager_behavior_signals.csv", index=False)
        pd.DataFrame(
            [{"owner_id": "u2", "roster_id": 2, "team_name": "Melkor Lord of Light", "asset_type": "pick", "position_group": "PICK", "preference_score": 20, "evidence_count": 1, "recency_weighted_score": 20, "confidence": "low", "label": "low-signal manager", "evidence": "test"}]
        ).to_csv(processed / "manager_valuation_profiles.csv", index=False)
        pd.DataFrame(columns=["season", "league_id", "owner_id", "event_type", "week", "created_datetime", "transaction_id", "roster_id", "team_name", "counterparty", "players_in", "picks_in", "faab_in", "players_out", "picks_out", "faab_out", "evidence"]).to_csv(
            processed / "manager_event_log.csv", index=False
        )
        pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "qb_count": 1, "rb_count": 0, "wr_count": 0, "te_count": 0, "pass_catcher_count": 0, "future_firsts_owned": 0, "need_qb": "high", "need_rb": "high", "need_pass_catcher": "high", "need_picks": "high", "team_shape": "balanced_or_unclear"}]
        ).to_csv(processed / "team_needs_matrix.csv", index=False)
        pd.DataFrame(
            [{"roster_id": 2, "team_name": "Melkor Lord of Light", "asset_type": "player", "asset_name": "Jayden Daniels", "position": "QB", "market_value": 53, "liquidity_score": 80, "liquidity_tier": "high", "demand_signal": 1, "source_trace": "internal_proxy_player_value"}]
        ).to_csv(processed / "liquidity_scores.csv", index=False)
        pd.DataFrame(
            [{"target_roster_id": 2, "target_team": "Melkor Lord of Light", "asset_type": "player", "asset_name": "Jayden Daniels", "position": "QB", "market_value": 53, "market_gap_score": 50, "opportunity_type": "sell_candidate", "timeline_fit": "core_or_rebuild_fit", "evidence": "test", "risk": "medium", "confidence": "medium", "source_trace": "internal_proxy_player_value"}]
        ).to_csv(processed / "asset_market_gaps.csv", index=False)
        pd.DataFrame(
            [{"action_type": "buy_low_target", "target_team": "The Clapper", "asset_in": "Young WR", "asset_out": "future offer packet only", "manager_signal": "pick seller / win-now buyer", "evidence": "test", "risk": "medium", "confidence": "medium", "source_trace": "test"}]
        ).to_csv(processed / "opportunity_board.csv", index=False)
        pd.DataFrame(
            [{"target_roster_id": 8, "target_team": "The Clapper", "player_id": "2", "player_name": "Young WR", "position": "WR", "our_value_score": 55, "market_consensus_value": 42, "estimated_owner_value_score": 30, "trade_edge_score": 25, "edge_type": "we_may_value_more", "evidence": "test", "risk": "medium", "confidence": "medium", "source_trace": "test"}]
        ).to_csv(processed / "counterparty_trade_edges.csv", index=False)
        pd.DataFrame(
            [{"entity_id": "2", "entity_name": "Melkor Lord of Light", "tag": "rebuilder", "score": 72, "confidence": "medium", "evidence": "test", "risk": "medium", "source_trace": "manager_profiles", "generated_at": "2026-06-06T00:00:00+00:00"}]
        ).to_csv(processed / "manager_profile_tags.csv", index=False)
        pd.DataFrame(
            [{"owner_id": "u2", "roster_id": 2, "team_name": "Melkor Lord of Light", "dynasty_cycle": "rebuild", "trade_temperature": "active trade market", "pick_posture": "pick accumulator", "waiver_posture": "quiet waiver market", "likely_needs": "RB; pass catcher", "likely_sells": "veteran RBs", "confidence": "medium", "evidence": "test"}]
        ).to_csv(processed / "manager_cycle_profiles.csv", index=False)
        pd.DataFrame(
            [{"player_id": "1", "player_name": "Jayden Daniels", "position": "QB", "age": 25, "roster_id": 2, "team_name": "Melkor Lord of Light", "roster_status": "starter", "market_value": 53, "projected_fantasy_points": 350, "projected_ppg": 20.59, "projection_confidence": "high", "signal_label": "breakout_target", "breakout_score": 70, "sell_score": 0, "news_impact": "role_or_value_change", "transaction_count": 1, "last_transaction": "draft_pick", "source_trace": "test"}]
        ).to_csv(processed / "player_dossiers.csv", index=False)
        pd.DataFrame(
            [{"player_id": "1", "identity_method": "source_id", "player_name": "Jayden Daniels", "event_type": "draft_pick", "season": 2026, "week": "", "created_datetime": "", "roster_id": 2, "team_name": "Melkor Lord of Light", "counterparty": "", "direction": "drafted pick 1", "evidence": "test", "source_trace": "draft_picks"}]
        ).to_csv(processed / "player_transaction_history.csv", index=False)
        pd.DataFrame(
            [{"entity_id": "1", "entity_name": "Jayden Daniels", "tag": "franchise cornerstone", "score": 85, "confidence": "high", "evidence": "test", "risk": "medium", "source_trace": "player_dossiers", "generated_at": "2026-06-06T00:00:00+00:00"}]
        ).to_csv(processed / "player_profile_tags.csv", index=False)

    def test_manager_behavior_scores_differentiate_by_activity(self) -> None:
        teams = pd.DataFrame(
            [
                {"season": "2026", "roster_id": 1, "team_name": "Very Active"},
                {"season": "2026", "roster_id": 2, "team_name": "Barely Active"},
            ]
        )
        manager_profiles = pd.DataFrame(
            [
                {"roster_id": 1, "total_trades": 46, "future_1sts_acquired": 1, "future_1sts_sold": 7, "faab_spent_on_waivers": 234, "number_of_waiver_claims": 36},
                {"roster_id": 2, "total_trades": 1, "future_1sts_acquired": 0, "future_1sts_sold": 0, "faab_spent_on_waivers": 5, "number_of_waiver_claims": 1},
            ]
        )
        roster_players = pd.DataFrame(columns=["roster_id", "position", "season"])

        result = build_manager_behavior_signals(teams, pd.DataFrame(), pd.DataFrame(), manager_profiles, roster_players)

        active = result[result["roster_id"] == 1].iloc[0]
        quiet = result[result["roster_id"] == 2].iloc[0]
        self.assertGreater(active["trade_activity_score"], quiet["trade_activity_score"])
        self.assertGreater(active["faab_aggression_score"], quiet["faab_aggression_score"])
        # Neither manager should be pinned to the old hard-cap value of 100 --
        # that was the saturation bug (any manager with >=6 trades used to cap
        # identically regardless of how much more active they actually were).
        self.assertLess(quiet["trade_activity_score"], 100)

    def test_action_reasoning_varies_by_player_magnitude(self) -> None:
        strong = pd.Series(
            {"roster_id": 8, "position": "WR", "age": 22, "projected_ppg": 18.0, "market_value": 500, "market_gap_score": 80, "breakout_score": 90, "sell_score": 0, "timeline_fit_score": 70, "confidence": "high"}
        )
        marginal = pd.Series(
            {"roster_id": 9, "position": "WR", "age": 25, "projected_ppg": 8.5, "market_value": 200, "market_gap_score": 31, "breakout_score": 40, "sell_score": 0, "timeline_fit_score": 50, "confidence": "medium"}
        )

        strong_action = _classify_action(strong, current_roster=2)
        marginal_action = _classify_action(marginal, current_roster=2)

        self.assertEqual(strong_action["action_label"], "true_buy_low")
        self.assertEqual(marginal_action["action_label"], "true_buy_low")
        self.assertNotEqual(strong_action["why"], marginal_action["why"])
        self.assertIn("80", strong_action["why"])
        self.assertIn("31", marginal_action["why"])

    def test_priority_board_deduplicates_by_entity(self) -> None:
        actions = pd.DataFrame(
            [{"roster_id": 8, "team_name": "The Clapper", "player_id": "1", "player_name": "Dup Player", "position": "WR", "action_label": "true_buy_low", "consumer_label": "True Buy Low", "action_rank": 1, "action_score": 90, "projected_ppg": 15, "market_value": 40, "why": "action reason", "evidence": "e", "risk": "medium", "confidence": "high", "source_trace": "t"}]
        )
        news = pd.DataFrame(
            [{"event_id": "n1", "source": "sleeper", "published_at": "2026-06-01", "player_id": "1", "player_name": "Dup Player", "roster_id": 8, "team_name": "The Clapper", "impact_type": "market_heat", "evidence": "news evidence", "risk": "low", "confidence": "high", "source_trace": "t"}]
        )
        picks = pd.DataFrame(columns=["is_my_original_pick", "i_currently_own_it", "pick_season", "round", "original_roster_id", "current_owner_roster_id", "current_owner", "original_team", "previous_owner"])
        managers = pd.DataFrame(columns=["roster_id", "team_name", "trade_activity_score", "plain_language_label", "evidence"])
        config = {"current_team": {"roster_id": 2}}

        board = build_today_priority_board(actions, news, picks, managers, config)

        dup_rows = board[(board["entity_type"] == "player") & (board["entity_id"] == "1")]
        self.assertEqual(len(dup_rows), 1)
        # The higher-signal source (action_recommendations) should win the collision.
        self.assertEqual(dup_rows.iloc[0]["why"], "action reason")

    def test_priority_board_ranks_higher_priority_first(self) -> None:
        actions = pd.DataFrame(
            [
                {"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "1", "player_name": "High Priority", "position": "RB", "action_label": "sell_window", "consumer_label": "Sell Window", "action_rank": 1, "action_score": 95, "projected_ppg": 10, "market_value": 30, "why": "high", "evidence": "e", "risk": "medium", "confidence": "high", "source_trace": "t"},
                {"roster_id": 2, "team_name": "Melkor Lord of Light", "player_id": "2", "player_name": "Low Priority", "position": "RB", "action_label": "monitor", "consumer_label": "Monitor", "action_rank": 5, "action_score": 5, "projected_ppg": 4, "market_value": 5, "why": "low", "evidence": "e", "risk": "low", "confidence": "low", "source_trace": "t"},
            ]
        )
        empty_news = pd.DataFrame(columns=["event_id", "source", "published_at", "player_id", "player_name", "roster_id", "team_name", "impact_type", "evidence", "risk", "confidence", "source_trace"])
        empty_picks = pd.DataFrame(columns=["is_my_original_pick", "i_currently_own_it", "pick_season", "round", "original_roster_id", "current_owner_roster_id", "current_owner", "original_team", "previous_owner"])
        empty_managers = pd.DataFrame(columns=["roster_id", "team_name", "trade_activity_score", "plain_language_label", "evidence"])
        config = {"current_team": {"roster_id": 2}}

        board = build_today_priority_board(actions, empty_news, empty_picks, empty_managers, config)

        self.assertEqual(board.iloc[0]["entity_name"], "High Priority")
        self.assertGreater(board.iloc[0]["priority_score"], board.iloc[-1]["priority_score"])

    def test_priority_board_alerts_preserve_risk_context(self) -> None:
        actions = pd.DataFrame(
            columns=[
                "roster_id", "team_name", "player_id", "player_name", "position", "action_label",
                "consumer_label", "action_rank", "action_score", "projected_ppg", "market_value",
                "why", "evidence", "risk", "confidence", "source_trace",
            ]
        )
        news = pd.DataFrame()
        picks = pd.DataFrame(
            [
                {
                    "is_my_original_pick": True,
                    "i_currently_own_it": False,
                    "pick_season": 2027,
                    "round": 1,
                    "original_roster_id": 2,
                    "current_owner_roster_id": 8,
                    "current_owner": "The Clapper",
                    "original_team": "Melkor Lord of Light",
                }
            ]
        )
        managers = pd.DataFrame(
            [{"roster_id": 8, "team_name": "The Clapper", "trade_activity_score": 90, "plain_language_label": "active trader", "evidence": "trades=12"}]
        )

        board = build_today_priority_board(actions, news, picks, managers, {"current_team": {"roster_id": 2}})

        self.assertEqual(set(board["item_type"]), {"pick_alert", "manager_angle"})
        self.assertTrue(board["risk"].astype(str).str.strip().ne("").all())
        self.assertIn("under your control", board.iloc[0]["risk"] + board.iloc[1]["risk"])
        self.assertIn("estimate", " ".join(board["risk"].tolist()).lower())

    def test_opportunity_scores_rank_usage_within_position(self) -> None:
        # Two WRs across three weeks: one commands the targets, one barely plays. Opportunity is
        # percentile-ranked within position, so the high-usage WR must score materially higher.
        weeks = []
        for week in (1, 2, 3):
            weeks.append({"player_id": "nfl_hi", "player_display_name": "Alpha Receiver", "player_name": "Alpha Receiver", "position": "WR", "season": 2026, "week": week, "season_type": "REG", "attempts": 0, "carries": 0, "targets": 11, "receptions": 8, "target_share": 0.32, "air_yards_share": 0.40, "wopr": 0.75, "fantasy_points": 18, "fantasy_points_ppr": 26})
            weeks.append({"player_id": "nfl_lo", "player_display_name": "Backup Receiver", "player_name": "Backup Receiver", "position": "WR", "season": 2026, "week": week, "season_type": "REG", "attempts": 0, "carries": 0, "targets": 2, "receptions": 1, "target_share": 0.05, "air_yards_share": 0.06, "wopr": 0.10, "fantasy_points": 3, "fantasy_points_ppr": 4})
        weekly = pd.DataFrame(weeks)
        roster = pd.DataFrame(
            [
                {"player_id": "10", "player_name": "Alpha Receiver", "position": "WR", "roster_id": 2, "team_name": "Melkor Lord of Light", "age": 25},
                {"player_id": "20", "player_name": "Backup Receiver", "position": "WR", "roster_id": 3, "team_name": "The Clapper", "age": 27},
            ]
        )
        scores = build_opportunity_scores(weekly, roster, {"current_season": 2026})
        self.assertEqual(set(scores["player_id"]), {"10", "20"})  # carries the Sleeper roster id, not the nflverse id
        by_name = {row["player_name"]: row for _, row in scores.iterrows()}
        self.assertGreater(by_name["Alpha Receiver"]["opportunity_score"], by_name["Backup Receiver"]["opportunity_score"])
        for _, row in scores.iterrows():
            self.assertGreaterEqual(row["opportunity_score"], 0.0)
            self.assertLessEqual(row["opportunity_score"], 100.0)

    def test_opportunity_scores_scope_current_league_before_name_join(self) -> None:
        """Design source: AGENTS.md; league identity precedes mutable team presentation."""
        weekly = pd.DataFrame([
            {
                "player_id": "nfl-shared",
                "player_display_name": "Shared Receiver",
                "player_name": "Shared Receiver",
                "position": "WR",
                "season": 2026,
                "week": 1,
                "season_type": "REG",
                "attempts": 0,
                "carries": 0,
                "targets": 8,
                "receptions": 6,
                "target_share": 0.25,
                "air_yards_share": 0.30,
                "wopr": 0.50,
                "fantasy_points": 12,
                "fantasy_points_ppr": 18,
            }
        ])
        roster = pd.DataFrame([
            {
                "season": 2025,
                "league_id": "league-1",
                "roster_id": 2,
                "player_id": "shared-sleeper-id",
                "player_name": "Shared Receiver",
                "position": "WR",
                "team_name": "Historical Team",
            },
            {
                "season": 2026,
                "league_id": "league-2",
                "roster_id": 4,
                "player_id": "shared-sleeper-id",
                "player_name": "Shared Receiver",
                "position": "WR",
                "team_name": "Moose Caboose",
            },
            {
                "season": 2026,
                "league_id": "league-1",
                "roster_id": 7,
                "player_id": "shared-sleeper-id",
                "player_name": "Shared Receiver",
                "position": "WR",
                "team_name": "Lulu's Potatoe's",
            },
        ])

        scores = build_opportunity_scores(
            weekly,
            roster,
            {"current_season": 2026, "league_id": "league-1"},
        )

        self.assertEqual(len(scores), 1)
        self.assertEqual(scores.iloc[0]["league_id"], "league-1")
        self.assertEqual(int(scores.iloc[0]["roster_id"]), 7)
        self.assertEqual(scores.iloc[0]["team_name"], "Lulu's Potatoe's")

    def test_breakout_score_lifts_with_opportunity(self) -> None:
        # The Sprint 18 blend: identical player, higher opportunity must not lower the breakout score.
        low = _breakout_score("WR", 24, 12.0, 40.0, "high", "", opportunity_score=20.0)
        high = _breakout_score("WR", 24, 12.0, 40.0, "high", "", opportunity_score=90.0)
        self.assertGreater(high, low)

    # --- Sprint 19: manager data correctness + cross-article dedup -----------------------

    def test_trade_theses_only_name_assets_owned_by_target_manager(self) -> None:
        # The old round-robin paired managers with arbitrary opportunity rows, attributing
        # players to managers who don't roster them. Theses must use the real target_team link.
        from src.analysis import build_trade_theses

        dataframes = {
            "manager_behavior_signals": pd.DataFrame(
                [
                    {"roster_id": 3, "team_name": "The Clapper", "plain_language_label": "pick buyer", "evidence": "e3"},
                    {"roster_id": 4, "team_name": "Moose Caboose", "plain_language_label": "waiver aggressive", "evidence": "e4"},
                    {"roster_id": 5, "team_name": "Quiet Team", "plain_language_label": "low activity", "evidence": "e5"},
                ]
            ),
            "opportunity_board": pd.DataFrame(
                [
                    {"action_type": "buy_low_target", "target_team": "The Clapper", "asset_in": "Clapper Player", "evidence": "oe1", "risk": "medium", "confidence": "high", "source_trace": "t"},
                    {"action_type": "buy_low_target", "target_team": "Moose Caboose", "asset_in": "Moose Player", "evidence": "oe2", "risk": "medium", "confidence": "high", "source_trace": "t"},
                ]
            ),
        }
        theses = build_trade_theses(dataframes, 2, "Melkor Lord of Light", "2026-01-01T00:00:00+00:00")
        by_manager = {thesis["target_manager_name"]: thesis for thesis in theses}
        self.assertIn("Clapper Player", by_manager["The Clapper"]["assets_to_discuss"])
        self.assertIn("Moose Player", by_manager["Moose Caboose"]["assets_to_discuss"])
        self.assertNotIn("Clapper Player", by_manager["Moose Caboose"]["assets_to_discuss"])
        # A manager with no matched opportunity gets a tendency-based angle, never someone else's player.
        self.assertNotIn("Player", by_manager["Quiet Team"]["assets_to_discuss"])
        self.assertIn("plausible_offer_range", by_manager["The Clapper"])
        self.assertIn("historical_evidence", by_manager["The Clapper"])
        self.assertIn("do_not_chase_conditions", by_manager["The Clapper"])

    def test_trade_offer_candidates_follow_observed_counterparty_lanes(self) -> None:
        """The Front Office realization epic requires offer fit to stay evidence-bound.

        The Trade Desk may rank assets from our exact roster against a target
        manager's observed valuation lanes, but it must label that shortlist as
        a conversation aid rather than a predicted response or generated offer.
        """
        from src.analysis import build_trade_theses

        dataframes = {
            "manager_behavior_signals": pd.DataFrame(
                [{"roster_id": 4, "team_name": "Moose Caboose", "plain_language_label": "pick buyer", "evidence": "behavior-4"}]
            ),
            "team_asset_inventory": pd.DataFrame(
                [
                    {"roster_id": 2, "asset_type": "player", "asset_id": "wr-1", "asset_name": "My Wideout", "position": "WR", "market_value": 60, "liquidity_tier": "high", "timeline_fit": "now", "source_trace": "inventory"},
                    {"roster_id": 2, "asset_type": "player", "asset_id": "rb-1", "asset_name": "My Runner", "position": "RB", "market_value": 100, "liquidity_tier": "medium", "timeline_fit": "now", "source_trace": "inventory"},
                    {"roster_id": 4, "asset_type": "player", "asset_id": "wrong-1", "asset_name": "Opponent Player", "position": "WR", "market_value": 200, "source_trace": "inventory"},
                ]
            ),
            "manager_valuation_profiles": pd.DataFrame(
                [
                    {"roster_id": 4, "position_group": "PASS_CATCHER", "preference_score": 0.90, "evidence_count": 5, "confidence": "high", "label": "pass-catcher accumulator"},
                    {"roster_id": 4, "position_group": "RB", "preference_score": 0.20, "evidence_count": 2, "confidence": "low", "label": "low RB lane"},
                ]
            ),
            "counterparty_asset_interest": pd.DataFrame(
                [{
                    "target_roster_id": 4,
                    "asset_id": "wr-1",
                    "asset_name": "My Wideout",
                    "position": "WR",
                    "market_value": 60,
                    "conversation_fit_score": 78,
                    "conversation_fit_label": "strong_conversation_fit",
                    "transaction_lane_read": "observed acquisition lane",
                    "target_need": "high",
                    "target_need_fit_score": 82,
                    "target_horizon_fit_score": 75,
                    "active_horizon_fit_score": 60,
                    "horizon_fit_edge": 15,
                    "horizon_fit_read": "target_team_timeline_premium",
                    "confidence": "high",
                    "evidence": "interest evidence",
                    "risk": "not intent",
                    "source_trace": "counterparty_asset_interest",
                }]
            ),
        }

        theses = build_trade_theses(dataframes, 2, "Lulu's Potatoes", "2026-01-01T00:00:00+00:00")
        thesis = theses[0]
        self.assertEqual(thesis["offer_candidates"][0]["asset_name"], "My Wideout")
        self.assertEqual(thesis["offer_candidates"][0]["manager_preference_evidence_count"], 5)
        self.assertNotIn("Opponent Player", thesis["assets_we_can_offer"])
        self.assertEqual(thesis["assets_target_may_value"][0]["asset_name"], "My Wideout")
        self.assertEqual(thesis["counterparty_interest_status"], "supported")
        self.assertIn("counterparty_asset_interest", thesis["source_trace"])
        self.assertTrue(thesis["historical_evidence"]["valuation_lanes"])
        self.assertIn("observed valuation lane", " ".join(thesis["do_not_chase_conditions"]))

    def test_dynasty_cycles_differentiate_by_future_pick_capital(self) -> None:
        # 11/12 managers classified "rebuild" in production because all-time pick counts tripped
        # an absolute threshold. Future-firsts + league-relative classification must produce a mix.
        from src.profile_intelligence import build_manager_cycle_profiles

        profiles = pd.DataFrame(
            [
                {"owner_id": "a", "roster_id": 1, "team_name": "Hoarder", "seasons_covered": "2021-2026", "total_trades": 30, "number_of_waiver_claims": 40, "faab_spent_on_waivers": 200, "future_1sts_acquired": 12, "future_1sts_sold": 2, "rb_count": 6, "pass_catcher_count": 14},
                {"owner_id": "b", "roster_id": 2, "team_name": "Spender", "seasons_covered": "2021-2026", "total_trades": 28, "number_of_waiver_claims": 35, "faab_spent_on_waivers": 180, "future_1sts_acquired": 1, "future_1sts_sold": 9, "rb_count": 10, "pass_catcher_count": 18},
                {"owner_id": "c", "roster_id": 3, "team_name": "Middle", "seasons_covered": "2021-2026", "total_trades": 5, "number_of_waiver_claims": 10, "faab_spent_on_waivers": 40, "future_1sts_acquired": 3, "future_1sts_sold": 3, "rb_count": 8, "pass_catcher_count": 16},
            ]
        )
        picks = pd.DataFrame(
            # Hoarder owns 5 future firsts, Spender none, Middle one; plus stale past-season picks
            # for everyone that must NOT count.
            [{"round": 1, "pick_season": 2027, "current_owner_roster_id": 1}] * 5
            + [{"round": 1, "pick_season": 2027, "current_owner_roster_id": 3}]
            + [{"round": 1, "pick_season": 2022, "current_owner_roster_id": 2}] * 6
        )
        cycles = build_manager_cycle_profiles(profiles, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), picks, None, 2026)
        by_team = {row["team_name"]: row["dynasty_cycle"] for _, row in cycles.iterrows()}
        self.assertEqual(by_team["Hoarder"], "rebuild")
        self.assertEqual(by_team["Spender"], "contender")
        self.assertEqual(len(set(by_team.values())) > 1, True)

    def test_likely_sells_names_actual_roster_veterans(self) -> None:
        from src.profile_intelligence import build_manager_cycle_profiles

        profiles = pd.DataFrame(
            [
                {"owner_id": "a", "roster_id": 1, "team_name": "Hoarder", "seasons_covered": "2021-2026", "total_trades": 30, "number_of_waiver_claims": 40, "faab_spent_on_waivers": 200, "future_1sts_acquired": 12, "future_1sts_sold": 2, "rb_count": 6, "pass_catcher_count": 14},
                {"owner_id": "b", "roster_id": 2, "team_name": "Spender", "seasons_covered": "2021-2026", "total_trades": 28, "number_of_waiver_claims": 35, "faab_spent_on_waivers": 180, "future_1sts_acquired": 1, "future_1sts_sold": 9, "rb_count": 10, "pass_catcher_count": 18},
            ]
        )
        picks = pd.DataFrame([{"round": 1, "pick_season": 2027, "current_owner_roster_id": 1}] * 4)
        dossiers = pd.DataFrame(
            [
                {"player_id": "9", "player_name": "Old Star", "position": "RB", "age": 30, "roster_id": 1, "market_value": 60},
                {"player_id": "10", "player_name": "Young Gun", "position": "WR", "age": 23, "roster_id": 1, "market_value": 80},
            ]
        )
        cycles = build_manager_cycle_profiles(profiles, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), picks, dossiers, 2026)
        hoarder = cycles[cycles.team_name == "Hoarder"].iloc[0]
        self.assertEqual(hoarder["dynasty_cycle"], "rebuild")
        self.assertIn("Old Star", hoarder["likely_sells"])  # the actual veteran, by name
        self.assertNotIn("Young Gun", hoarder["likely_sells"])  # the 23-year-old is not a sell

    def test_articles_dedup_claims_players_across_scopes(self) -> None:
        from src import articles

        ctx = articles.ArticleContext(analysis_dir=Path("."), active_roster_id=2)
        first = [
            {"evidence_id": "player:1:1", "entity_type": "player", "entity_id": "1", "name": "Shared Star", "text": "t", "source_trace": "source:shared"},
            {"evidence_id": "player:2:2", "entity_type": "player", "entity_id": "2", "name": "Only First", "text": "t"},
        ]
        second = [
            {"evidence_id": "player:1:9", "entity_type": "player", "entity_id": "1", "name": "Shared Star", "text": "t"},
            {"evidence_id": "player:3:3", "entity_type": "player", "entity_id": "3", "name": "Only Second", "text": "t"},
            {"evidence_id": "manager:4:4", "entity_type": "manager", "entity_id": "4", "name": "Some Manager", "text": "t"},
        ]
        kept_first = articles.apply_entity_dedup(ctx, first)
        kept_second = articles.apply_entity_dedup(ctx, second)
        self.assertEqual(len(kept_first), 2)
        second_players = [row["name"] for row in kept_second if row.get("entity_type") == "player"]
        self.assertEqual(second_players, ["Only Second"])  # Shared Star dropped
        self.assertTrue(any(row.get("entity_type") == "manager" for row in kept_second))  # managers untouched
        covered = [row for row in kept_second if row.get("entity_type") == "context"]
        self.assertEqual(len(covered), 1)
        self.assertIn("Shared Star", covered[0]["text"])
        self.assertEqual(covered[0]["source_ids"], ["source:shared"])


if __name__ == "__main__":
    unittest.main()
