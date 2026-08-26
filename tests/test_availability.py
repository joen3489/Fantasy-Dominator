import unittest

import pandas as pd

from src.availability import (
    availability_note,
    baseline_ppg_label,
    baseline_ppg_text,
    current_availability_status,
)
from src.horizons import build_player_horizon_market_scores
from src.profile_intelligence import build_player_dossiers
from src.signals import (
    build_action_recommendations,
    build_breakout_candidates,
    build_counterparty_trade_edges,
    build_news_market_edges,
    build_player_signal_scores,
    build_projection_market_gaps,
    build_sell_candidates,
    build_team_fit_scores,
)


class AvailabilityContractTests(unittest.TestCase):
    def test_sleeper_free_agent_is_not_treated_as_available(self) -> None:
        """Design source: AGENTS.md; current NFL team is part of the availability boundary."""

        row = {
            "season": "2026",
            "availability_scope": "current_season_snapshot",
            "nfl_team": "",
            "status": "Active",
            "injury_status": "Questionable",
        }

        self.assertEqual(current_availability_status(row), "no_current_nfl_team")
        self.assertIn("No current NFL team", availability_note(row))
        self.assertEqual(baseline_ppg_label(row), "conditional baseline PPG if signed")
        self.assertEqual(
            baseline_ppg_text(row, "15.0"),
            "conditional baseline PPG if signed 15.0",
        )

    def test_missing_team_field_is_unknown_not_free_agent(self) -> None:
        """Design source: docs/data_contract.md; missing evidence is not a negative fact."""

        self.assertEqual(current_availability_status({"injury_status": "Active"}), "unknown")
        self.assertEqual(baseline_ppg_text({"injury_status": "Active"}, "15"), "season baseline 15 PPG")

    def test_pandas_nan_is_missing_not_a_team_or_injury(self) -> None:
        """Design source: AGENTS.md; CSV nulls must preserve the identity boundary."""

        free_agent = pd.Series(
            {
                "availability_scope": "current_season_snapshot",
                "nfl_team": float("nan"),
                "injury_status": float("nan"),
                "injury_body_part": float("nan"),
            }
        )
        active = pd.Series(
            {
                "availability_scope": "current_season_snapshot",
                "nfl_team": "WAS",
                "injury_status": float("nan"),
                "injury_body_part": float("nan"),
            }
        )

        self.assertEqual(current_availability_status(free_agent), "no_current_nfl_team")
        self.assertIn("No current NFL team", availability_note(free_agent))
        self.assertEqual(current_availability_status(active), "available")
        self.assertIn("No current Sleeper injury flag", availability_note(active))

    def test_rating_layer_withholds_actionable_scores_for_free_agent(self) -> None:
        """Design source: docs/data_contract.md; history may remain context but cannot become a current-role signal."""

        projections = pd.DataFrame(
            [
                {
                    "season": "2026",
                    "player_id": "fa",
                    "player_name": "Free Agent Receiver",
                    "position": "WR",
                    "team": "",
                    "roster_id": 2,
                    "team_name": "My Team",
                    "projected_fantasy_points": 255,
                    "projected_ppg": 15,
                    "projection_confidence": "high",
                    "source_trace": "history",
                }
            ]
        )
        roster = pd.DataFrame(
            [
                {
                    "season": "2026",
                    "league_id": "league",
                    "roster_id": 2,
                    "player_id": "fa",
                    "player_name": "Free Agent Receiver",
                    "position": "WR",
                    "nfl_team": "",
                    "availability_scope": "current_season_snapshot",
                    "injury_status": "Questionable",
                    "injury_body_part": "knee",
                    "team_name": "My Team",
                },
                {
                    "season": "2025",
                    "league_id": "league",
                    "roster_id": 2,
                    "player_id": "fa",
                    "player_name": "Free Agent Receiver",
                    "position": "WR",
                    "nfl_team": "",
                    "availability_scope": "historical_unavailable",
                    "injury_status": "",
                    "injury_body_part": "",
                    "team_name": "My Team",
                },
            ]
        )
        market = pd.DataFrame(
            [
                {
                    "player_id": "fa",
                    "player_name": "Free Agent Receiver",
                    "position": "WR",
                    "market_value": 10,
                    "source_count": 2,
                    "source_trace": "market",
                }
            ]
        )
        signals = build_player_signal_scores(
            projections,
            roster,
            market,
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            {"current_team": {"roster_id": 2}},
        )
        signal = signals.iloc[0]
        self.assertEqual(signal["signal_label"], "role_uncertain_watch")
        self.assertEqual(signal["confidence"], "low")
        self.assertIn("No current NFL team", signal["evidence"])
        action = build_action_recommendations(signals, {"current_team": {"roster_id": 2}}).iloc[0]
        self.assertEqual(action["action_label"], "conditional_watch")
        self.assertEqual(action["confidence"], "low")
        self.assertIn("no current weekly role", action["why"])

        horizons = build_player_horizon_market_scores(
            projections,
            pd.DataFrame(
                [
                    {
                        "season": "2026",
                        "week": 2,
                        "player_id": "fa",
                        "position": "WR",
                        "projected_fantasy_points": 15,
                    }
                ]
            ),
            signals,
            roster,
            {"current_season": "2026", "current_week": 1, "league_id": "league"},
            market_consensus_df=pd.DataFrame(
                [
                    {
                        "player_id": "fa",
                        "source_count": 2,
                        "disagreement_score": 0,
                        "confidence": "high",
                        "source_trace": "market",
                    }
                ]
            ),
        )
        horizon = horizons.iloc[0]
        self.assertEqual(horizon["current_availability_status"], "no_current_nfl_team")
        self.assertTrue(pd.isna(horizon["next_game_market_score"]))
        self.assertTrue(pd.isna(horizon["rest_of_season_market_score"]))
        self.assertEqual(horizon["next_game_status"], "unavailable_no_current_nfl_team")
        self.assertEqual(horizon["rest_of_season_status"], "unavailable_no_current_nfl_team")

    def test_free_agent_baseline_does_not_calibrate_current_projection_percentiles(self) -> None:
        """Design source: docs/data_contract.md; conditional history cannot calibrate current-role rankings."""

        projections = pd.DataFrame(
            [
                {
                    "player_id": "active-low",
                    "player_name": "Active Low",
                    "position": "WR",
                    "team": "AAA",
                    "roster_id": 1,
                    "projected_fantasy_points": 170,
                    "projected_ppg": 10,
                    "projection_confidence": "high",
                    "source_trace": "projection",
                },
                {
                    "player_id": "active-high",
                    "player_name": "Active High",
                    "position": "WR",
                    "team": "BBB",
                    "roster_id": 2,
                    "projected_fantasy_points": 204,
                    "projected_ppg": 12,
                    "projection_confidence": "high",
                    "source_trace": "projection",
                },
                {
                    "player_id": "conditional",
                    "player_name": "Conditional Veteran",
                    "position": "WR",
                    "team": "",
                    "roster_id": 3,
                    "projected_fantasy_points": 850,
                    "projected_ppg": 50,
                    "projection_confidence": "high",
                    "source_trace": "historical projection",
                },
            ]
        )
        roster = pd.DataFrame(
            [
                {"player_id": "active-low", "nfl_team": "AAA", "availability_scope": "current_season_snapshot"},
                {"player_id": "active-high", "nfl_team": "BBB", "availability_scope": "current_season_snapshot"},
                {"player_id": "conditional", "nfl_team": "", "availability_scope": "current_season_snapshot"},
            ]
        )

        signals = build_player_signal_scores(
            projections,
            roster,
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            {},
        ).set_index("player_id")

        self.assertEqual(float(signals.loc["active-low", "projection_percentile"]), 25.0)
        self.assertEqual(float(signals.loc["active-high", "projection_percentile"]), 75.0)
        self.assertTrue(pd.isna(signals.loc["conditional", "projection_percentile"]) or signals.loc["conditional", "projection_percentile"] == "")
        self.assertEqual(float(signals.loc["conditional", "market_gap_score"]), 0.0)
        self.assertEqual(signals.loc["conditional", "market_gap_status"], "availability_conditioned_unavailable")

    def test_no_current_team_cannot_reappear_in_actionable_secondary_queues(self) -> None:
        """Design source: AGENTS.md; one availability fact must constrain every rating seam."""

        scores = pd.DataFrame(
            [
                {
                    "player_id": "fa",
                    "player_name": "Free Agent Receiver",
                    "position": "WR",
                    "age": 31,
                    "roster_id": 2,
                    "team_name": "My Team",
                    "current_availability_status": "no_current_nfl_team",
                    "projected_fantasy_points": 255,
                    "projected_ppg": 15,
                    "market_value": 10,
                    "projection_edge_score": 20,
                    "market_gap_score": 70,
                    "projection_percentile": 95,
                    "market_percentile": 25,
                    "market_gap_status": "position_percentile_disagreement",
                    "breakout_score": 80,
                    "sell_score": 70,
                    "signal_label": "role_uncertain_watch",
                    "risk": "high: no current team",
                    "confidence": "low",
                    "evidence": "conditional historical evidence",
                    "source_trace": "sleeper;history",
                }
            ]
        )
        config = {"current_team": {"roster_id": 2}}

        gaps = build_projection_market_gaps(scores)
        self.assertEqual(gaps.iloc[0]["current_availability_status"], "no_current_nfl_team")
        self.assertEqual(float(gaps.iloc[0]["gap_score"]), 0.0)
        self.assertEqual(gaps.iloc[0]["gap_label"], "availability_conditioned_gap")
        self.assertEqual(len(build_breakout_candidates(scores)), 0)
        self.assertEqual(len(build_sell_candidates(scores, config)), 0)
        self.assertEqual(
            len(build_team_fit_scores(scores, pd.DataFrame([{ "roster_id": 8, "team_name": "Rival", "need_wr": "high" }]), config)),
            0,
        )
        self.assertEqual(
            len(build_counterparty_trade_edges(scores, pd.DataFrame(), pd.DataFrame(), config)),
            0,
        )
        self.assertEqual(
            len(build_news_market_edges(
                scores,
                pd.DataFrame([{"player_id": "fa", "impact_type": "sell_pressure", "confidence": "high"}]),
                config,
            )),
            0,
        )

    def test_player_dossier_carries_shared_current_availability_status(self) -> None:
        """Design source: AGENTS.md; profile surfaces cannot make readers infer current availability from prose."""

        roster = pd.DataFrame(
            [{
                "season": "2026",
                "player_id": "fa",
                "player_name": "Free Agent Receiver",
                "position": "WR",
                "age": 29,
                "roster_id": 2,
                "team_name": "My Team",
                "roster_status": "active",
                "availability_scope": "current_season_snapshot",
                "nfl_team": "",
                "injury_status": "Questionable",
                "injury_body_part": "knee",
            }]
        )
        signals = pd.DataFrame(
            [{
                "player_id": "fa",
                "current_availability_status": "no_current_nfl_team",
                "availability_note": "No current NFL team in Sleeper; historical baseline is conditional on signing",
                "signal_label": "role_uncertain_watch",
                "confidence": "low",
            }]
        )
        dossiers = build_player_dossiers(
            roster,
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            signals,
            pd.DataFrame(),
        )
        dossier = dossiers.iloc[0]
        self.assertEqual(dossier["current_availability_status"], "no_current_nfl_team")
        self.assertIn("No current NFL team", dossier["availability_note"])


if __name__ == "__main__":
    unittest.main()
