from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.horizon_accuracy import (
    ACCURACY_COLUMNS,
    HORIZON_MOVEMENT_COLUMNS,
    SNAPSHOT_COLUMNS,
    append_horizon_snapshot,
    build_horizon_accuracy_table,
    build_horizon_movement_table,
)


def _snapshot_row(
    *,
    scope: str,
    league_id: str,
    week: int,
    player_id: str = "sleeper-1",
    player_name: str = "Alpha Receiver",
    next_game: float = 60,
    rest_of_season: float = 58,
    dynasty: float = 55,
    career: float = 52,
    market_value: float = 40,
    market_percentile: float = 50,
    lane: str = "balanced_window",
) -> dict[str, object]:
    row = {column: "" for column in SNAPSHOT_COLUMNS}
    row.update(
        {
            "snapshot_at": f"2026-09-{week:02d}T00:00:00+00:00",
            "snapshot_scope": scope,
            "season": "2026",
            "league_id": league_id,
            "as_of_week": str(week),
            "player_id": player_id,
            "player_name": player_name,
            "position": "WR",
            "horizon_model_version": "horizon_market_v2",
            "market_value": market_value,
            "market_percentile": market_percentile,
            "market_source_count": 1,
            "market_disagreement_score": 0,
            "market_source_confidence": "medium",
            "next_game_market_score": next_game,
            "next_game_minus_market_delta": next_game - market_percentile,
            "rest_of_season_market_score": rest_of_season,
            "rest_of_season_minus_market_delta": rest_of_season - market_percentile,
            "dynasty_market_score": dynasty,
            "dynasty_minus_market_delta": dynasty - market_percentile,
            "career_projection_score": career,
            "career_minus_market_delta": career - market_percentile,
            "contender_fit_score": next_game,
            "rebuilder_fit_score": dynasty,
            "fit_coverage": "4/4",
            "value_lane": lane,
            "source_trace": "player_horizon_market_scores",
        }
    )
    return row


class HorizonAccuracyTests(unittest.TestCase):
    def test_movement_has_no_baseline_row_without_an_earlier_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizon_snapshot_history.csv"
            current = pd.DataFrame(
                [
                    {
                        "season": "2026",
                        "league_id": "league-1",
                        "as_of_week": 1,
                        "player_id": "sleeper-1",
                        "player_name": "Alpha Receiver",
                        "position": "WR",
                        "horizon_model_version": "horizon_market_v2",
                        "next_game_market_score": 60,
                    }
                ]
            )

            result = build_horizon_movement_table(
                path,
                current,
                {"league_id": "league-1", "current_season": "2026", "context": {"roster_id": 2}},
            )

            self.assertEqual(list(result.columns), HORIZON_MOVEMENT_COLUMNS)
            self.assertTrue(result.empty)

    def test_movement_uses_latest_earlier_exact_scope_and_ignores_foreign_league(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizon_snapshot_history.csv"
            rows = [
                _snapshot_row(
                    scope="league:league-1:season:2026:roster:2",
                    league_id="league-1",
                    week=1,
                    next_game=60,
                ),
                _snapshot_row(
                    scope="league:league-1:season:2026:roster:2",
                    league_id="league-1",
                    week=2,
                    next_game=65,
                ),
                _snapshot_row(
                    scope="league:league-2:season:2026:roster:2",
                    league_id="league-2",
                    week=3,
                    next_game=5,
                ),
            ]
            pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS).to_csv(path, index=False)
            current = pd.DataFrame(
                [
                    {
                        "season": "2026",
                        "league_id": "league-1",
                        "as_of_week": 4,
                        "player_id": "sleeper-1",
                        "player_name": "Alpha Receiver",
                        "position": "WR",
                        "horizon_model_version": "horizon_market_v2",
                        "market_value": 42,
                        "market_percentile": 52,
                        "next_game_market_score": 80,
                        "rest_of_season_market_score": 70,
                        "dynasty_market_score": 75,
                        "career_projection_score": 70,
                        "contender_fit_score": 78,
                        "rebuilder_fit_score": 72,
                        "rebuilder_contender_spread": -6,
                        "value_lane": "balanced_window",
                        "source_trace": "player_horizon_market_scores",
                    }
                ]
            )

            result = build_horizon_movement_table(
                path,
                current,
                {"league_id": "league-1", "current_season": "2026", "context": {"roster_id": 2}},
            )

            self.assertEqual(len(result), 1)
            row = result.iloc[0]
            self.assertEqual(row["prior_as_of_week"], "2")
            self.assertEqual(row["current_as_of_week"], "4")
            self.assertEqual(float(row["next_game_score_delta"]), 15.0)
            self.assertEqual(row["largest_clock_movement_window"], "dynasty")
            self.assertEqual(float(row["largest_clock_movement_magnitude"]), 20.0)
            self.assertEqual(row["movement_status"], "changed")
            self.assertIn("exact-scope", row["evidence"])

    def test_movement_does_not_compare_a_same_week_rerun_to_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizon_snapshot_history.csv"
            pd.DataFrame(
                [
                    _snapshot_row(
                        scope="league:league-1:season:2026:roster:2",
                        league_id="league-1",
                        week=4,
                    )
                ],
                columns=SNAPSHOT_COLUMNS,
            ).to_csv(path, index=False)
            current = pd.DataFrame(
                [
                    {
                        "season": "2026",
                        "league_id": "league-1",
                        "as_of_week": 4,
                        "player_id": "sleeper-1",
                        "position": "WR",
                        "horizon_model_version": "horizon_market_v2",
                        "next_game_market_score": 99,
                    }
                ]
            )

            result = build_horizon_movement_table(
                path,
                current,
                {"league_id": "league-1", "current_season": "2026", "context": {"roster_id": 2}},
            )

            self.assertTrue(result.empty)

    def test_snapshot_append_is_idempotent_by_scope_week_player_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizon_snapshot_history.csv"
            horizons = pd.DataFrame(
                [
                    {
                        "season": "2026",
                        "league_id": "league-1",
                        "as_of_week": 1,
                        "player_id": "sleeper-1",
                        "player_name": "Alpha Receiver",
                        "position": "WR",
                        "horizon_model_version": "horizon_market_v2",
                        "market_value": 40,
                        "market_percentile": 35,
                        "next_game_market_score": 80,
                        "next_game_minus_market_delta": 45,
                        "rest_of_season_market_score": 70,
                        "rest_of_season_minus_market_delta": 35,
                        "dynasty_market_score": 60,
                        "dynasty_minus_market_delta": 25,
                        "career_projection_score": 55,
                        "career_minus_market_delta": 20,
                        "contender_fit_score": 75,
                        "rebuilder_fit_score": 62,
                        "fit_coverage": "4/4",
                        "value_lane": "contender_edge",
                        "source_trace": "player_horizon_market_scores",
                    }
                ]
            )
            config = {"league_id": "league-1", "current_season": "2026", "context": {"roster_id": 2}}

            first = append_horizon_snapshot(path, horizons, config)
            second = append_horizon_snapshot(path, horizons, config)

            self.assertEqual(first["written"], 1)
            self.assertEqual(second["row_count"], 1)
            stored = pd.read_csv(path)
            self.assertEqual(list(stored.columns), SNAPSHOT_COLUMNS)
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored.iloc[0]["league_id"], "league-1")

    def test_accuracy_grades_observed_next_game_and_rest_of_season_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizon_snapshot_history.csv"
            snapshots = []
            usage = []
            for index, (name, score, next_points) in enumerate(
                [
                    ("Alpha Receiver", 90, 20),
                    ("Bravo Receiver", 70, 12),
                    ("Charlie Receiver", 50, 8),
                ],
                start=1,
            ):
                snapshots.append(
                    {
                        "snapshot_at": "2026-09-01T00:00:00+00:00",
                        "snapshot_scope": "league:league-1:season:2026:roster:2",
                        "season": "2026",
                        "as_of_week": "1",
                        "player_id": f"sleeper-{index}",
                        "player_name": name,
                        "position": "WR",
                        "horizon_model_version": "horizon_market_v2",
                        "market_value": 40,
                        "market_percentile": 35,
                        "next_game_market_score": score,
                        "next_game_minus_market_delta": score - 35,
                        "rest_of_season_market_score": score - 5,
                        "rest_of_season_minus_market_delta": score - 35 - 5,
                        "dynasty_market_score": score - 10,
                        "dynasty_minus_market_delta": score - 35 - 10,
                        "career_projection_score": score - 15,
                        "career_minus_market_delta": score - 35 - 15,
                        "contender_fit_score": score,
                        "rebuilder_fit_score": score - 4,
                        "fit_coverage": "4/4",
                        "value_lane": "balanced_window",
                        "source_trace": "player_horizon_market_scores",
                    }
                )
                usage.extend(
                    [
                        {"season": 2026, "week": 2, "player_id": f"nfl-{index}", "player_name": name, "position": "WR", "targets": 8, "carries": 0, "fantasy_points_ppr": next_points},
                        {"season": 2026, "week": 3, "player_id": f"nfl-{index}", "player_name": name, "position": "WR", "targets": 8, "carries": 0, "fantasy_points_ppr": next_points + 1},
                    ]
                )
            pd.DataFrame(snapshots, columns=SNAPSHOT_COLUMNS).to_csv(path, index=False)

            result = build_horizon_accuracy_table(
                path,
                pd.DataFrame(usage),
                {"current_season": "2026"},
                minimum_sample=2,
            )

            self.assertEqual(list(result.columns), ACCURACY_COLUMNS)
            self.assertEqual(set(result["horizon"]), {"next_game", "rest_of_season"})
            self.assertTrue((result["evaluation_status"] == "descriptive_evaluation").all())
            next_row = result[result["horizon"] == "next_game"].iloc[0]
            self.assertEqual(int(next_row["n_snapshots"]), 3)
            self.assertGreater(float(next_row["spearman_rank_correlation"]), 0.9)
            self.assertIn("player_usage_weekly", next_row["source_trace"])

    def test_ambiguous_name_join_is_withheld_instead_of_grading_wrong_player(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizon_snapshot_history.csv"
            snapshot = {
                "snapshot_at": "2026-09-01T00:00:00+00:00",
                "snapshot_scope": "league:league-1:season:2026:roster:2",
                "season": "2026",
                "as_of_week": "1",
                "player_id": "sleeper-1",
                "player_name": "Same Name",
                "position": "WR",
                "horizon_model_version": "horizon_market_v2",
                "market_value": 40,
                "market_percentile": 60,
                "next_game_market_score": 75,
                "next_game_minus_market_delta": 15,
                "rest_of_season_market_score": 75,
                "rest_of_season_minus_market_delta": 15,
                "dynasty_market_score": 75,
                "dynasty_minus_market_delta": 15,
                "career_projection_score": 75,
                "career_minus_market_delta": 15,
                "contender_fit_score": 75,
                "rebuilder_fit_score": 75,
                "fit_coverage": "4/4",
                "value_lane": "balanced_window",
                "source_trace": "player_horizon_market_scores",
            }
            pd.DataFrame([snapshot], columns=SNAPSHOT_COLUMNS).to_csv(path, index=False)
            usage = pd.DataFrame(
                [
                    {"season": 2026, "week": 2, "player_id": "nfl-1", "player_name": "Same Name", "position": "WR", "targets": 5, "fantasy_points_ppr": 10},
                    {"season": 2026, "week": 2, "player_id": "nfl-2", "player_name": "Same Name", "position": "WR", "targets": 5, "fantasy_points_ppr": 20},
                ]
            )

            result = build_horizon_accuracy_table(path, usage)

            self.assertTrue(result.empty)


if __name__ == "__main__":
    unittest.main()
