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


if __name__ == "__main__":
    unittest.main()
