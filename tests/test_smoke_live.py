from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from scripts.smoke_live import (
    validate_authenticated_edition,
    validate_edition_bundle,
    validate_edition_manifest,
    validate_health_payload,
    main,
    resolve_smoke_credentials,
    validate_storage_audit_payload,
)


class LiveSmokeContractTests(unittest.TestCase):
    def test_smoke_fails_closed_without_a_session_token(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "FRONT_OFFICE_SESSION_TOKEN is missing"):
                resolve_smoke_credentials()

    def test_smoke_allows_an_explicit_public_only_diagnostic(self) -> None:
        with patch.dict(os.environ, {"FRONT_OFFICE_PUBLIC_ONLY": "1"}, clear=True):
            self.assertEqual(resolve_smoke_credentials(), ("", True))

    def test_smoke_prefers_an_authenticated_token_over_public_only_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"FRONT_OFFICE_SESSION_TOKEN": "session", "FRONT_OFFICE_PUBLIC_ONLY": "1"},
            clear=True,
        ):
            self.assertEqual(resolve_smoke_credentials(), ("session", False))

    def test_smoke_entrypoint_fails_closed_before_private_requests(self) -> None:
        health = Mock(status_code=200)
        health.json.return_value = {
            "ok": True,
            "auth_mode": "live",
            "auth_configuration_ready": True,
            "public_url_ready": True,
            "data_root_configured": True,
            "database_present": True,
            "database_schema_ready": True,
            "operator_token_configured": True,
            "scheduler_enabled": True,
            "writer_api_configured": True,
        }
        login = Mock(status_code=200, text="Sign in to the Front Office")
        health.raise_for_status.return_value = None
        login.raise_for_status.return_value = None
        with patch.dict(os.environ, {}, clear=True), patch(
            "scripts.smoke_live._get", side_effect=[health, login]
        ) as get:
            with self.assertRaisesRegex(SystemExit, "Authenticated smoke not done"):
                main("https://example.test")

        self.assertEqual(get.call_count, 2)

    def test_health_requires_live_auth_and_durable_schema(self) -> None:
        errors, warnings = validate_health_payload(
            {
                "ok": True,
                "auth_mode": "development",
                "development_auth_allowed": False,
                "auth_configuration_ready": False,
                "public_url_ready": False,
                "data_root_configured": False,
                "database_present": True,
                "database_schema_ready": False,
                "operator_token_configured": False,
                "scheduler_enabled": False,
                "writer_api_configured": False,
                "writer_api_key_env": "OPENAI_API_KEY",
            }
        )

        self.assertTrue(any("expected live" in error for error in errors))
        self.assertTrue(any("durable" in error for error in errors))
        self.assertTrue(any("schema" in error for error in errors))
        self.assertTrue(any("OPENAI_API_KEY" in warning for warning in warnings))

    def test_health_accepts_explicit_private_development_auth(self) -> None:
        errors, warnings = validate_health_payload(
            {
                "ok": True,
                "auth_mode": "development",
                "development_auth_allowed": True,
                "auth_configuration_ready": True,
                "public_url_ready": True,
                "data_root_configured": True,
                "database_present": True,
                "database_schema_ready": True,
                "operator_token_configured": True,
                "scheduler_enabled": True,
                "writer_api_configured": True,
            }
        )

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_health_accepts_ready_store_and_warns_only_for_optional_writer(self) -> None:
        payload = {
            "ok": True,
            "revision": "abc123",
            "auth_mode": "live",
            "auth_configuration_ready": True,
            "public_url_ready": True,
            "data_root_configured": True,
            "database_present": True,
            "database_schema_ready": True,
            "operator_token_configured": True,
            "scheduler_enabled": True,
            "writer_api_configured": False,
        }
        with patch.dict("os.environ", {"FRONT_OFFICE_EXPECTED_REVISION": "abc123"}, clear=False):
            errors, warnings = validate_health_payload(payload)

        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_health_can_reject_a_stale_deployed_revision(self) -> None:
        payload = {
            "ok": True,
            "revision": "old",
            "auth_mode": "live",
            "auth_configuration_ready": True,
            "public_url_ready": True,
            "data_root_configured": True,
            "database_present": True,
            "database_schema_ready": True,
            "operator_token_configured": True,
            "scheduler_enabled": True,
            "writer_api_configured": True,
        }
        with patch.dict("os.environ", {"FRONT_OFFICE_EXPECTED_REVISION": "new"}, clear=False):
            errors, _ = validate_health_payload(payload)

        self.assertIn("running revision='old'; expected 'new'", errors)

    def test_health_rejects_explicit_deployment_gate_blockers(self) -> None:
        errors, _ = validate_health_payload(
            {
                "ok": True,
                "auth_mode": "live",
                "auth_configuration_ready": True,
                "public_url_ready": True,
                "data_root_configured": True,
                "database_present": True,
                "database_schema_ready": True,
                "operator_token_configured": True,
                "scheduler_enabled": True,
                "deployment_ready": False,
                "deployment_blockers": ["durable store missing"],
                "writer_api_configured": True,
            }
        )

        self.assertIn("deployment gate is not ready: durable store missing", errors)

    def test_edition_bundle_requires_facts_analysis_and_source_receipts(self) -> None:
        errors = validate_edition_bundle(
            {
                "tables": {
                    "today_priority_board": [{}],
                    "player_dossiers": [{}],
                    "player_horizon_market_scores": [{}],
                    "available_player_horizon_scores": [{}],
                    "horizon_market_movements": [{}],
                    "manager_dossiers": [{}],
                    "manager_season_history": [{}],
                    "team_asset_inventory": [{}],
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

        shallow = validate_edition_bundle(
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
        self.assertIn("edition bundle is missing player_horizon_market_scores", shallow)
        self.assertIn("edition bundle is missing horizon_market_movements", shallow)
        self.assertIn("edition bundle is missing manager_dossiers", shallow)

    def test_authenticated_edition_requires_revision_league_and_verified_roster(self) -> None:
        receipts = {
            key: {
                "mode": "deterministic_template",
                "reporter_id": key,
                "structured": {
                    "headline": key,
                    "lede": "A grounded fallback lead.",
                    "thesis": "Use the evidence.",
                    "what_changed": "The receipt boundary is explicit.",
                    "action": "Open the Data Room.",
                    "visual_brief": "Use accessible HTML evidence rails.",
                    "fallback_schema_version": "deterministic_fallback_v2",
                },
            }
            for key in ("daily_brief", "team_report", "market_watch", "horizon_watch", "trade_desk", "manager_intel")
        }
        payload = {
            "leagueId": "alpha",
            "sourceRevision": "new",
            "identityReceipt": {"status": "verified", "roster_id": 2},
            "tables": {
                "today_priority_board": [{}],
                "player_dossiers": [{}],
                "player_horizon_market_scores": [{}],
                "available_player_horizon_scores": [{}],
                "horizon_market_movements": [{}],
                "manager_dossiers": [{}],
                "manager_season_history": [{}],
                "team_asset_inventory": [{}],
                "source_freshness": [{}],
                "news_source_freshness": [{}],
                "projection_source_freshness": [{}],
            },
            "analysis": {"dailyGmBrief": "brief", "articleReceipts": receipts},
            "draftRoom": {"schema_version": "draft_room_v1"},
        }

        self.assertEqual(validate_authenticated_edition(payload, "new", "alpha"), [])
        errors = validate_authenticated_edition(payload, "old", "beta")
        self.assertIn("edition bundle source revision='new'; expected 'old'", errors)
        self.assertIn("edition bundle league_id='alpha'; expected 'beta'", errors)

        errors = validate_authenticated_edition({**payload, "identityReceipt": {"status": "unverified"}}, "new", "alpha")
        self.assertIn("edition bundle does not carry a verified Sleeper roster receipt", errors)
        self.assertIn("edition bundle identity receipt has no exact roster_id", errors)

        stale = {**payload, "analysis": {**payload["analysis"], "articleReceipts": {**receipts, "daily_brief": {**receipts["daily_brief"], "structured": {**receipts["daily_brief"]["structured"], "fallback_schema_version": "old"}}}}}
        self.assertIn("publication receipt daily_brief has stale fallback schema", validate_authenticated_edition(stale, "new", "alpha"))

        reviewed = {**payload, "analysis": {**payload["analysis"], "articleReceipts": {**receipts, "daily_brief": {**receipts["daily_brief"], "editorial_review": {"mode": "llm", "status": "approved", "decision": "modify"}}}}}
        self.assertEqual(validate_authenticated_edition(reviewed, "new", "alpha"), [])
        invalid_review = {**reviewed, "analysis": {**reviewed["analysis"], "articleReceipts": {**reviewed["analysis"]["articleReceipts"], "daily_brief": {**reviewed["analysis"]["articleReceipts"]["daily_brief"], "editorial_review": {"mode": "llm", "status": "maybe", "decision": "approve"}}}}}
        self.assertIn("unknown editorial review status", " ".join(validate_authenticated_edition(invalid_review, "new", "alpha")))

    def test_edition_manifest_requires_deployed_revision_and_roster_receipt(self) -> None:
        self.assertEqual(
            validate_edition_manifest(
                {"sourceRevision": "new", "identityReceipt": {"roster_id": 2}},
                "new",
            ),
            [],
        )
        errors = validate_edition_manifest({"sourceRevision": "old", "identityReceipt": {}}, "new")
        self.assertIn("edition manifest source revision='old'; expected 'new'", errors)
        self.assertIn("edition manifest identity receipt has no exact roster_id", errors)

    def test_storage_audit_requires_current_identity_and_league(self) -> None:
        self.assertEqual(
            validate_storage_audit_payload(
                {
                    "database_schema_ready": True,
                    "current_user_present": True,
                    "current_user_leagues": 2,
                    "content_artifacts": 5,
                }
            ),
            [],
        )
        errors = validate_storage_audit_payload(
            {
                "database_schema_ready": True,
                "current_user_present": True,
                "current_user_leagues": 0,
            }
        )
        self.assertIn("storage audit finds no leagues for the authenticated identity", errors)


if __name__ == "__main__":
    unittest.main()
