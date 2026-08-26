from __future__ import annotations

import unittest
import tempfile
import json
from pathlib import Path

import pandas as pd

from src.analysis import _attach_horizon_rows, _horizon_market_disagreement_bullets, _manager_trajectory, build_analysis_artifacts, build_horizon_market_read, build_manager_dossier_items, build_manager_intel, build_market_watch, build_player_dossier_items, build_team_report, build_trade_desk


class DeterministicArticleTests(unittest.TestCase):
    def test_horizon_market_read_keeps_each_decision_clock_explicit(self) -> None:
        """Design source: docs/data_contract.md; horizon percentiles are not a universal rank."""
        report = build_horizon_market_read(
            [
                {
                    "player_id": "qb-1",
                    "player_name": "Quarterback One",
                    "position": "QB",
                    "next_game_market_score": 90,
                    "next_game_minus_market_delta": -2,
                    "rest_of_season_market_score": 80,
                    "rest_of_season_minus_market_delta": -12,
                    "rest_of_season_minus_next_game_delta": -10,
                    "dynasty_market_score": 55,
                    "dynasty_minus_market_delta": 10,
                    "dynasty_minus_rest_of_season_delta": -25,
                    "career_projection_score": 50,
                    "career_minus_market_delta": 4,
                    "career_minus_dynasty_delta": -5,
                    "contender_fit_score": 82,
                    "rebuilder_fit_score": 57,
                    "rebuilder_contender_spread": -25,
                    "value_lane": "contender_edge",
                    "availability_scope": "current_season_snapshot",
                    "injury_status": "Questionable",
                    "rest_of_season_ppg": 16,
                    "market_value": 75,
                    "market_percentile": 92,
                    "next_game_status": "schedule_aware_matchup_projection",
                    "dynasty_status": "external_market_plus_timeline",
                    "source_trace": "horizon",
                },
                {
                    "player_id": "wr-1",
                    "player_name": "Receiver One",
                    "position": "WR",
                    "next_game_market_score": 35,
                    "next_game_minus_market_delta": 20,
                    "rest_of_season_market_score": 50,
                    "rest_of_season_minus_market_delta": 10,
                    "rest_of_season_minus_next_game_delta": 15,
                    "dynasty_market_score": 88,
                    "dynasty_minus_market_delta": -5,
                    "dynasty_minus_rest_of_season_delta": 38,
                    "career_projection_score": 91,
                    "career_minus_market_delta": -10,
                    "career_minus_dynasty_delta": 3,
                    "contender_fit_score": 44,
                    "rebuilder_fit_score": 86,
                    "rebuilder_contender_spread": 42,
                    "value_lane": "rebuilder_edge",
                    "market_value": 35,
                    "market_percentile": 70,
                    "next_game_status": "opponent_neutral_weekly_allocation",
                    "dynasty_status": "external_market_plus_timeline",
                    "source_trace": "horizon",
                },
            ],
            "now",
        )

        self.assertIn("## This Week", report)
        self.assertIn("## Rest of Season", report)
        self.assertIn("## Dynasty Window", report)
        self.assertIn("## Market vs Clock", report)
        self.assertIn("## Contender vs Rebuilder", report)
        self.assertIn("position-relative percentile", report)
        self.assertIn("This is timeline fit, not a universal price", report)
        self.assertIn("Quarterback One", report)
        self.assertIn("Receiver One", report)
        self.assertIn("rest-of-season minus next-game delta 15", report)
        self.assertIn("dynasty minus rest-of-season delta 38", report)
        self.assertIn("career minus dynasty delta 3", report)
        self.assertIn("same-position repricing lead", report)
        self.assertIn("availability scope current Sleeper snapshot", report)
        self.assertIn("conditional baseline PPG if active 16", report)
        self.assertLess(len(report.split()), 600)

    def test_horizon_copy_does_not_make_active_players_sound_conditional(self) -> None:
        """Design source: AGENTS.md; availability qualifiers must reflect the current status."""
        report = build_horizon_market_read(
            [{
                "player_name": "Healthy Hill",
                "position": "RB",
                "rest_of_season_market_score": 55,
                "rest_of_season_ppg": 16,
                "injury_status": "Active",
                "rest_of_season_status": "projection",
                "market_value": 10,
                "market_percentile": 45,
            }],
            "now",
        )

        self.assertIn("season baseline 16 PPG", report)
        self.assertNotIn("conditional baseline PPG if active 16", report)

    def test_horizon_market_read_publishes_dated_movement_receipts(self) -> None:
        """Design source: docs/data_contract.md; movement is not a fifth score."""
        report = build_horizon_market_read(
            [{
                "player_name": "Moved Receiver",
                "position": "WR",
                "next_game_market_score": 60,
                "rest_of_season_market_score": 65,
                "dynasty_market_score": 72,
                "career_projection_score": 68,
                "market_value": 30,
                "market_percentile": 50,
            }],
            "now",
            movement_rows=[{
                "player_name": "Moved Receiver",
                "prior_as_of_week": "1",
                "current_as_of_week": "2",
                "largest_clock_movement_window": "dynasty",
                "largest_clock_movement_delta": "12",
                "largest_clock_movement_magnitude": "12",
                "market_value_delta": "-2",
                "value_lane": "rebuilder_edge",
                "movement_status": "changed",
            }],
        )

        self.assertIn("Moved Receiver", report)
        self.assertIn("from week 1 to 2", report)
        self.assertIn("dated exact-scope movement receipt", report)
        self.assertIn("not a fifth score", report)

    def test_market_disagreement_queue_keeps_leads_within_position(self) -> None:
        """Design source: docs/data_contract.md; clock deltas are same-position research leads, not universal prices."""
        bullets = _horizon_market_disagreement_bullets([
            {
                "player_name": "WR Lead",
                "position": "WR",
                "market_value": 22,
                "market_percentile": 60,
                "next_game_minus_market_delta": 18,
                "rest_of_season_minus_market_delta": -9,
                "dynasty_minus_market_delta": 4,
                "career_minus_market_delta": "",
            },
            {
                "player_name": "QB Lag",
                "position": "QB",
                "market_value": 80,
                "market_percentile": 90,
                "next_game_minus_market_delta": -25,
                "rest_of_season_minus_market_delta": -10,
                "dynasty_minus_market_delta": -4,
                "career_minus_market_delta": "",
            },
        ])

        self.assertEqual(len(bullets), 2)
        self.assertIn("WR — WR Lead", bullets[1])
        self.assertIn("next game is 18 percentile points above", bullets[1])
        self.assertIn("rest of season is -9 below it", bullets[1])
        self.assertIn("QB — QB Lag", bullets[0])
        self.assertIn("next game is -25 percentile points below", bullets[0])
        self.assertIn("cross-position price anchor", bullets[0])

    def test_market_disagreement_queue_does_not_pair_a_trivial_lead_with_the_largest_lag(self) -> None:
        """Design source: docs/data_contract.md; positive and negative leads are selected independently within position."""
        bullets = _horizon_market_disagreement_bullets([
            {
                "player_name": "Large Lag",
                "position": "WR",
                "market_value": 40,
                "market_percentile": 80,
                "next_game_minus_market_delta": -80,
                "dynasty_minus_market_delta": 0.08,
            },
            {
                "player_name": "Real Lead",
                "position": "WR",
                "market_value": 12,
                "market_percentile": 40,
                "rest_of_season_minus_market_delta": 35,
            },
        ])

        self.assertEqual(len(bullets), 2)
        self.assertIn("WR — Real Lead", bullets[0])
        self.assertIn("rest of season is 35 percentile points above", bullets[0])
        self.assertIn("WR — Large Lag", bullets[1])
        self.assertIn("next game is -80 percentile points below", bullets[1])
        self.assertNotIn("0.08", bullets[1])

    def test_market_watch_surfaces_available_clock_rows_without_collapsing_the_lenses(self) -> None:
        """Design source: docs/front_office_principles.md; media must make the data room legible."""
        report = build_market_watch(
            [],
            [],
            "2026-08-26T00:00:00+00:00",
            available_horizon_rows=[
                {
                    "player_id": "available-1",
                    "player_name": "Available Clock WR",
                    "position": "WR",
                    "availability_status": "not_rostered_in_selected_league",
                    "identity_status": "sleeper_id",
                    "fit_coverage": "4/4",
                    "next_game_market_score": "72",
                    "rest_of_season_market_score": "84",
                    "rest_of_season_minus_next_game_delta": "12",
                    "dynasty_market_score": "61",
                    "dynasty_minus_rest_of_season_delta": "-23",
                    "career_projection_score": "70",
                    "career_minus_dynasty_delta": "9",
                    "contender_fit_score": "78",
                    "rebuilder_fit_score": "65",
                    "rebuilder_contender_spread": "-13",
                    "value_lane": "contender_edge",
                    "market_value": "12",
                    "market_percentile": "66",
                    "risk": "verify role",
                }
            ],
        )

        self.assertIn("## Buy-Low Targets", report)
        self.assertIn("Available market clock", report)
        self.assertIn("Available Clock WR", report)
        self.assertIn("this-week percentile 72", report)
        self.assertIn("rest-of-season percentile 84 (clock-minus-market n/a; delta 12)", report)
        self.assertIn("dynasty percentile 61 (clock-minus-market n/a; delta -23)", report)
        self.assertIn("not a waiver-eligibility or claim receipt", report)
        self.assertIn("## Sell-High Windows", report)

    def test_horizon_enrichment_does_not_erase_canonical_dossier_facts(self) -> None:
        """Design source: AGENTS.md; enrichment must not overwrite canonical facts with blanks."""
        players = [{"player_id": "p1", "roster_id": 2, "market_value": 80, "player_name": "Anchor"}]
        _attach_horizon_rows(
            players,
            pd.DataFrame([{"player_id": "p1", "roster_id": 2, "market_value": 20, "horizon_model_version": "horizon_market_v1"}]),
        )

        self.assertEqual(players[0]["market_value"], 80)
        self.assertEqual(players[0]["horizon_model_version"], "horizon_market_v1")

    def test_trade_desk_fallback_explains_timeline_fit_separately_from_price(self) -> None:
        """Design source: docs/front_office_principles.md; a writer explains, but does not blend, deterministic lenses."""
        report = build_trade_desk(
            [{
                "target_manager_name": "Timeline Team",
                "approach_type": "price discovery",
                "manager_signal": "patient builder",
                "assets_to_discuss": "Young Receiver",
                "plausible_offer_range": {"low": 20, "high": 24},
                "minimum_acceptable_return": {"value": 18},
                "risk_of_waiting": "No elevated timing risk.",
                "risk_of_acting": "Verify the market.",
                "horizon_fit_read": "target_team_timeline_premium",
                "target_team_lens": "rebuilder",
                "target_horizon_fit_score": 82,
                "active_horizon_fit_score": 41,
                "horizon_fit_edge": 41,
                "evidence": "horizon_model=horizon_market_v1",
                "risk": "medium",
                "confidence": "high",
            }],
            "My Team",
            "now",
        )

        self.assertIn("Timeline fit: target team timeline premium", report)
        self.assertIn("target lens rebuilder at 82", report)
        self.assertIn("separate from market price", report)
        self.assertIn("horizon_model=horizon_market_v1", report)

    def test_team_report_renders_evidence_instead_of_empty_name_bullets(self) -> None:
        dataframes = {
            "player_dossiers": pd.DataFrame(
                [
                    {
                        "roster_id": 2,
                        "player_name": "Anchor QB",
                        "position": "QB",
                        "roster_status": "starter",
                        "market_value": 80,
                        "projected_ppg": 20.5,
                        "projection_confidence": "high",
                        "signal_label": "breakout_target",
                        "news_impact": "",
                        "breakout_score": 90,
                        "sell_score": 12,
                        "transaction_count": 2,
                        "last_transaction": "trade",
                    },
                    {
                        "roster_id": 2,
                        "player_name": "Shop RB",
                        "position": "RB",
                        "roster_status": "bench",
                        "market_value": 35,
                        "projected_ppg": 14.2,
                        "projection_confidence": "high",
                        "signal_label": "monitor",
                        "news_impact": "sell_pressure",
                        "breakout_score": 20,
                        "sell_score": 70,
                        "transaction_count": 1,
                        "last_transaction": "draft_pick",
                    },
                ]
            )
        }

        report = build_team_report(dataframes, 2, "Test Team", "2026-08-22T00:00:00+00:00")

        self.assertIn("market value 80", report)
        self.assertIn("baseline 20.5 PPG", report)
        self.assertIn("sell score is 70", report)
        self.assertNotIn("Anchor QB: \n", report)
        self.assertNotIn("Shop RB: \n", report)

    def test_team_report_keeps_conditional_free_agents_out_of_current_action_sections(self) -> None:
        """Design source: docs/reporter_personas.md; Topline Tony is a current-role desk."""
        dataframes = {
            "player_dossiers": pd.DataFrame(
                [
                    {
                        "roster_id": 2,
                        "player_name": "Active Anchor",
                        "position": "WR",
                        "roster_status": "starter",
                        "market_value": 40,
                        "projected_ppg": 12,
                        "projection_confidence": "high",
                        "signal_label": "productive_hold",
                        "breakout_score": 40,
                        "sell_score": 5,
                    },
                    {
                        "roster_id": 2,
                        "player_name": "Conditional Veteran",
                        "position": "WR",
                        "roster_status": "bench",
                        "market_value": 3,
                        "projected_ppg": 15,
                        "projection_confidence": "high",
                        "current_availability_status": "no_current_nfl_team",
                        "availability_note": "No current NFL team in Sleeper; historical baseline is conditional on signing",
                        "signal_label": "role_uncertain_watch",
                        "news_impact": "sell_pressure",
                        "breakout_score": 10,
                        "sell_score": 80,
                    },
                ]
            )
        }

        report = build_team_report(dataframes, 2, "Test Team", "2026-08-22T00:00:00+00:00")
        shop_section = report.split("## Shop Candidates", 1)[1]

        self.assertIn("1 carry current-role baselines", report)
        self.assertIn("1 retain conditional historical baselines", report)
        self.assertNotIn("Conditional Veteran", shop_section)
        self.assertNotIn("Conditional Veteran", report.split("## Cornerstones", 1)[1].split("## Shop Candidates", 1)[0])
        self.assertIn("Active Anchor", report)

    def test_team_report_fallback_respects_reporter_persona(self) -> None:
        dataframes = {
            "player_dossiers": pd.DataFrame(
                [
                    {
                        "roster_id": 2,
                        "player_name": "Signal Player",
                        "position": "WR",
                        "roster_status": "starter",
                        "market_value": 40,
                        "projected_ppg": 12,
                        "projection_confidence": "high",
                        "signal_label": "monitor",
                        "breakout_score": 40,
                    }
                ]
            )
        }

        scout = build_team_report(dataframes, 2, "Scout Team", "now", {"persona_id": "scout"})
        quant = build_team_report(dataframes, 2, "Quant Team", "now", {"persona_id": "quant"})

        self.assertIn("reporter_persona: scout", scout)
        self.assertIn("role signal", scout.lower())
        self.assertIn("ranking blends", quant.lower())
        self.assertNotEqual(scout, quant)

    def test_player_dossier_artifact_carries_the_four_window_evidence(self) -> None:
        """Design source: docs/data_contract.md; player dossier interpretation must retain its hard-data clocks."""
        items = build_player_dossier_items(
            {
                "player_dossiers": pd.DataFrame([
                    {
                        "league_id": "league-1",
                        "roster_id": 2,
                        "player_id": "p1",
                        "player_name": "Clock Player",
                        "position": "WR",
                        "market_value": 40,
                        "projected_ppg": 14,
                        "projection_confidence": "high",
                        "source_trace": "player_dossiers",
                    }
                ]),
                "player_horizon_market_scores": pd.DataFrame([
                    {
                        "league_id": "league-1",
                        "roster_id": 2,
                        "player_id": "p1",
                        "next_game_market_score": 35,
                        "rest_of_season_market_score": 62,
                        "dynasty_market_score": 88,
                        "career_projection_score": 75,
                        "contender_fit_score": 40,
                        "rebuilder_fit_score": 90,
                        "fit_coverage": "4/4",
                        "horizon_model_version": "horizon_market_v2",
                        "horizon_score_basis": "position-relative percentiles",
                        "source_trace": "player_horizon_market_scores",
                    }
                ]),
            },
            "now",
        )

        item = items[0]
        self.assertEqual(item["dynasty_market_score"], 88)
        self.assertEqual(item["rebuilder_fit_score"], 90)
        self.assertIn("four-window scores: this week 35", item["analysis_text"])
        self.assertIn("player_horizon_market_scores", item["source_trace"])

    def test_topline_fallback_publishes_scoped_week_context_and_receipt_rows(self) -> None:
        """Encodes docs/front_office_realization_epic.md's beat-reporting fallback contract."""
        dataframes = {
            "player_dossiers": pd.DataFrame(
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 2,
                        "player_id": "101",
                        "player_name": "Anchor QB",
                        "position": "QB",
                        "roster_status": "starter",
                        "market_value": 70,
                        "projected_ppg": 20,
                        "projection_confidence": "high",
                        "signal_label": "core_hold",
                        "news_impact": "",
                        "breakout_score": 40,
                        "sell_score": 10,
                    }
                ]
            ),
            "league_news_impact": pd.DataFrame(
                [
                    {
                        "event_id": "news-current",
                        "league_id": "league-1",
                        "season": "2026",
                        "player_id": "101",
                        "player_name": "Anchor QB",
                        "impact_type": "role_or_value_change",
                        "evidence": "Anchor QB named starter",
                        "risk": "medium",
                        "confidence": "high",
                        "source_trace": "news-source",
                    },
                    {
                        "event_id": "news-other",
                        "league_id": "league-2",
                        "season": "2026",
                        "player_id": "101",
                        "player_name": "Anchor QB",
                        "impact_type": "injury_risk",
                        "evidence": "Other league signal must stay out",
                        "risk": "high",
                        "confidence": "high",
                        "source_trace": "other-news-source",
                    },
                ]
            ),
            "matchups": pd.DataFrame(
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "week": 1,
                        "matchup_id": "m1",
                        "roster_id": 2,
                        "opponent_team_name": "Rival Team",
                        "points_for": 18,
                        "points_against": 14,
                        "result": "win",
                        "source_trace": "sleeper:matchups",
                    }
                ]
            ),
            "trades": pd.DataFrame(
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "week": 2,
                        "transaction_id": "trade-1",
                        "team_a_roster_id": 2,
                        "team_a_name": "My Team",
                        "team_b_roster_id": 4,
                        "team_b_name": "Rival Team",
                    }
                ]
            ),
            "waivers": pd.DataFrame(
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "week": 3,
                        "transaction_id": "waiver-1",
                        "roster_id": 2,
                        "player_added": "Depth WR",
                        "player_dropped": "Depth RB",
                    }
                ]
            ),
        }

        report = build_team_report(
            dataframes,
            2,
            "My Team",
            "2026-08-22T00:00:00+00:00",
            active_league_id="league-1",
            current_season="2026",
        )
        self.assertIn("Anchor QB named starter", report)
        self.assertIn("week 1 vs Rival Team (win)", report)
        self.assertIn("trade week 2 with Rival Team", report)
        self.assertIn("waiver week 3: added Depth WR, dropped Depth RB", report)
        self.assertNotIn("Other league signal must stay out", report)

        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = Path(tmp)
            build_analysis_artifacts(
                analysis_dir,
                dataframes,
                {"current_season": "2026", "context": {"league_id": "league-1"}},
                2,
            )
            text = (analysis_dir / "team_report.md").read_text(encoding="utf-8")
            payload_line = next(line for line in text.splitlines() if line.startswith("article_payload_json: "))
            payload = json.loads(payload_line.split(": ", 1)[1])
            self.assertTrue(any(evidence_id.startswith("news:") for evidence_id in payload["evidence_ids"]))
            self.assertTrue(any(evidence_id.startswith("matchup:") for evidence_id in payload["evidence_ids"]))
            self.assertTrue(any(evidence_id.startswith("transaction:") for evidence_id in payload["evidence_ids"]))
            self.assertIn("league_news_impact", payload["source_tables"])
            self.assertIn("matchups", payload["source_tables"])

    def test_default_fallback_articles_use_distinct_newsroom_reporters(self) -> None:
        """Encodes docs/reporter_personas.md and docs/front_office_principles.md's distinct-lens rule."""
        expected = {
            "daily_gm_brief.md": "look_ahead_lonnie",
            "team_report.md": "topline_tony",
            "market_watch.md": "waiver_wire_waverly",
            "trade_desk.md": "trade_desk_talia",
            "manager_intel.md": "dossier_dana",
        }

        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = Path(tmp)
            build_analysis_artifacts(analysis_dir, {}, {}, 2)
            for filename, reporter_id in expected.items():
                text = (analysis_dir / filename).read_text(encoding="utf-8")
                self.assertIn(f"reporter_persona: {reporter_id}", text)
                self.assertIn("reporter_name:", text)
                self.assertIn("evidence_fingerprint:", text)
                self.assertIn("fallback_reason:", text)
                self.assertIn("article_payload_json:", text)
                payload_line = next(line for line in text.splitlines() if line.startswith("article_payload_json: "))
                payload = json.loads(payload_line.split(": ", 1)[1])
                self.assertEqual(payload["fallback_schema_version"], "deterministic_fallback_v2")
                self.assertTrue(payload["lede"])
                self.assertTrue(payload["thesis"])
                self.assertTrue(payload["what_changed"])
                self.assertTrue(payload["action"])
                self.assertTrue(payload["visual_brief"])

    def test_manager_intel_exposes_profile_evidence(self) -> None:
        dataframes = {
            "manager_cycle_profiles": pd.DataFrame(
                [
                    {
                        "team_name": "Evidence Team",
                        "dynasty_cycle": "contender",
                        "likely_needs": "picks",
                        "likely_sells": "excess depth",
                        "trade_temperature": "active trade market",
                        "pick_posture": "pick spender",
                        "confidence": "high",
                        "evidence": "trades=8; future_1sts_net=-2",
                    }
                ]
            )
        }

        report = build_manager_intel(dataframes, "now")

        self.assertIn("Evidence Team", report)
        self.assertIn("trades=8; future_1sts_net=-2", report)
        self.assertIn("Confidence: high", report)
        self.assertNotIn("Evidence Team: picks", report)

    def test_manager_intel_fallback_publishes_dossier_depth(self) -> None:
        """Encodes the manager dossier depth requirement at the written-publication seam."""
        report = build_manager_intel(
            {},
            "now",
            dossier_items=[
                {
                    "roster_id": 4,
                    "team_name": "History Team",
                    "dynasty_cycle": "contender",
                    "likely_needs": "picks",
                    "likely_sells": "excess depth",
                    "trade_temperature": "active trade market",
                    "pick_posture": "pick spender",
                    "confidence": "high",
                    "evidence": "seasons=6; trades_per_season=4",
                    "sample_size": {"seasons": 6, "trades": 24, "matchups": 91},
                    "outcome_summary": {"status": "recorded", "record": "44-37-0"},
                    "trajectory": {"status": "comparison", "summary": "recent window is steadier than prior"},
                    "trade_fit_summary": "2 current trade fits overlap 1 observed valuation lane",
                    "transaction_profile": {
                        "status": "supported",
                        "lanes": [{"position_group": "RB", "transaction_read": "observed acquisition lane", "acquired_count": 8, "sold_count": 2}],
                        "horizon_coverage_by_clock": {
                            "next_game": {"acquired": 6, "sold": 1, "acquired_total": 8, "sold_total": 2},
                        },
                    },
                }
            ],
        )

        self.assertIn("history=6 seasons/24 trades/91 matchups", report)
        self.assertIn("record=44-37-0 (recorded)", report)
        self.assertIn("trajectory=recent window is steadier than prior", report)
        self.assertIn("fit=2 current trade fits", report)
        self.assertIn("movement=RB observed acquisition lane (8 acquired/2 sold)", report)
        self.assertIn("horizon coverage=next game acquired 6/8, sold 1/2", report)

    def test_manager_dossiers_emit_incremental_update_receipts(self) -> None:
        dataframes = {
            "manager_cycle_profiles": pd.DataFrame(
                [{
                    "roster_id": 4,
                    "team_name": "Archive Team",
                    "dynasty_cycle": "contender",
                    "trade_temperature": "active",
                    "pick_posture": "pick spender",
                    "confidence": "high",
                    "evidence": "trades=3",
                }]
            ),
            "manager_profile_tags": pd.DataFrame(
                [{"entity_id": 4, "tag": "aggressive buyer"}]
            ),
            "manager_transaction_preferences": pd.DataFrame([
                {
                    "roster_id": 4,
                    "position_group": "RB",
                    "transaction_read": "observed acquisition lane",
                    "acquired_count": 8,
                    "sold_count": 2,
                    "horizon_acquired_matches": 4,
                    "horizon_sold_matches": 1,
                    "history_status": "supported",
                    "confidence": "high",
                    "source_trace": "manager_transaction_preferences",
                }
            ]),
        }

        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = Path(tmp)
            first = build_analysis_artifacts(analysis_dir, dataframes, {}, 2)
            first_payload = (analysis_dir / "manager_dossiers.json").read_text(encoding="utf-8")
            second = build_analysis_artifacts(analysis_dir, dataframes, {}, 2)
            second_payload = (analysis_dir / "manager_dossiers.json").read_text(encoding="utf-8")

        self.assertEqual(first["manager_dossier_receipt"]["new_count"], 1)
        self.assertEqual(second["manager_dossier_receipt"]["unchanged_count"], 1)
        self.assertNotEqual(first_payload, second_payload)  # generated_at remains an honest refresh receipt.
        item = json.loads(first_payload)["items"][0]
        self.assertIn("roster_construction", item)
        self.assertIn("season_history", item)
        self.assertIn("questions_to_ask", item)
        self.assertEqual(item["trade_fit_status"], "none_supported")
        self.assertIn("No supported trade fit", item["trade_fit_summary"])
        self.assertEqual(item["trade_fit_evaluation"]["current_fit_count"], 0)
        self.assertEqual(item["trajectory"]["status"], "not_available")
        self.assertEqual(item["transaction_profile"]["status"], "supported")
        self.assertEqual(item["transaction_profile"]["lanes"][0]["position_group"], "RB")
        self.assertTrue(any("Manager intent is not observed" in value for value in item["unknowns"]))

    def test_manager_dossier_follows_owner_across_historical_roster_ids(self) -> None:
        """Encodes the identity rule: owner history outranks a repeated roster number."""
        items = build_manager_dossier_items(
            {
                "manager_cycle_profiles": pd.DataFrame(
                    [
                        {
                            "owner_id": "owner-4",
                            "roster_id": 4,
                            "team_name": "Current Team",
                            "dynasty_cycle": "transition",
                            "trade_temperature": "active trade market",
                            "pick_posture": "two-way pick trader",
                            "confidence": "high",
                            "evidence": "owner history",
                        }
                    ]
                ),
                "manager_profiles": pd.DataFrame(
                    [
                        {
                            "owner_id": "owner-4",
                            "roster_id": 4,
                            "team_name": "Current Team",
                            "seasons_covered": "2025; 2026",
                            "roster_ids_by_season": "2026:4; 2025:7",
                            "total_trades": 5,
                            "number_of_waiver_claims": 3,
                        }
                    ]
                ),
                "manager_season_history": pd.DataFrame(
                    [
                        {"owner_id": "owner-4", "season": "2026", "roster_id": 4, "trades": 2, "transaction_count": 3},
                        {"owner_id": "owner-4", "season": "2025", "roster_id": 7, "trades": 3, "transaction_count": 5},
                        {"owner_id": "other-owner", "season": "2025", "roster_id": 7, "trades": 99, "transaction_count": 99},
                    ]
                ),
                "manager_event_log": pd.DataFrame(
                    [
                        {"season": "2026", "roster_id": 4, "event_type": "trade", "week": 2, "team_name": "Current Team"},
                        {"season": "2025", "roster_id": 7, "event_type": "waiver", "week": 3, "team_name": "Former Team"},
                    ]
                ),
            },
            "now",
        )

        item = items[0]
        self.assertEqual(item["owner_id"], "owner-4")
        self.assertEqual(item["sample_size"]["seasons"], 2)
        self.assertEqual(item["sample_size"]["trades"], 5)
        self.assertEqual(item["sample_size"]["observed_events"], 2)
        self.assertEqual({row["roster_id"] for row in item["season_history"]}, {4, 7})
        self.assertNotIn(99, {row["trades"] for row in item["season_history"]})

    def test_manager_dossier_exposes_recorded_outcomes_with_trace(self) -> None:
        """Encodes docs/data_contract.md's rule that outcome depth must remain source-backed."""
        items = build_manager_dossier_items(
            {
                "manager_cycle_profiles": pd.DataFrame([{
                    "roster_id": 4,
                    "team_name": "Archive Team",
                    "dynasty_cycle": "contender",
                    "trade_temperature": "active",
                    "pick_posture": "pick spender",
                    "confidence": "high",
                    "evidence": "matchup outcomes recorded",
                }]),
                "manager_profiles": pd.DataFrame([{
                    "roster_id": 4,
                    "seasons_covered": "2025",
                    "total_trades": 1,
                    "number_of_waiver_claims": 2,
                }]),
                "manager_season_history": pd.DataFrame([{
                    "roster_id": 4,
                    "season": "2025",
                    "transaction_count": 1,
                    "matchup_weeks": "1; 2",
                    "played_weeks": "1; 2",
                    "wins": 1,
                    "losses": 1,
                    "ties": 0,
                    "points_for": 210,
                    "points_against": 200,
                    "outcome_status": "recorded",
                    "source_trace": "manager_season_history;matchups",
                }]),
            },
            "now",
        )

        item = items[0]
        self.assertEqual(item["outcome_summary"]["status"], "recorded")
        self.assertEqual(item["outcome_summary"]["record"], "1-1-0")
        self.assertEqual(item["outcome_summary"]["point_diff"], 10)
        self.assertEqual(item["outcome_summary"]["scored_matchups"], 2)
        self.assertEqual(item["sample_size"]["matchups"], 2)
        self.assertEqual(item["sample_size"]["scored_matchups"], 2)
        self.assertIn("matchups", item["source_trace"])
        self.assertTrue(any(row["label"] == "Season outcomes" for row in item["behavior_observations"]))

    def test_manager_dossier_exposes_recent_trajectory_without_inventing_intent(self) -> None:
        """Encodes docs/front_office_realization_epic.md's transition and timing requirement."""
        items = build_manager_dossier_items(
            {
                "manager_cycle_profiles": pd.DataFrame([{
                    "roster_id": 4,
                    "team_name": "Archive Team",
                    "dynasty_cycle": "transition",
                    "trade_temperature": "active trade market",
                    "pick_posture": "two-way pick trader",
                    "waiver_posture": "active waiver market",
                    "confidence": "high",
                    "evidence": "season history",
                }]),
                "manager_profiles": pd.DataFrame([{
                    "roster_id": 4,
                    "seasons_covered": "2023; 2024; 2025; 2026",
                    "total_trades": 12,
                    "number_of_waiver_claims": 18,
                }]),
                "manager_season_history": pd.DataFrame([
                    {"roster_id": 4, "season": "2023", "trades": 1, "waiver_claims": 1, "transaction_count": 2, "outcome_status": "recorded", "wins": 7, "losses": 10, "ties": 0},
                    {"roster_id": 4, "season": "2024", "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 9, "ties": 0},
                    {"roster_id": 4, "season": "2025", "trades": 5, "waiver_claims": 4, "transaction_count": 9, "outcome_status": "recorded", "wins": 11, "losses": 6, "ties": 0},
                    {"roster_id": 4, "season": "2026", "trades": 4, "waiver_claims": 5, "transaction_count": 9, "outcome_status": "recorded", "wins": 10, "losses": 7, "ties": 0},
                ]),
            },
            "now",
        )

        trajectory = items[0]["trajectory"]
        self.assertEqual(trajectory["status"], "comparison")
        self.assertEqual(trajectory["recent_seasons"], [2025, 2026])
        self.assertEqual(trajectory["prior_seasons"], [2023, 2024])
        self.assertEqual(trajectory["activity_read"], "more active")
        self.assertEqual(trajectory["outcome_read"], "stronger results")
        self.assertEqual(trajectory["outcome_status"], "comparable")
        self.assertIn("manager_season_history", trajectory["evidence"])
        self.assertIn("Latest observed window", items[0]["analysis_text"])
        self.assertIn("intent", items[0]["unknowns"][0].lower())

        steady = _manager_trajectory([
            {"season": 2023, "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 8, "ties": 0},
            {"season": 2024, "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 8, "ties": 0},
            {"season": 2025, "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 8, "ties": 0},
            {"season": 2026, "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 8, "ties": 0},
        ])
        self.assertIn("is steady compared with", steady["summary"])
        self.assertNotIn("steady than", steady["summary"])

    def test_manager_trajectory_excludes_partial_season_from_outcome_trend(self) -> None:
        """Encodes the epic's rule: current activity may be partial, outcome trends may not be."""
        trajectory = _manager_trajectory([
            {"season": 2023, "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 8, "ties": 0},
            {"season": 2024, "trades": 2, "waiver_claims": 2, "transaction_count": 4, "outcome_status": "recorded", "wins": 8, "losses": 8, "ties": 0},
            {"season": 2025, "trades": 5, "waiver_claims": 4, "transaction_count": 9, "outcome_status": "recorded", "wins": 13, "losses": 3, "ties": 0},
            {"season": 2026, "trades": 4, "waiver_claims": 5, "transaction_count": 9, "outcome_status": "partial", "wins": 0, "losses": 0, "ties": 0},
        ])
        self.assertEqual(trajectory["recent_seasons"], [2025, 2026])
        self.assertEqual(trajectory["outcome_recent_seasons"], [2025])
        self.assertEqual(trajectory["partial_recent_seasons"], [2026])
        self.assertEqual(trajectory["outcome_status"], "limited")
        self.assertEqual(trajectory["outcome_read"], "limited coverage")
        self.assertIn("partial recent seasons: 2026", trajectory["summary"])

    def test_manager_trade_fit_evaluation_exposes_cross_season_alignment(self) -> None:
        """Encodes docs/front_office_realization_epic.md's cross-season trade-fit rule."""
        items = build_manager_dossier_items(
            {
                "manager_cycle_profiles": pd.DataFrame([
                    {
                        "roster_id": 4,
                        "team_name": "Archive Team",
                        "dynasty_cycle": "contender",
                        "trade_temperature": "active",
                        "pick_posture": "pick spender",
                        "confidence": "high",
                        "evidence": "seasons=2; trades=4",
                    }
                ]),
                "manager_profiles": pd.DataFrame([
                    {
                        "roster_id": 4,
                        "team_name": "Archive Team",
                        "seasons_covered": "2025; 2026",
                        "total_trades": 4,
                        "number_of_waiver_claims": 8,
                        "contender_rebuilder_indicator": "possible contender",
                    }
                ]),
                "manager_season_history": pd.DataFrame([
                    {"roster_id": 4, "season": "2025", "transaction_count": 2, "trades": 1},
                    {"roster_id": 4, "season": "2026", "transaction_count": 3, "trades": 3},
                ]),
                "manager_valuation_profiles": pd.DataFrame([
                    {
                        "roster_id": 4,
                        "position_group": "PASS_CATCHER",
                        "label": "pass-catcher accumulator",
                        "preference_score": 82,
                        "recency_weighted_score": 88,
                        "evidence_count": 6,
                        "confidence": "high",
                        "evidence": "pass catchers acquired across two seasons",
                    }
                ]),
                "counterparty_trade_edges": pd.DataFrame([
                    {
                        "target_roster_id": 4,
                        "player_id": "p1",
                        "player_name": "Target WR",
                        "position": "WR",
                        "edge_type": "mutual_fit",
                        "trade_edge_score": 62,
                        "market_consensus_value": 50,
                        "estimated_owner_value_score": 48,
                        "evidence": "current edge",
                        "risk": "medium",
                        "confidence": "medium",
                        "source_trace": "edge",
                    },
                    {
                        "target_roster_id": 4,
                        "player_id": "p2",
                        "player_name": "Target RB",
                        "position": "RB",
                        "edge_type": "owner_may_overvalue",
                        "trade_edge_score": 30,
                        "market_consensus_value": 40,
                        "estimated_owner_value_score": 52,
                        "evidence": "current RB edge",
                        "risk": "high",
                        "confidence": "low",
                        "source_trace": "edge",
                    }
                ]),
            },
            "now",
        )

        evaluation = items[0]["trade_fit_evaluation"]
        self.assertEqual(items[0]["trade_fit_status"], "supported")
        self.assertEqual(evaluation["aligned_position_groups"], ["PASS_CATCHER"])
        self.assertIn("overlap", evaluation["summary"])
        self.assertEqual(evaluation["historical_seasons"], 2)
        self.assertEqual(evaluation["fit_alignment"][0]["status"], "aligned")
        self.assertEqual(evaluation["fit_alignment"][0]["lane_label"], "pass-catcher accumulator")
        self.assertEqual(evaluation["fit_alignment"][1]["status"], "no_direct_lane")
        self.assertEqual(evaluation["fit_alignment"][1]["position_group"], "RB")
        self.assertEqual(evaluation["aligned_fit_count"], 1)
        self.assertEqual(evaluation["no_direct_lane_fit_count"], 1)

    def test_manager_dossier_carries_scoped_event_timeline(self) -> None:
        """Encodes Workstream 5's transaction-timeline requirement from the realization epic."""
        items = build_manager_dossier_items(
            {
                "manager_cycle_profiles": pd.DataFrame(
                    [{
                        "roster_id": 4,
                        "team_name": "Archive Team",
                        "dynasty_cycle": "contender",
                        "trade_temperature": "active",
                        "pick_posture": "pick spender",
                        "confidence": "high",
                        "evidence": "trades=2",
                    }]
                ),
                "manager_profiles": pd.DataFrame(
                    [{
                        "roster_id": 4,
                        "team_name": "Archive Team",
                        "seasons_covered": "2025; 2026",
                        "total_trades": 2,
                        "number_of_waiver_claims": 1,
                    }]
                ),
                "manager_event_log": pd.DataFrame(
                    [
                        {
                            "season": "2026",
                            "event_type": "trade",
                            "week": 5,
                            "created_datetime": "2026-05-02T00:00:00+00:00",
                            "transaction_id": "new-event",
                            "roster_id": 4,
                            "team_name": "Archive Team",
                            "counterparty": "Partner Team",
                            "players_in": "Target WR",
                            "players_out": "Shop RB",
                            "evidence": "Sleeper trade transaction",
                        },
                        {
                            "season": "2026",
                            "event_type": "waiver",
                            "week": 2,
                            "created_datetime": "2026-04-01T00:00:00+00:00",
                            "transaction_id": "old-event",
                            "roster_id": 4,
                            "team_name": "Archive Team",
                            "counterparty": "waiver wire",
                            "players_in": "Depth WR",
                            "evidence": "Sleeper waiver transaction",
                        },
                        {
                            "season": "2026",
                            "event_type": "trade",
                            "week": 6,
                            "created_datetime": "2026-06-01T00:00:00+00:00",
                            "transaction_id": "foreign-event",
                            "roster_id": 9,
                            "team_name": "Foreign Team",
                            "counterparty": "Archive Team",
                            "players_in": "Foreign Player",
                            "evidence": "Sleeper trade transaction",
                        },
                    ]
                ),
            },
            "now",
        )

        timeline = items[0]["transaction_timeline"]
        self.assertEqual([row["event_id"] for row in timeline], ["new-event", "old-event"])
        self.assertTrue(all(row["roster_id"] == 4 for row in timeline))
        self.assertEqual(timeline[0]["source_trace"], "manager_event_log")
        self.assertEqual(timeline[0]["players_in"], "Target WR")


if __name__ == "__main__":
    unittest.main()
