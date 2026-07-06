from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from src import operator
from src.analysis import build_analysis_artifacts
from src.browser_site import build_browser_site
from src.economics import build_economic_tables, build_manager_behavior_signals
from src.external_sources import build_market_consensus_values, refresh_external_sources
from src.news import build_news_tables
from src.normalize import build_roster_maps, normalize_traded_picks
from src.pick_ownership import build_pick_ownership
from src.players import players_table
from src.priority_board import build_today_priority_board
from src.profile_intelligence import build_profile_intelligence_tables
from src.projection_accuracy import append_projection_accuracy_snapshot, build_projection_accuracy_table
from src.projections import _blend_projection_components, _build_projection_consensus, build_projection_tables, calculate_fantasy_points
from src.opportunity import build_opportunity_scores, score_players_from_weekly
from src.signals import _breakout_score, _classify_action, build_signal_tables
from scripts.refresh_all import _discover_league_history
from scripts.serve import RailwayHTTPRequestHandler
from scripts.start import write_boot_page


EXPECTED_TABLE_COLUMNS = {
    "leagues": ["season", "league_id", "name", "status", "scoring_settings", "roster_positions", "playoff_week_start", "settings"],
    "teams": ["season", "league_id", "roster_id", "owner_id", "display_name", "team_name", "waiver_position", "waiver_budget_used", "total_moves"],
    "players": ["player_id", "full_name", "position", "team", "age", "years_exp", "fantasy_positions", "status"],
    "roster_players": ["season", "league_id", "roster_id", "owner_id", "player_id", "player_name", "position", "nfl_team", "age", "years_exp", "roster_status", "is_my_team", "team_name"],
    "drafts": ["season", "league_id", "draft_id", "status", "type", "settings"],
    "draft_picks": ["season", "league_id", "draft_id", "pick_no", "round", "roster_id", "picked_by", "player_id", "player_name", "position", "nfl_team"],
    "traded_picks": ["season", "league_id", "original_roster_id", "original_team_name", "round", "pick_season", "current_owner_roster_id", "current_owner_team_name", "previous_owner_roster_id", "previous_owner_team_name", "is_my_original_pick", "is_currently_owned_by_me"],
    "transactions_raw": ["season", "league_id", "week", "transaction_id", "type", "status", "created", "raw"],
    "transactions_normalized": ["season", "league_id", "week", "transaction_id", "type", "status", "created_datetime", "roster_ids_involved", "manager_team_names_involved", "adds", "drops", "draft_picks_moved", "waiver_bid", "faab_moved", "failure_reason"],
    "trades": ["season", "league_id", "week", "transaction_id", "created_datetime", "team_a_roster_id", "team_a_name", "team_a_players_received", "team_a_picks_received", "team_a_faab_received", "team_b_roster_id", "team_b_name", "team_b_players_received", "team_b_picks_received", "team_b_faab_received", "raw"],
    "waivers": ["season", "league_id", "week", "transaction_id", "roster_id", "team_name", "player_added", "player_dropped", "waiver_bid", "status", "failure_reason"],
    "player_usage_weekly": ["source", "season", "week", "player_id", "player_name", "position", "team", "targets", "carries", "receptions", "passing_attempts", "fantasy_points_ppr", "source_trace"],
    "market_value_sources": ["source", "source_access_type", "source_player_id", "player_id", "player_name", "position", "raw_value", "normalized_value", "market_rank", "value_format", "source_confidence", "source_trace", "checked_at"],
    "market_consensus_values": ["player_id", "player_name", "position", "consensus_value", "source_count", "disagreement_score", "best_source", "confidence", "source_trace"],
    "player_market_values": ["source", "source_player_id", "player_id", "player_name", "position", "market_value", "market_rank", "value_format", "source_trace"],
    "pick_market_values": ["source", "pick_label", "pick_season", "round", "market_value", "source_trace"],
    "source_freshness": ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"],
    "news_events": ["source", "event_id", "event_type", "published_at", "title", "summary", "url", "player_id", "player_name", "team", "position", "source_trace"],
    "player_news_matches": ["event_id", "source", "input_player_name", "player_id", "matched_player_name", "match_method", "match_confidence", "is_ambiguous", "source_trace"],
    "league_news_impact": ["event_id", "source", "published_at", "player_id", "player_name", "roster_id", "team_name", "impact_type", "evidence", "risk", "confidence", "source_trace"],
    "news_source_freshness": ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"],
    "player_projection_season": ["season", "player_id", "player_name", "position", "team", "roster_id", "team_name", "projected_games", "projected_passing_yards", "projected_passing_tds", "projected_interceptions", "projected_rushing_yards", "projected_rushing_tds", "projected_receptions", "projected_receiving_yards", "projected_receiving_tds", "projected_fantasy_points", "projected_ppg", "projection_method", "projection_confidence", "source_trace", "projection_note"],
    "player_projection_weekly": ["season", "week", "player_id", "player_name", "position", "team", "roster_id", "team_name", "projected_fantasy_points", "projected_snap_or_usage_note", "projection_method", "projection_confidence", "source_trace"],
    "projection_source_freshness": ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"],
    "fantasy_nerds_projection_source": ["source", "fn_player_id", "player_name", "normalized_name", "position", "team", "projected_fantasy_points", "source_confidence", "source_trace", "checked_at"],
    "projection_source_components": ["season", "player_id", "player_name", "position", "team", "roster_id", "team_name", "source", "projected_fantasy_points", "projected_ppg", "projected_games", "source_confidence", "source_trace", "projection_method", "detail_stats_json", "checked_at"],
    "source_accuracy_scores": ["source", "position", "season", "mean_absolute_error", "sample_size", "accuracy_confidence", "source_trace", "checked_at"],
    "today_priority_board": ["item_type", "item_type_label", "entity_type", "entity_id", "entity_name", "roster_id", "team_name", "priority_score", "why", "evidence", "risk", "confidence", "source_trace"],
    "player_signal_scores": ["player_id", "player_name", "position", "roster_id", "team_name", "projection_edge_score", "market_gap_score", "timeline_fit_score", "breakout_score", "sell_score", "opportunity_score", "xfp_regression_score", "role_trend_score", "fragility_score", "signal_label", "evidence", "risk", "confidence", "source_trace"],
    "player_opportunity_scores": ["player_id", "player_name", "position", "roster_id", "team_name", "games_sample", "opportunity_score", "production_score", "xfp_regression_score", "role_trend_score", "fragility_score", "opportunity_evidence", "source_trace"],
    "breakout_candidates": ["player_id", "player_name", "position", "current_team_name", "breakout_score", "projection_edge", "market_value", "evidence", "risk", "confidence", "source_trace"],
    "sell_candidates": ["player_id", "player_name", "position", "current_team_name", "sell_score", "projection_risk", "market_value", "evidence", "risk", "confidence", "source_trace"],
    "projection_market_gaps": ["player_id", "player_name", "position", "projected_fantasy_points", "projected_ppg", "market_value", "gap_score", "gap_label", "evidence", "risk", "confidence", "source_trace"],
    "team_fit_scores": ["roster_id", "team_name", "player_id", "player_name", "position", "timeline_fit_score", "need_fit_score", "liquidity_fit_score", "fit_label", "evidence", "risk", "confidence", "source_trace"],
    "action_recommendations": ["roster_id", "team_name", "player_id", "player_name", "position", "action_label", "consumer_label", "action_rank", "action_score", "projected_ppg", "market_value", "why", "evidence", "risk", "confidence", "source_trace"],
    "manager_profiles": ["owner_id", "roster_id", "display_name", "team_name", "seasons_covered", "roster_ids_by_season", "team_names_by_season", "total_trades", "trades_by_season", "players_acquired", "players_sold", "picks_acquired", "picks_sold", "future_1sts_acquired", "future_1sts_sold", "future_2nds_acquired", "future_2nds_sold", "faab_spent_on_waivers", "number_of_waiver_claims", "average_waiver_bid", "max_waiver_bid", "most_common_transaction_partners", "qb_count", "rb_count", "pass_catcher_count", "contender_rebuilder_indicator", "notes"],
    "pick_ownership": ["original_roster_id", "original_team", "pick_season", "round", "current_owner_roster_id", "current_owner", "previous_owner_roster_id", "previous_owner", "is_my_original_pick", "is_currently_owned_by_me", "i_currently_own_it"],
    "team_asset_inventory": ["roster_id", "team_name", "asset_type", "asset_id", "asset_name", "position", "age", "market_value", "liquidity_tier", "timeline_fit", "source_trace"],
    "manager_event_log": ["event_type", "week", "created_datetime", "transaction_id", "roster_id", "team_name", "counterparty", "players_in", "picks_in", "faab_in", "players_out", "picks_out", "faab_out", "evidence"],
    "team_needs_matrix": ["roster_id", "team_name", "qb_count", "rb_count", "wr_count", "te_count", "pass_catcher_count", "future_firsts_owned", "need_qb", "need_rb", "need_pass_catcher", "need_picks", "team_shape"],
    "manager_behavior_signals": ["roster_id", "team_name", "trade_activity_score", "pick_buyer_score", "pick_seller_score", "faab_aggression_score", "waiver_activity_score", "rb_appetite_score", "pass_catcher_appetite_score", "plain_language_label", "evidence"],
    "manager_valuation_profiles": ["owner_id", "roster_id", "team_name", "asset_type", "position_group", "preference_score", "evidence_count", "recency_weighted_score", "confidence", "label", "evidence"],
    "liquidity_scores": ["roster_id", "team_name", "asset_type", "asset_name", "position", "market_value", "liquidity_score", "liquidity_tier", "demand_signal", "source_trace"],
    "asset_market_gaps": ["target_roster_id", "target_team", "asset_type", "asset_name", "position", "market_value", "market_gap_score", "opportunity_type", "timeline_fit", "evidence", "risk", "confidence", "source_trace"],
    "opportunity_board": ["action_type", "target_team", "asset_in", "asset_out", "manager_signal", "evidence", "risk", "confidence", "source_trace"],
    "counterparty_trade_edges": ["target_roster_id", "target_team", "player_id", "player_name", "position", "our_value_score", "market_consensus_value", "estimated_owner_value_score", "trade_edge_score", "edge_type", "evidence", "risk", "confidence", "source_trace"],
    "manager_profile_tags": ["entity_id", "entity_name", "tag", "score", "confidence", "evidence", "risk", "source_trace", "generated_at"],
    "manager_cycle_profiles": ["owner_id", "roster_id", "team_name", "dynasty_cycle", "trade_temperature", "pick_posture", "waiver_posture", "likely_needs", "likely_sells", "confidence", "evidence"],
    "player_dossiers": ["player_id", "player_name", "position", "age", "roster_id", "team_name", "roster_status", "market_value", "projected_fantasy_points", "projected_ppg", "projection_confidence", "signal_label", "breakout_score", "sell_score", "news_impact", "transaction_count", "last_transaction", "source_trace"],
    "player_transaction_history": ["player_id", "player_name", "event_type", "season", "week", "created_datetime", "roster_id", "team_name", "counterparty", "direction", "evidence", "source_trace"],
    "player_profile_tags": ["entity_id", "entity_name", "tag", "score", "confidence", "evidence", "risk", "source_trace", "generated_at"],
    "refresh_metadata": ["generated_at", "current_season", "configured_league_ids", "configured_seasons", "ingested_seasons", "historical_league_ids_configured", "transaction_week_start", "transaction_week_end", "source_scope", "raw_cache_root", "raw_external_cache_root", "browser_is_primary_surface", "recommendation_packets_status", "analysis_artifacts_status", "analysis_generated_at", "analysis_context_packet_count", "target_thesis_count", "sell_thesis_count", "trade_thesis_count", "market_source_rows", "market_consensus_rows", "projection_source_rows", "projection_accuracy_rows", "manager_valuation_profile_rows", "counterparty_edge_rows", "manager_profile_tag_rows", "player_profile_tag_rows", "player_dossier_rows"],
}


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
        self.assertIn("ANTHROPIC_API_KEY", result["message"])
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

        self.assertEqual(result, {"items": [{"card_id": "player-1"}]})
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

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
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

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
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

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
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

    def test_article_registry_has_one_summary_and_loadable_prompts(self) -> None:
        from src import articles

        summaries = [article for article in articles.ARTICLES if article.is_summary]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].key, "daily_brief")
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
        self.assertTrue(operator.validate_article_output(good, evidence_ids, headers)["valid"])

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

    def _seed_article_inputs(self, analysis_dir: Path, processed_dir: Path) -> None:
        processed_dir.mkdir(parents=True, exist_ok=True)
        (processed_dir / "player_dossiers.csv").write_text(
            "player_id,player_name,position,roster_id,market_value,projected_ppg,signal_label,news_impact\n"
            "1,Jayden Daniels,QB,2,90,21.1,productive_hold,\n"
            "2,Tank Dell,WR,2,40,10.6,sell_candidate,\n",
            encoding="utf-8",
        )
        for filename, items in (
            ("target_theses.json", [{"player_id": "1", "player_name": "Jayden Daniels", "analysis_text": "Buy-low angle."}]),
            ("sell_theses.json", [{"player_id": "2", "player_name": "Tank Dell", "analysis_text": "Sell-high angle."}]),
            ("trade_theses.json", [{"target_manager_roster_id": 3, "target_manager_name": "The Clapper", "analysis_text": "Trade angle."}]),
            ("manager_dossiers.json", [{"roster_id": 3, "team_name": "The Clapper", "dynasty_cycle": "rebuild", "analysis_text": "Rebuild read."}]),
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

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
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
            self.assertIn("model_mode: automatic_llm", (analysis / "market_watch.md").read_text(encoding="utf-8"))

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
            "projection_source_freshness": ["source", "dataset", "status", "source_url", "cache_path"],
            "projection_source_components": ["source", "source_confidence", "source_trace", "checked_at"],
            "source_accuracy_scores": ["sample_size", "accuracy_confidence", "source_trace"],
            "today_priority_board": ["item_type", "priority_score", "why", "evidence", "source_trace"],
            "player_signal_scores": ["evidence", "risk", "confidence", "source_trace"],
            "breakout_candidates": ["evidence", "risk", "confidence", "source_trace"],
            "sell_candidates": ["evidence", "risk", "confidence", "source_trace"],
            "projection_market_gaps": ["evidence", "risk", "confidence", "source_trace"],
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
            players_audit_exists = (site / "data" / "audit" / "players.json").exists()

        self.assertIn("The Front Office", html)
        self.assertIn("front-office-manifest", html)
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
        self.assertIn("Projection Board", html)
        self.assertIn("Signal Board", html)
        self.assertIn("Analyst Brief", html)
        self.assertIn("Target Theses", html)
        self.assertIn("Sell Theses", html)
        self.assertIn("Trade Theses", html)
        self.assertIn("Manager Dossiers", html)
        self.assertIn("Breakout Candidates", html)
        self.assertIn("Sell Candidates", html)
        self.assertIn("Projection Market Gaps", html)
        self.assertIn("Manager Behavior", html)
        self.assertIn("Market Gaps", html)
        self.assertIn("Counterparty Edges", html)
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
        self.assertIn("function renderTeamPage", html)
        self.assertIn("entity-search", html)
        self.assertIn("Manager Cycle Profiles", html)
        self.assertIn("Player Dossiers", html)
        self.assertIn("League Impact", html)
        self.assertIn("Watchlist / Waiver", html)
        self.assertIn("Unmatched Feed Items", html)
        self.assertIn("Player News Matches", html)
        self.assertIn("Data Diagnostics", html)
        self.assertIn("waiver-scope", html)
        self.assertIn("Source Freshness", html)
        self.assertIn("Player market rows", html)
        self.assertIn("Market source rows", html)
        self.assertIn("Market consensus rows", html)
        self.assertIn("Counterparty edge rows", html)
        self.assertIn("Manager profile tag rows", html)
        self.assertIn("Player dossier rows", html)
        self.assertIn("Player profile tag rows", html)
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

    def test_live_smoke_script_exists_with_required_markers(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_live.py"
        text = script.read_text(encoding="utf-8")

        self.assertIn("fantasy-dominator-production.up.railway.app", text)
        self.assertIn("The Front Office", text)
        self.assertIn("Today's Board", text)
        self.assertIn("brief-card", text)
        self.assertIn("Projection Board", text)
        self.assertIn("Signal Board", text)
        self.assertIn("Analyst Brief", text)
        self.assertIn("today-priority-board", text)
        self.assertIn("News Desk", text)
        self.assertIn("Data Room", text)
        self.assertIn("Data Diagnostics", text)

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
                {"player_id": "elite", "player_name": "Elite QB", "market_value": 8000, "source_trace": "market"},
                {"player_id": "rb", "player_name": "Aging RB", "market_value": 1200, "source_trace": "market"},
                {"player_id": "wr", "player_name": "Young WR", "market_value": 20, "source_trace": "market"},
                {"player_id": "noise", "player_name": "Rookie Noise", "market_value": 60, "source_trace": "market"},
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
        self.assertNotIn("accepted", validation_text.lower())

    def test_external_sources_fail_soft_with_diagnostics(self) -> None:
        frames = refresh_external_sources({"source_policy": "open_legal_only", "external_sources": {"enabled": []}})

        self.assertIn("source_freshness", frames)
        self.assertEqual(frames["source_freshness"].iloc[0]["source"], "external_sources")
        self.assertEqual(frames["source_freshness"].iloc[0]["status"], "no_external_sources_enabled")
        self.assertIn("player_market_values", frames)
        self.assertIn("market_value_sources", frames)
        self.assertIn("market_consensus_values", frames)

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
        pd.DataFrame(columns=["event_type", "week", "created_datetime", "transaction_id", "roster_id", "team_name", "counterparty", "players_in", "picks_in", "faab_in", "players_out", "picks_out", "faab_out", "evidence"]).to_csv(
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
            [{"player_id": "1", "player_name": "Jayden Daniels", "event_type": "draft_pick", "season": 2026, "week": "", "created_datetime": "", "roster_id": 2, "team_name": "Melkor Lord of Light", "counterparty": "", "direction": "drafted pick 1", "evidence": "test", "source_trace": "draft_picks"}]
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
            {"evidence_id": "player:1:1", "entity_type": "player", "entity_id": "1", "name": "Shared Star", "text": "t"},
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


if __name__ == "__main__":
    unittest.main()
