from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.validate_local_data import HORIZON_MOVEMENT_COLUMNS, audit_local_data


REQUIRED_TABLES = {
    "refresh_metadata": ["generated_at", "current_season", "analysis_artifacts_status"],
    "news_events": ["source", "event_id", "published_at", "source_trace"],
    "news_source_freshness": ["source", "dataset", "status", "checked_at"],
    "source_freshness": ["source", "dataset", "status", "checked_at"],
    "projection_source_freshness": ["source", "dataset", "status", "checked_at"],
    "today_priority_board": ["source_trace"],
    "player_dossiers": ["source_trace"],
    "league_news_impact": ["source_trace"],
    "player_signal_scores": ["source_trace"],
    "player_projection_season": ["season", "player_id", "player_name", "position", "team", "availability_scope", "current_availability_status", "availability_note", "projected_ppg", "projection_method", "projection_confidence", "source_trace", "projection_note"],
    "player_projection_weekly": ["season", "week", "player_id", "player_name", "position", "team", "availability_scope", "current_availability_status", "availability_note", "projected_fantasy_points", "projection_method", "projection_confidence", "source_trace"],
    "projection_source_components": ["season", "player_id", "player_name", "position", "team", "availability_scope", "current_availability_status", "availability_note", "source", "projected_fantasy_points", "projected_ppg", "source_confidence", "source_trace", "checked_at"],
    "player_horizon_market_scores": ["league_id", "horizon_model_version", "horizon_score_basis", "market_value", "market_percentile", "next_game_status", "next_game_matchup_adjustment_status", "next_game_minus_market_delta", "rest_of_season_status", "rest_of_season_minus_market_delta", "rest_of_season_minus_next_game_delta", "dynasty_status", "dynasty_minus_market_delta", "dynasty_minus_rest_of_season_delta", "career_projection_status", "career_projection_basis", "career_history_join_method", "career_history_source_player_id", "career_history_status", "career_history_seasons", "career_history_games", "career_history_ppg", "career_history_latest_season", "career_minus_market_delta", "career_minus_dynasty_delta", "fit_coverage", "fit_basis", "evidence", "risk", "confidence", "source_trace"],
}

REQUIRED_TABLES["player_horizon_market_scores"] = REQUIRED_TABLES["player_horizon_market_scores"] + [
    "market_source_count",
    "market_disagreement_score",
    "market_source_confidence",
    "next_game_market_score",
    "rest_of_season_market_score",
    "dynasty_market_score",
    "career_projection_score",
    "contender_fit_score",
    "rebuilder_fit_score",
    "value_lane",
]


class LocalDataValidationTests(unittest.TestCase):
    def _fixture(self, root: Path, *, valid_analysis: bool = True) -> tuple[Path, Path]:
        processed = root / "processed"
        analysis = root / "analysis"
        processed.mkdir()
        analysis.mkdir()
        generated_at = "2026-08-22T12:00:00+00:00"
        for table, columns in REQUIRED_TABLES.items():
            rows = [{column: "value" for column in columns}]
            if table == "refresh_metadata":
                rows[0] = {"generated_at": generated_at, "current_season": "2026", "analysis_artifacts_status": "generated"}
            elif table == "news_events":
                rows[0] = {"source": "rotowire_rss", "event_id": "news-1", "published_at": generated_at, "source_trace": "https://example.test/news-1"}
            elif table.endswith("freshness"):
                rows[0] = {"source": "test_source", "dataset": table, "status": "refreshed", "checked_at": generated_at}
            elif table == "player_horizon_market_scores":
                rows[0] = {column: "horizon" for column in columns}
                rows[0].update(
                    {
                        "horizon_model_version": "horizon_market_v2",
                        "horizon_score_basis": "position-relative percentile score",
                        "market_value": "10",
                        "market_percentile": "50",
                        "market_source_count": "1",
                        "market_disagreement_score": "0",
                        "market_source_confidence": "medium",
                        "next_game_market_score": "50",
                        "next_game_minus_market_delta": "0",
                        "rest_of_season_market_score": "55",
                        "rest_of_season_minus_market_delta": "5",
                        "dynasty_market_score": "60",
                        "dynasty_minus_market_delta": "10",
                        "career_projection_score": "65",
                        "career_minus_market_delta": "15",
                        "contender_fit_score": "53",
                        "rebuilder_fit_score": "62",
                        "rest_of_season_minus_next_game_delta": "5",
                        "dynasty_minus_rest_of_season_delta": "5",
                        "career_minus_dynasty_delta": "5",
                        "fit_coverage": "4/4",
                        "value_lane": "balanced_window",
                    }
                )
            elif table in {"player_projection_season", "player_projection_weekly", "projection_source_components"}:
                rows[0] = {column: "value" for column in columns}
                rows[0].update(
                    {
                        "availability_scope": "current_season_snapshot",
                        "current_availability_status": "available",
                        "availability_note": "No current Sleeper injury flag; baseline projection",
                    }
                )
                if table == "player_projection_season":
                    rows[0]["projection_note"] = "fixture projection"
            else:
                rows[0] = {"source_trace": "source_table"}
            with (processed / f"{table}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        (analysis / "analysis_validation.json").write_text(
            json.dumps(
                {
                    "generation_mode": "deterministic_template",
                    "items": [{"valid": valid_analysis, "errors": [] if valid_analysis else ["bad"]}],
                }
            ),
            encoding="utf-8",
        )
        return processed, analysis

    def test_current_facts_and_disabled_optional_source_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            source_path = processed / "source_freshness.csv"
            with source_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write("fantasy_nerds,weekly_projections,disabled:api_key_missing,now\n")

            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            )

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["news_event_count"], 1)
        self.assertTrue(any("explicitly disabled" in warning for warning in audit["warnings"]))

    def test_projection_contract_cannot_drop_availability_context(self) -> None:
        """Design source: docs/data_contract.md; baselines need explicit current availability."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            projection_path = processed / "player_projection_season.csv"
            rows = list(csv.DictReader(projection_path.read_text(encoding="utf-8").splitlines()))
            fieldnames = [
                column
                for column in REQUIRED_TABLES["player_projection_season"]
                if column != "current_availability_status"
            ]
            with projection_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(
                    {
                        column: row.get(column, "")
                        for column in fieldnames
                    }
                    for row in rows
                )

            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            )

        self.assertFalse(audit["ok"])
        self.assertTrue(any("player_projection_season.csv is missing columns" in error for error in audit["errors"]))

    def test_projection_contract_cannot_label_unsigned_history_without_a_signing_caveat(self) -> None:
        """Design source: docs/data_contract.md; status and caveat must agree."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            projection_path = processed / "player_projection_season.csv"
            rows = list(csv.DictReader(projection_path.read_text(encoding="utf-8").splitlines()))
            rows[0].update(
                {
                    "current_availability_status": "no_current_nfl_team",
                    "availability_note": "availability limited",
                    "projection_note": "historical production evidence",
                }
            )
            with projection_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=REQUIRED_TABLES["player_projection_season"])
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            )

        self.assertFalse(audit["ok"])
        self.assertTrue(any("without a signing caveat" in error for error in audit["errors"]))

    def test_invalid_analysis_and_duplicate_untraced_news_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary), valid_analysis=False)
            with (processed / "news_events.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=REQUIRED_TABLES["news_events"])
                writer.writeheader()
                writer.writerow({"source": "sleeper", "event_id": "duplicate", "published_at": "now", "source_trace": ""})
                writer.writerow({"source": "sleeper", "event_id": "duplicate", "published_at": "now", "source_trace": ""})

            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            )

        self.assertFalse(audit["ok"])
        self.assertTrue(any("duplicate event IDs" in error for error in audit["errors"]))
        self.assertTrue(any("no source traces" in error for error in audit["errors"]))
        self.assertTrue(any("invalid analysis" in error for error in audit["errors"]))

    def test_current_news_cannot_attach_to_completed_season(self) -> None:
        """Design source: docs/data_contract.md; current news is not historical evidence."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            impact_path = processed / "league_news_impact.csv"
            rows = list(csv.DictReader(impact_path.read_text(encoding="utf-8").splitlines()))
            rows[0].update({"season": "2025", "source_trace": "news-1"})
            with impact_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            )

        self.assertFalse(audit["ok"])
        self.assertTrue(any("attaches current news to non-current season" in error for error in audit["errors"]))

    def test_freshness_margin_warns_before_the_gate_fails(self) -> None:
        # Design source: docs/data_contract.md, source freshness contract; a
        # passing gate must still expose proximity to stale data.
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 23, 22, 0, tzinfo=timezone.utc),
            )

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["freshness_margin_hours"], 2.0)
        self.assertTrue(any("freshness margin" in warning for warning in audit["warnings"]))

    def test_player_history_identity_receipt_reports_resolution_and_trade_balance(self) -> None:
        """Encodes docs/data_contract.md's player identity and acquired/sold contract."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            history_path = processed / "player_transaction_history.csv"
            fields = ["player_id", "identity_method", "player_name", "event_type", "direction", "source_trace"]
            with history_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(
                    [
                        {"player_id": "101", "identity_method": "source_id", "player_name": "Alpha", "event_type": "trade", "direction": "acquired", "source_trace": "trades"},
                        {"player_id": "101", "identity_method": "source_id", "player_name": "Alpha", "event_type": "trade", "direction": "sold", "source_trace": "trades"},
                        {"player_id": "", "identity_method": "unmatched_name", "player_name": "Legacy Player", "event_type": "waiver_add", "direction": "added", "source_trace": "waivers"},
                    ]
                )

            audit = audit_local_data(
                processed,
                analysis,
                now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc),
            )

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["player_history_identity"]["resolved_rows"], 2)
        self.assertEqual(audit["player_history_identity"]["unresolved_rows"], 1)
        self.assertEqual(audit["player_history_identity"]["trade_direction_counts"], {"acquired": 1, "sold": 1})
        self.assertTrue(any("unresolved name matches" in warning for warning in audit["warnings"]))

    def test_player_history_identity_contradiction_fails_closed(self) -> None:
        """A source_id row without an ID is a contract failure, not a recoverable label."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            history_path = processed / "player_transaction_history.csv"
            fields = ["player_id", "identity_method", "player_name", "event_type", "direction", "source_trace"]
            with history_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"player_id": "", "identity_method": "source_id", "player_name": "Broken", "event_type": "trade", "direction": "received", "source_trace": "trades"})

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("without player_id" in error for error in audit["errors"]))
        self.assertTrue(any("invalid trade direction" in error for error in audit["errors"]))

    def test_horizon_history_receipt_fails_closed_when_status_and_id_disagree(self) -> None:
        """Design source: docs/data_contract.md; matched history needs an auditable source ID."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            horizon_path = processed / "player_horizon_market_scores.csv"
            rows = list(csv.DictReader(horizon_path.read_text(encoding="utf-8").splitlines()))
            rows[0].update(
                {
                    "player_name": "Broken History Receipt",
                    "career_history_status": "matched",
                    "career_history_join_method": "normalized_name_position_unique_source_id",
                    "career_history_source_player_id": "",
                    "career_history_games": "12",
                    "career_history_seasons": "2",
                    "career_history_ppg": "14.2",
                }
            )
            with horizon_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("without career_history_source_player_id" in error for error in audit["errors"]))

    def test_horizon_ambiguous_receipt_with_source_id_fails_closed(self) -> None:
        """An ambiguous bridge cannot retain a source ID that looks canonical."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            horizon_path = processed / "player_horizon_market_scores.csv"
            rows = list(csv.DictReader(horizon_path.read_text(encoding="utf-8").splitlines()))
            rows[0].update({"career_history_status": "ambiguous", "career_history_source_player_id": "nfl-ambiguous"})
            with horizon_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("ambiguous career history with a source player ID" in error for error in audit["errors"]))

    def test_horizon_score_receipt_fails_on_scale_and_transition_contradictions(self) -> None:
        """Design source: docs/data_contract.md; position-relative scores and deltas must reconcile."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            horizon_path = processed / "player_horizon_market_scores.csv"
            rows = list(csv.DictReader(horizon_path.read_text(encoding="utf-8").splitlines()))
            rows[0].update(
                {
                    "player_name": "Contradictory Horizon Row",
                    "next_game_market_score": "101",
                    "rest_of_season_market_score": "55",
                    "rest_of_season_minus_next_game_delta": "5",
                    "fit_coverage": "4/4",
                }
            )
            with horizon_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("outside the 0-100 percentile scale" in error for error in audit["errors"]))
        self.assertTrue(any("fit_coverage disagrees" in error for error in audit["errors"]))

    def test_horizon_price_delta_receipt_fails_when_market_comparison_does_not_reconcile(self) -> None:
        """Design source: docs/data_contract.md; repricing leads must equal clock minus market percentile."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            horizon_path = processed / "player_horizon_market_scores.csv"
            rows = list(csv.DictReader(horizon_path.read_text(encoding="utf-8").splitlines()))
            rows[0]["next_game_minus_market_delta"] = "9"
            with horizon_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("next_game_minus_market_delta does not reconcile" in error for error in audit["errors"]))

    def test_horizon_snapshot_history_and_accuracy_receipts_are_validated(self) -> None:
        """Design source: docs/data_contract.md; feedback history is dated and bounded."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            snapshot_fields = [
                "snapshot_at", "snapshot_scope", "season", "as_of_week", "player_id", "player_name",
                "league_id", "position", "horizon_model_version", "market_value", "market_percentile",
                "market_source_count", "market_disagreement_score", "market_source_confidence",
                "next_game_market_score", "next_game_minus_market_delta", "rest_of_season_market_score",
                "rest_of_season_minus_market_delta", "rest_of_season_minus_next_game_delta",
                "dynasty_market_score", "dynasty_minus_market_delta", "dynasty_minus_rest_of_season_delta",
                "career_projection_score", "career_minus_market_delta", "career_minus_dynasty_delta",
                "contender_fit_score", "rebuilder_fit_score",
                "fit_coverage", "value_lane", "source_trace",
            ]
            with (processed / "horizon_snapshot_history.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=snapshot_fields)
                writer.writeheader()
                writer.writerow({
                    "snapshot_at": "2026-08-22T12:00:00+00:00", "snapshot_scope": "league:l:season:2026:roster:2",
                    "season": "2026", "league_id": "l", "as_of_week": "1", "player_id": "p1", "player_name": "Alpha",
                    "position": "WR", "horizon_model_version": "horizon_market_v2",
                    "market_value": "40", "market_percentile": "35",
                    "next_game_market_score": "50", "next_game_minus_market_delta": "15",
                    "rest_of_season_market_score": "55", "rest_of_season_minus_market_delta": "20",
                    "dynasty_market_score": "60", "dynasty_minus_market_delta": "25",
                    "career_projection_score": "65", "career_minus_market_delta": "30",
                    "contender_fit_score": "53",
                    "rebuilder_fit_score": "62", "fit_coverage": "4/4", "value_lane": "balanced_window",
                    "rest_of_season_minus_next_game_delta": "5", "dynasty_minus_rest_of_season_delta": "5",
                    "career_minus_dynasty_delta": "5",
                    "source_trace": "player_horizon_market_scores",
                })
            accuracy_fields = [
                "horizon_model_version", "horizon", "score_field", "position", "outcome", "n_snapshots",
                "n_player_snapshots", "spearman_rank_correlation", "cohort_mean_outcome", "top_quartile_mean_outcome",
                "top_quartile_lift", "evaluation_status", "confidence", "evidence", "source_trace",
            ]
            with (processed / "horizon_score_accuracy.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=accuracy_fields)
                writer.writeheader()
                writer.writerow({field: "value" for field in accuracy_fields} | {
                    "horizon": "next_game", "score_field": "next_game_market_score", "spearman_rank_correlation": "0.25",
                    "cohort_mean_outcome": "10", "top_quartile_mean_outcome": "12", "top_quartile_lift": "1.2",
                    "n_snapshots": "1", "n_player_snapshots": "1", "evaluation_status": "insufficient_history",
                })

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["horizon_snapshot_history"]["row_count"], 1)
        self.assertEqual(audit["horizon_score_accuracy"]["status_counts"], {"insufficient_history": 1})

    def test_horizon_movement_receipt_reconciles_and_fails_closed(self) -> None:
        """Design source: docs/data_contract.md; movement is a receipt over dated endpoints."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            movement_fields = sorted(HORIZON_MOVEMENT_COLUMNS)
            movement = {field: "" for field in movement_fields}
            movement.update(
                {
                    "snapshot_scope": "league:l:season:2026:roster:2",
                    "league_id": "l",
                    "season": "2026",
                    "player_id": "p1",
                    "player_name": "Alpha",
                    "position": "WR",
                    "horizon_model_version": "horizon_market_v2",
                    "prior_snapshot_at": "2026-08-21T12:00:00+00:00",
                    "current_snapshot_at": "2026-08-22T12:00:00+00:00",
                    "prior_as_of_week": "1",
                    "current_as_of_week": "2",
                    "prior_market_value": "10",
                    "market_value": "12",
                    "market_value_delta": "2",
                    "prior_value_lane": "balanced_window",
                    "value_lane": "balanced_window",
                    "value_lane_change": "unchanged",
                    "movement_status": "changed",
                    "evidence": "exact earlier snapshot comparison",
                    "source_trace": "horizon_snapshot_history.csv; player_horizon_market_scores",
                }
            )
            with (processed / "horizon_market_movements.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=movement_fields)
                writer.writeheader()
                writer.writerow(movement)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

            self.assertTrue(audit["ok"])
            self.assertEqual(audit["horizon_market_movements"]["row_count"], 1)

            movement["market_value_delta"] = "3"
            with (processed / "horizon_market_movements.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=movement_fields)
                writer.writeheader()
                writer.writerow(movement)
            invalid_audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(invalid_audit["ok"])
        self.assertTrue(any("market_value_delta that does not reconcile" in error for error in invalid_audit["errors"]))

    def test_horizon_market_receipt_fails_closed_when_partial_or_malformed(self) -> None:
        """Design source: docs/data_contract.md; market quality is a complete receipt or unavailable."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            horizon_path = processed / "player_horizon_market_scores.csv"
            rows = list(csv.DictReader(horizon_path.read_text(encoding="utf-8").splitlines()))
            rows[0].update({
                "player_name": "Malformed Market Receipt",
                "market_source_count": "two",
                "market_disagreement_score": "-1",
                "market_source_confidence": "certain",
            })
            partial = rows[0].copy()
            partial.update({
                "player_name": "Partial Market Receipt",
                "market_source_count": "",
                "market_disagreement_score": "0",
                "market_source_confidence": "medium",
            })
            rows.append(partial)
            with horizon_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("invalid market_source_count" in error for error in audit["errors"]))
        self.assertTrue(any("invalid market_disagreement_score" in error for error in audit["errors"]))
        self.assertTrue(any("unsupported market_source_confidence" in error for error in audit["errors"]))
        self.assertTrue(any("incomplete market quality receipt" in error for error in audit["errors"]))

    def test_available_horizon_requires_market_quality_receipt(self) -> None:
        """Design source: docs/data_contract.md; available rows require an auditable price anchor."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            fields = [
                "league_id", "availability_status", "identity_status", "player_id", "player_name",
                "market_value", "market_source_count", "market_disagreement_score",
                "market_source_confidence", "fit_coverage", "evidence", "risk", "confidence", "source_trace",
            ]
            with (processed / "available_player_horizon_scores.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "league_id": "league-1", "availability_status": "not_rostered_in_selected_league",
                    "identity_status": "sleeper_id", "player_id": "p1", "player_name": "Partial Available",
                    "market_value": "25", "market_source_count": "1", "market_disagreement_score": "",
                    "market_source_confidence": "medium", "fit_coverage": "4/4", "evidence": "market",
                    "risk": "verify", "confidence": "medium", "source_trace": "market",
                })

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("available_player_horizon_scores.csv has an incomplete market quality receipt" in error for error in audit["errors"]))

    def test_horizon_snapshot_duplicate_key_fails_closed(self) -> None:
        """An append-only feedback log must not silently retain duplicate beliefs."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            fields = [
                "snapshot_at", "snapshot_scope", "season", "league_id", "as_of_week", "player_id", "player_name",
                "position", "horizon_model_version", "market_value", "market_percentile",
                "market_source_count", "market_disagreement_score", "market_source_confidence",
                "next_game_market_score", "next_game_minus_market_delta", "rest_of_season_market_score",
                "rest_of_season_minus_market_delta", "rest_of_season_minus_next_game_delta",
                "dynasty_market_score", "dynasty_minus_market_delta", "dynasty_minus_rest_of_season_delta",
                "career_projection_score", "career_minus_market_delta", "career_minus_dynasty_delta",
                "contender_fit_score", "rebuilder_fit_score",
                "fit_coverage", "value_lane", "source_trace",
            ]
            row = {field: "" for field in fields}
            row.update({
                "snapshot_at": "2026-08-22T12:00:00+00:00", "snapshot_scope": "scope", "season": "2026",
                "league_id": "l", "as_of_week": "1", "player_id": "p1", "player_name": "Alpha", "position": "WR",
                "horizon_model_version": "horizon_market_v2", "next_game_market_score": "50",
                "rest_of_season_market_score": "55", "dynasty_market_score": "60", "career_projection_score": "65",
                "contender_fit_score": "53", "rebuilder_fit_score": "62", "fit_coverage": "4/4",
                "value_lane": "balanced_window", "source_trace": "horizon",
            })
            with (processed / "horizon_snapshot_history.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows([row, row])

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("duplicate dated player keys" in error for error in audit["errors"]))

    def test_manager_transaction_lanes_report_receipt(self) -> None:
        """Design source: docs/data_contract.md; manager lanes need scope and trace."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            lane_path = processed / "manager_transaction_preferences.csv"
            fields = [
                "owner_id", "roster_id", "position_group", "acquired_count", "sold_count",
                "horizon_coverage", "history_status", "confidence", "evidence", "source_trace",
            ]
            with lane_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "owner_id": "owner-a", "roster_id": "2", "position_group": "RB",
                    "acquired_count": "4", "sold_count": "1", "horizon_coverage": "acquired 2/4; sold 1/1",
                    "history_status": "supported", "confidence": "high", "evidence": "observed", "source_trace": "history;horizon",
                })

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["manager_transaction_preferences"]["row_count"], 1)
        self.assertEqual(audit["manager_transaction_preferences"]["history_status_counts"], {"supported": 1})

    def test_counterparty_asset_interest_reports_receipt_and_rejects_self_target(self) -> None:
        """Design source: docs/data_contract.md; audience rows must remain cross-roster and bounded."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            interest_path = processed / "counterparty_asset_interest.csv"
            fields = [
                "active_roster_id", "asset_id", "target_roster_id", "transaction_lane_read",
                "conversation_fit_score", "conversation_fit_label", "evidence", "risk", "confidence", "source_trace",
            ]
            with interest_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "active_roster_id": "2", "asset_id": "player-1", "target_roster_id": "8",
                    "transaction_lane_read": "observed acquisition lane", "conversation_fit_score": "72",
                    "conversation_fit_label": "strong_conversation_fit", "evidence": "observed",
                    "risk": "not intent", "confidence": "high", "source_trace": "interest",
                })

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["counterparty_asset_interest"]["row_count"], 1)
        self.assertEqual(audit["counterparty_asset_interest"]["confidence_counts"], {"high": 1})

    def test_counterparty_asset_interest_self_target_fails_closed(self) -> None:
        """The audience layer cannot turn our own roster into its counterparty."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            interest_path = processed / "counterparty_asset_interest.csv"
            fields = [
                "active_roster_id", "asset_id", "target_roster_id", "transaction_lane_read",
                "conversation_fit_score", "conversation_fit_label", "evidence", "risk", "confidence", "source_trace",
            ]
            with interest_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "active_roster_id": "2", "asset_id": "player-1", "target_roster_id": "2",
                    "transaction_lane_read": "observed acquisition lane", "conversation_fit_score": "72",
                    "conversation_fit_label": "strong_conversation_fit", "evidence": "observed",
                    "risk": "not intent", "confidence": "high", "source_trace": "interest",
                })

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("active roster as its own target" in error for error in audit["errors"]))

    def test_counterparty_horizon_context_must_match_canonical_row(self) -> None:
        """Design source: AGENTS.md; downstream trade context cannot become a second source of truth."""
        with tempfile.TemporaryDirectory() as temporary:
            processed, analysis = self._fixture(Path(temporary))
            horizon_path = processed / "player_horizon_market_scores.csv"
            horizon_rows = list(csv.DictReader(horizon_path.read_text(encoding="utf-8").splitlines()))
            horizon_rows[0].update({"player_id": "p1", "roster_id": "2", "player_name": "Alpha"})
            with horizon_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=horizon_rows[0].keys())
                writer.writeheader()
                writer.writerows(horizon_rows)

            context_fields = [
                "horizon_market_percentile", "next_game_market_score", "rest_of_season_market_score",
                "dynasty_market_score", "career_projection_score", "next_game_minus_market_delta",
                "rest_of_season_minus_market_delta", "dynasty_minus_market_delta", "career_minus_market_delta",
                "rest_of_season_minus_next_game_delta", "dynasty_minus_rest_of_season_delta", "career_minus_dynasty_delta",
                "horizon_market_disagreement_window", "horizon_market_disagreement_delta",
                "horizon_market_disagreement_magnitude", "horizon_market_disagreement_read",
            ]
            edge_fields = ["target_roster_id", "player_id", *context_fields]
            edge = {field: horizon_rows[0].get(field, "") for field in context_fields}
            edge.update({"target_roster_id": "2", "player_id": "p1", "next_game_market_score": "51"})
            with (processed / "counterparty_trade_edges.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=edge_fields)
                writer.writeheader()
                writer.writerow(edge)

            audit = audit_local_data(processed, analysis, now=datetime(2026, 8, 22, 13, 0, tzinfo=timezone.utc))

        self.assertFalse(audit["ok"])
        self.assertTrue(any("next_game_market_score does not match canonical" in error for error in audit["errors"]))


if __name__ == "__main__":
    unittest.main()
