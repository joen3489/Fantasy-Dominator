from __future__ import annotations

import unittest
import tempfile
import json
from pathlib import Path

import pandas as pd

from src.analysis import build_analysis_artifacts, build_manager_dossier_items, build_manager_intel, build_team_report


class DeterministicArticleTests(unittest.TestCase):
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
        self.assertIn("projected 20.5 PPG", report)
        self.assertIn("sell score is 70", report)
        self.assertNotIn("Anchor QB: \n", report)
        self.assertNotIn("Shop RB: \n", report)

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
        self.assertTrue(any("Manager intent is not observed" in value for value in item["unknowns"]))

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
        self.assertEqual(item["sample_size"]["matchups"], 2)
        self.assertIn("matchups", item["source_trace"])
        self.assertTrue(any(row["label"] == "Season outcomes" for row in item["behavior_observations"]))

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
