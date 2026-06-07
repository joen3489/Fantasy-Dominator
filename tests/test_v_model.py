from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.analysis import build_analysis_artifacts
from src.browser_site import build_browser_site
from src.economics import build_economic_tables
from src.external_sources import build_market_consensus_values, refresh_external_sources
from src.news import build_news_tables
from src.normalize import build_roster_maps, normalize_traded_picks
from src.pick_ownership import build_pick_ownership
from src.players import players_table
from src.projections import calculate_fantasy_points
from src.signals import build_signal_tables
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
    "player_signal_scores": ["player_id", "player_name", "position", "roster_id", "team_name", "projection_edge_score", "market_gap_score", "timeline_fit_score", "breakout_score", "sell_score", "signal_label", "evidence", "risk", "confidence", "source_trace"],
    "breakout_candidates": ["player_id", "player_name", "position", "current_team_name", "breakout_score", "projection_edge", "market_value", "evidence", "risk", "confidence", "source_trace"],
    "sell_candidates": ["player_id", "player_name", "position", "current_team_name", "sell_score", "projection_risk", "market_value", "evidence", "risk", "confidence", "source_trace"],
    "projection_market_gaps": ["player_id", "player_name", "position", "projected_fantasy_points", "projected_ppg", "market_value", "gap_score", "gap_label", "evidence", "risk", "confidence", "source_trace"],
    "team_fit_scores": ["roster_id", "team_name", "player_id", "player_name", "position", "timeline_fit_score", "need_fit_score", "liquidity_fit_score", "fit_label", "evidence", "risk", "confidence", "source_trace"],
    "action_recommendations": ["roster_id", "team_name", "player_id", "player_name", "position", "action_label", "consumer_label", "action_rank", "action_score", "projected_ppg", "market_value", "why", "evidence", "risk", "confidence", "source_trace"],
    "manager_profiles": ["roster_id", "display_name", "team_name", "total_trades", "trades_by_season", "players_acquired", "players_sold", "picks_acquired", "picks_sold", "future_1sts_acquired", "future_1sts_sold", "future_2nds_acquired", "future_2nds_sold", "faab_spent_on_waivers", "number_of_waiver_claims", "average_waiver_bid", "max_waiver_bid", "most_common_transaction_partners", "qb_count", "rb_count", "pass_catcher_count", "contender_rebuilder_indicator", "notes"],
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
    "refresh_metadata": ["generated_at", "current_season", "configured_league_ids", "configured_seasons", "ingested_seasons", "historical_league_ids_configured", "transaction_week_start", "transaction_week_end", "source_scope", "raw_cache_root", "raw_external_cache_root", "browser_is_primary_surface", "recommendation_packets_status", "analysis_artifacts_status", "analysis_generated_at", "analysis_context_packet_count", "target_thesis_count", "sell_thesis_count", "trade_thesis_count", "market_source_rows", "market_consensus_rows", "manager_valuation_profile_rows", "counterparty_edge_rows"],
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
            "player_signal_scores": ["evidence", "risk", "confidence", "source_trace"],
            "breakout_candidates": ["evidence", "risk", "confidence", "source_trace"],
            "sell_candidates": ["evidence", "risk", "confidence", "source_trace"],
            "projection_market_gaps": ["evidence", "risk", "confidence", "source_trace"],
            "team_fit_scores": ["evidence", "risk", "confidence", "source_trace"],
            "action_recommendations": ["consumer_label", "why", "evidence", "risk", "confidence", "source_trace"],
            "manager_valuation_profiles": ["evidence", "confidence", "label"],
            "counterparty_trade_edges": ["evidence", "risk", "confidence", "source_trace"],
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
        self.assertIn("Action Board", html)
        self.assertNotIn("Buy-Low Targets", html)
        self.assertIn("Sell Windows", html)
        self.assertIn("My Roster News", html)
        self.assertIn("Trade Target News", html)
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
        self.assertIn("Action Board", text)
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
                    "roster_id": 2,
                    "team_name": "Melkor Lord of Light",
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


if __name__ == "__main__":
    unittest.main()
