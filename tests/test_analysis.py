from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import pandas as pd

from src.analysis import build_analysis_artifacts, build_manager_intel, build_team_report


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


if __name__ == "__main__":
    unittest.main()
