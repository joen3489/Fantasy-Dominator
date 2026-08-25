from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.validate_local_data import audit_local_data


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
}


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


if __name__ == "__main__":
    unittest.main()
