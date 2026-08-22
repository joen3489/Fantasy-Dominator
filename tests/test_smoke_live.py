from __future__ import annotations

import unittest

from scripts.smoke_live import validate_edition_bundle, validate_health_payload


class LiveSmokeContractTests(unittest.TestCase):
    def test_health_requires_live_auth_and_durable_schema(self) -> None:
        errors, warnings = validate_health_payload(
            {
                "ok": True,
                "auth_mode": "development",
                "auth_configuration_ready": False,
                "data_root_configured": False,
                "database_present": True,
                "database_schema_ready": False,
                "writer_api_configured": False,
            }
        )

        self.assertTrue(any("expected live" in error for error in errors))
        self.assertTrue(any("durable" in error for error in errors))
        self.assertTrue(any("schema" in error for error in errors))
        self.assertTrue(any("ANTHROPIC_API_KEY" in warning for warning in warnings))

    def test_health_accepts_ready_store_and_warns_only_for_optional_writer(self) -> None:
        errors, warnings = validate_health_payload(
            {
                "ok": True,
                "auth_mode": "live",
                "auth_configuration_ready": True,
                "data_root_configured": True,
                "database_present": True,
                "database_schema_ready": True,
                "writer_api_configured": False,
            }
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_edition_bundle_requires_facts_analysis_and_source_receipts(self) -> None:
        errors = validate_edition_bundle(
            {
                "tables": {
                    "today_priority_board": [{}],
                    "player_dossiers": [{}],
                    "source_freshness": [{}],
                    "news_source_freshness": [{}],
                    "projection_source_freshness": [{}],
                },
                "analysis": {"dailyGmBrief": "brief"},
                "draftRoom": {"schema_version": "draft_room_v1"},
            }
        )

        self.assertEqual(errors, [])

        errors = validate_edition_bundle({"tables": {}})
        self.assertIn("edition bundle has no source freshness receipt", errors)
        self.assertIn("edition bundle has no Draft Room payload", errors)


if __name__ == "__main__":
    unittest.main()
