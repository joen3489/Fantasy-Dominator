from __future__ import annotations

import unittest

from src.reality_check import REALITY_CHECK_SCHEMA_VERSION, build_reality_check_packet


class RealityCheckTests(unittest.TestCase):
    def test_packet_is_exact_roster_scoped_and_retains_evidence_receipts(self) -> None:
        packet = build_reality_check_packet(
            {
                "roster_players": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 1,
                        "player_id": "p1",
                        "player_name": "No Team Veteran",
                        "nfl_team": "",
                        "availability_scope": "current_season_snapshot",
                        "injury_status": "",
                        "source_trace": "sleeper:players",
                    },
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 2,
                        "player_id": "p2",
                        "player_name": "Other Manager Player",
                        "nfl_team": "NYG",
                        "availability_scope": "current_season_snapshot",
                        "injury_status": "out",
                    },
                ],
                "player_dossiers": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 1,
                        "player_id": "p1",
                    }
                ],
                "player_signal_scores": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 1,
                        "player_id": "p1",
                        "market_gap_status": "proxy_market_not_calibrated",
                        "signal_label": "missing_projection_watch",
                    }
                ],
                "source_freshness": [
                    {"source": "optional", "dataset": "news", "status": "disabled:key_missing"},
                    {"source": "primary", "dataset": "players", "status": "cached"},
                ],
            },
            league_id="league-1",
            season="2026",
            roster_id=1,
            generated_at="2026-08-27T12:00:00+00:00",
        )

        self.assertEqual(packet["schema_version"], REALITY_CHECK_SCHEMA_VERSION)
        self.assertEqual(packet["roster_rows_checked"], 1)
        self.assertEqual(packet["status"], "flagged")
        self.assertTrue(packet["fingerprint"])
        self.assertTrue(all("evidence_ids" in check for check in packet["checks"]))
        self.assertTrue(all(check["entity_id"] != "p2" for check in packet["checks"]))
        check_ids = {check["check_id"] for check in packet["checks"]}
        self.assertIn("market.proxy_not_calibrated", check_ids)
        self.assertIn("projection.missing_input", check_ids)
        self.assertIn("source.limited_receipt", check_ids)

    def test_actionable_market_universe_cannot_bypass_no_team_guardrail(self) -> None:
        """Design source: AGENTS.md; every actionable player inherits availability limits."""
        packet = build_reality_check_packet(
            {
                "roster_players": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 1,
                        "player_id": "p1",
                        "player_name": "My Player",
                        "nfl_team": "NYG",
                        "availability_scope": "current_season_snapshot",
                    }
                ],
                "player_horizon_market_scores": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": 8,
                        "player_id": "target-1",
                        "player_name": "Target Veteran",
                        "availability_scope": "current_season_snapshot",
                        "current_availability_status": "no_current_nfl_team",
                        "availability_note": "No current NFL team in Sleeper; historical baseline is conditional on signing",
                        "market_value": "3.3",
                    }
                ],
            },
            league_id="league-1",
            season="2026",
            roster_id=1,
            generated_at="2026-08-27T12:00:00+00:00",
        )

        checks = [check for check in packet["checks"] if check["entity_id"] == "target-1"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["check_id"], "availability.no_current_nfl_team")
        self.assertEqual(checks[0]["scope"], "league_actionable_player_universe")
        self.assertEqual(packet["actionable_player_rows_checked"], 1)
        self.assertEqual(packet["source_receipt"]["scope"], "selected_league_roster_and_actionable_player_universe")

    def test_market_check_is_same_position_and_requires_a_real_market_receipt(self) -> None:
        """Design source: docs/data_contract.md; clock deltas are leads, never cross-position rankings."""
        packet = build_reality_check_packet(
            {
                "player_horizon_market_scores": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "player_id": "p1",
                        "player_name": "Receiver One",
                        "market_percentile": 42,
                        "market_source_count": 3,
                        "market_source_confidence": "high",
                        "dynasty_minus_market_delta": 41,
                    },
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "player_id": "p2",
                        "player_name": "Quarterback Two",
                        "market_percentile": 45,
                        "market_source_count": 1,
                        "market_source_confidence": "single_source",
                        "dynasty_minus_market_delta": 60,
                    },
                ]
            },
            league_id="league-1",
            season="2026",
            roster_id=1,
        )

        checks = {(check["entity_id"], check["check_id"]): check for check in packet["checks"]}
        self.assertIn(("p1", "market.large_clock_disagreement"), checks)
        self.assertIn(("p2", "market.single_source_not_calibrated"), checks)
        self.assertEqual(packet["market_quality"]["status"], "multi_source_available")
        self.assertEqual(checks[("p1", "market.large_clock_disagreement")]["observed"]["position"], "unknown")
        self.assertEqual(
            checks[("p1", "market.large_clock_disagreement")]["observed"]["comparison_basis"],
            "position_relative_clock_vs_market_percentile",
        )

    def test_actionable_injury_flag_is_not_lost_when_market_disagreement_also_exists(self) -> None:
        """Design source: AGENTS.md; availability limits must survive every other warning branch."""
        packet = build_reality_check_packet(
            {
                "player_horizon_market_scores": [{
                    "league_id": "league-1", "season": "2026", "player_id": "injured",
                    "player_name": "Injured Receiver", "position": "WR", "injury_status": "Out",
                    "market_percentile": "60", "market_source_count": "3", "market_source_confidence": "high",
                    "dynasty_minus_market_delta": "45",
                }]
            },
            league_id="league-1",
            season="2026",
            roster_id=1,
        )

        checks = {(check["entity_id"], check["check_id"]): check for check in packet["checks"]}
        self.assertIn(("injured", "availability.injury_flag"), checks)
        self.assertIn(("injured", "market.large_clock_disagreement"), checks)


if __name__ == "__main__":
    unittest.main()
