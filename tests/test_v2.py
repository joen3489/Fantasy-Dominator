from __future__ import annotations

"""Focused tests for the multi-league path and orchestration layer."""

import inspect
import csv
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth, db
from app import main as app_main
from app.main import _source_receipt_view, create_app
from scripts import refresh_all
from src.attention import (
    AttentionItem,
    build_league_attention,
    build_user_attention,
    deadline_items,
    load_attention,
    roster_health_items,
    save_attention,
)
from src.league_paths import LeaguePaths
from src.league_registry import classify_league, discover_leagues


def _empty_data_quality() -> dict:
    return {
        "player_history_identity": {
            "status": "empty",
            "valid": True,
            "row_count": 0,
            "resolved_rows": 0,
            "unresolved_rows": 0,
            "resolved_rate": 0.0,
            "identity_method_counts": {},
            "trade_direction_counts": {},
            "trade_direction_status": "not_applicable",
        }
    }


def _write_complete_bundle(site_dir: Path, html: str, editorial: dict | None = None) -> None:
    """Create the smallest valid reader bundle for route/readiness tests."""

    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    data_quality = _empty_data_quality()
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    # Keep the app payload empty so generic route tests continue to model the
    # legacy migration fixture; production-generated bundles are checked for
    # the receipt when a deployment revision is present.
    (data_dir / "app_bundle.json").write_text("{}", encoding="utf-8")
    (data_dir / "editorial_issue.json").write_text(json.dumps(editorial or {}), encoding="utf-8")
    (data_dir / "draft_room.json").write_text("{}", encoding="utf-8")
    (data_dir / "media_manifest.json").write_text(json.dumps({"schema_version": "media_manifest_v1", "assets": []}), encoding="utf-8")
    (data_dir / "manifest.json").write_text(json.dumps({"auditTables": {}, "dataQuality": data_quality}), encoding="utf-8")


def _write_writer_brief(
    analysis_dir: Path,
    text: str,
    *,
    persona_id: str = "scout",
    mode: str = "deterministic_template",
    team_name: str = "",
) -> None:
    """Write the private markdown artifact surfaced by the headquarters preview."""

    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "daily_gm_brief.md").write_text(
        "\n".join(
            [
                "---",
                "artifact_type: daily_gm_brief",
                "generated_at: 2026-08-22T19:19:09+00:00",
                f"model_mode: {mode}",
                f"reporter_persona: {persona_id}",
                *( [f"team_name: {team_name}"] if team_name else [] ),
                "---",
                "",
                f"# Daily GM Brief: {team_name or 'Private Team'}",
                "",
                text,
                "",
                "## Evidence",
                "",
                "- Confirmed league signal.",
            ]
        ),
        encoding="utf-8",
    )


class MultiLeagueLayerTests(unittest.TestCase):
    def test_classify_league_handles_known_and_missing_settings(self) -> None:
        self.assertEqual(classify_league({"settings": {"type": 2}}), "dynasty")
        self.assertEqual(classify_league({"settings": {"type": 1}}), "dynasty")
        self.assertEqual(classify_league({"settings": {"type": 0}}), "redraft")
        self.assertEqual(classify_league({"settings": {"best_ball": 1, "type": 2}}), "best_ball")
        self.assertEqual(classify_league({}), "redraft")

    def test_league_paths_for_league_layout_and_ensure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            leagues_root = Path(tmp) / "data" / "leagues"
            with patch("src.league_paths.LEAGUES_ROOT", leagues_root):
                paths = LeaguePaths.for_league("123")
                self.assertEqual(paths.root, leagues_root / "123")
                self.assertEqual(paths.raw_dir, leagues_root / "123" / "raw")
                self.assertEqual(paths.processed_dir, leagues_root / "123" / "processed")
                self.assertEqual(paths.analysis_dir, leagues_root / "123" / "analysis")
                self.assertEqual(paths.site_dir, leagues_root / "123" / "site")
                self.assertEqual(paths.operator_inbox_dir, leagues_root / "123" / "operator" / "inbox")

                paths.ensure()

                for path in (
                    paths.raw_dir,
                    paths.processed_dir,
                    paths.cache_dir,
                    paths.reports_dir,
                    paths.site_dir,
                    paths.analysis_dir,
                    paths.operator_inbox_dir,
                    paths.operator_outbox_dir,
                    paths.operator_status_dir,
                ):
                    self.assertTrue(path.is_dir())

    def test_discover_leagues_resolves_user_roster_and_type(self) -> None:
        api = MagicMock()
        api.user.return_value = {"user_id": "user-1"}
        api.user_leagues.return_value = [
            {
                "league_id": "league-a",
                "name": "Alpha",
                "settings": {"type": 2},
                "total_rosters": 12,
            },
            {
                "league_id": "league-b",
                "name": "Beta",
                "settings": {"best_ball": 1},
                "total_rosters": 10,
            },
        ]
        api.rosters.side_effect = [
            [{"roster_id": 4, "owner_id": "other"}, {"roster_id": 7, "owner_id": "user-1"}],
            [{"roster_id": 1, "owner_id": "other"}],
        ]

        entries = discover_leagues(api, "joe", "2026")

        self.assertEqual(
            entries,
            [
                {
                    "league_id": "league-a",
                    "name": "Alpha",
                    "season": "2026",
                    "league_type": "dynasty",
                    "roster_id": 7,
                    "sleeper_user_id": "user-1",
                    "identity_status": "verified_roster_match",
                    "total_rosters": 12,
                },
                {
                    "league_id": "league-b",
                    "name": "Beta",
                    "season": "2026",
                    "league_type": "best_ball",
                    "roster_id": None,
                    "sleeper_user_id": "user-1",
                    "identity_status": "unverified",
                    "total_rosters": 10,
                },
            ],
        )
        api.user.assert_called_once_with("joe")
        api.user_leagues.assert_called_once_with("user-1", "2026")

    def test_refresh_user_records_statuses_and_isolates_failure(self) -> None:
        entries = [
            {"league_id": "ok", "league_type": "dynasty", "roster_id": 2},
            {"league_id": "bad", "league_type": "redraft", "roster_id": 3},
            {"league_id": "skip", "league_type": "best_ball", "roster_id": 4},
        ]

        def fake_main(**kwargs: object) -> None:
            if kwargs["league_id"] == "bad":
                raise RuntimeError("boom")

        mocked_main = MagicMock(side_effect=fake_main)
        with patch.multiple(
            refresh_all,
            discover_leagues=MagicMock(return_value=entries),
            save_registry=MagicMock(),
            main=mocked_main,
        ):
            statuses = refresh_all.refresh_user("joe", "2026", force=True)

        self.assertEqual(statuses["ok"]["state"], "complete")
        self.assertEqual(statuses["ok"]["league_type"], "dynasty")
        self.assertEqual(statuses["bad"]["state"], "failed")
        self.assertIn("boom", statuses["bad"]["message"])
        self.assertNotIn("skip", statuses)
        self.assertEqual(mocked_main.call_count, 2)

    def test_refresh_user_passes_private_manager_profiles_into_scoped_context(self) -> None:
        entries = [{"league_id": "league-a", "league_type": "dynasty", "roster_id": 2, "season": "2026"}]
        manager_profile = {"roster_id": 8, "manager_name": "Observed Rival", "trade_style": "pick buyer"}
        with patch.multiple(
            refresh_all,
            discover_leagues=MagicMock(return_value=entries),
            save_registry=MagicMock(),
        ):
            with patch.object(refresh_all, "main", MagicMock()) as mocked_main:
                with patch.object(db, "init_db"), patch.object(db, "set_sleeper_account"), patch.object(db, "start_refresh_run", return_value=None):
                    with patch.object(db, "get_team_profile", return_value={"strategy_profile": {"team_direction": "rebuild"}}):
                        with patch.object(db, "list_manager_trade_profiles", return_value=[manager_profile]):
                            statuses = refresh_all.refresh_user("joe", "2026", user_id=17)

        self.assertEqual(statuses["league-a"]["state"], "complete")
        context = mocked_main.call_args.kwargs["context"]
        self.assertEqual(context.manager_trade_profiles, [manager_profile])
        self.assertEqual(context.strategy_profile["team_direction"], "rebuild")

    def test_refresh_all_main_keeps_legacy_defaults(self) -> None:
        signature = inspect.signature(refresh_all.main)
        self.assertEqual(signature.parameters["force"].default, False)
        self.assertIsNone(signature.parameters["league_id"].default)
        self.assertIsNone(signature.parameters["roster_id"].default)
        self.assertIsNone(signature.parameters["paths"].default)
        self.assertEqual(refresh_all.PROCESSED_DIR, Path(refresh_all.PROCESSED_DIR))


class AttentionQueueTests(unittest.TestCase):
    def test_waiver_day_today_emits_deadline_and_missing_settings_do_nothing(self) -> None:
        now = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
        entry = {"league_id": "l1", "name": "Alpha", "league_type": "dynasty"}
        paths = LeaguePaths.for_league("l1")

        items = deadline_items(entry, paths, {"waiver_day_of_week": 0, "waiver_type": 0}, [], now)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, "deadline")
        self.assertEqual(items[0].severity, 80)
        self.assertIn("today", items[0].headline.lower())
        self.assertEqual(deadline_items(entry, paths, {}, [], now), [])

    def test_only_pending_transactions_emit_deadline_items(self) -> None:
        # Review finding on the first implementation: weeks-old FAILED waivers were surfacing
        # as severity-85 deadlines. Only genuinely pending transactions demand attention;
        # complete and failed rows are history.
        now = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
        entry = {"league_id": "l1", "name": "Alpha", "league_type": "dynasty"}
        paths = LeaguePaths.for_league("l1")
        # Field names match the real transactions_normalized.csv schema (adds/drops).
        transactions = [
            {"league_id": "l1", "transaction_id": "t1", "type": "waiver", "status": "failed", "adds": "Old Miss"},
            {"league_id": "l1", "transaction_id": "t2", "type": "trade", "status": "complete", "adds": "Done Deal"},
            {"league_id": "l1", "transaction_id": "t3", "type": "trade", "status": "pending", "adds": "Live Offer"},
            {"league_id": "l1", "transaction_id": "t3", "type": "trade", "status": "pending", "adds": "Live Offer"},
        ]
        items = deadline_items(entry, paths, {}, transactions, now)
        self.assertEqual(len(items), 1)  # pending only, deduped by transaction_id
        self.assertIn("pending", items[0].headline.lower())
        self.assertIn("Live Offer", items[0].headline)

    def test_owned_non_active_player_emits_one_deduped_roster_health_item(self) -> None:
        entry = {"league_id": "l1", "name": "Alpha", "league_type": "dynasty", "roster_id": 2}
        paths = LeaguePaths.for_league("l1")

        items = roster_health_items(
            entry,
            paths,
            [{"roster_id": "2", "player_id": "p1", "player_name": "Player One"}],
            [{"player_id": "p1", "full_name": "Player One", "status": "Injured Reserve"}],
            [{"event_id": "e1", "player_id": "p1", "player_name": "Player One", "impact_type": "injury_risk"}],
            [{"player_id": "p1", "market_value": "30"}],
            datetime(2026, 7, 5, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, "roster_health")
        self.assertEqual(items[0].severity, 70)
        self.assertIn("Player One", items[0].headline)

    def test_market_windows_respect_ownership_and_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "league-market")
            entry = {"league_id": "league-market", "name": "Market", "league_type": "dynasty", "roster_id": 2, "season": "2026"}
            rows = []
            for index in range(5):
                rows.append(
                    {
                        "roster_id": "2",
                        "player_id": f"s{index}",
                        "player_name": f"Sell {index}",
                        "action_label": "sell_window",
                        "action_score": str(160 - index),
                    }
                )
            rows.append({"roster_id": "2", "player_id": "owned-buy", "player_name": "Owned Buy", "action_label": "true_buy_low", "action_score": "200"})
            for index in range(5):
                rows.append(
                    {
                        "roster_id": "9",
                        "player_id": f"b{index}",
                        "player_name": f"Buy {index}",
                        "action_label": "true_buy_low",
                        "action_score": str(160 - index),
                    }
                )
            self._write_csv(paths.processed_dir / "roster_players.csv", ["roster_id", "player_id", "player_name"], [{"roster_id": "2", "player_id": f"s{index}", "player_name": f"Sell {index}"} for index in range(5)] + [{"roster_id": "2", "player_id": "owned-buy", "player_name": "Owned Buy"}])
            self._write_csv(paths.processed_dir / "players.csv", ["player_id", "full_name", "status"], [])
            self._write_csv(paths.processed_dir / "league_news_impact.csv", ["event_id", "player_id", "impact_type"], [])
            self._write_csv(paths.processed_dir / "action_recommendations.csv", ["roster_id", "player_id", "player_name", "action_label", "action_score"], rows)
            self._write_csv(paths.processed_dir / "refresh_metadata.csv", ["generated_at"], [{"generated_at": "2026-07-05T00:00:00+00:00"}])

            items = build_league_attention(entry, paths, datetime(2026, 7, 5, 12, tzinfo=timezone.utc))

        market_items = [item for item in items if item.item_type == "market_window"]
        self.assertEqual(len([item for item in market_items if item.headline.startswith("Sell window")]), 3)
        self.assertEqual(len([item for item in market_items if item.headline.startswith("Buy-low")]), 3)
        self.assertNotIn("Owned Buy", [item.headline for item in market_items])

    def test_quiet_item_when_nothing_above_threshold_names_league(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "quiet")
            entry = {"league_id": "quiet", "name": "Quiet League", "league_type": "dynasty", "roster_id": 2, "season": "2026"}
            self._write_csv(paths.processed_dir / "refresh_metadata.csv", ["generated_at"], [{"generated_at": "2026-07-05T00:00:00+00:00"}])

            items = build_league_attention(entry, paths, datetime(2026, 7, 5, 12, tzinfo=timezone.utc))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, "quiet")
        self.assertIn("Quiet League", items[0].headline)

    def test_build_user_attention_isolates_missing_league_path_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            leagues_root = Path(tmp) / "leagues"
            good_paths = self._paths(str(leagues_root.parent), "good")
            self._write_csv(good_paths.processed_dir / "roster_players.csv", ["roster_id", "player_id", "player_name"], [{"roster_id": "2", "player_id": "p1", "player_name": "Hurt"}])
            self._write_csv(good_paths.processed_dir / "players.csv", ["player_id", "full_name", "status"], [{"player_id": "p1", "full_name": "Hurt", "status": "Out"}])
            self._write_csv(good_paths.processed_dir / "league_news_impact.csv", ["event_id", "player_id", "impact_type"], [])
            self._write_csv(good_paths.processed_dir / "player_dossiers.csv", ["player_id", "market_value"], [{"player_id": "p1", "market_value": "10"}])
            with patch("src.league_paths.LEAGUES_ROOT", leagues_root):
                items = build_user_attention(
                    [
                        {"league_id": "good", "name": "Good", "league_type": "dynasty", "roster_id": 2, "season": "2026"},
                        {"league_id": "missing", "name": "Missing", "league_type": "dynasty", "roster_id": 2, "season": "2026"},
                    ],
                    datetime(2026, 7, 5, 12, tzinfo=timezone.utc),
                )

        self.assertTrue(any(item.league_name == "Good" and item.item_type == "roster_health" for item in items))
        problem = [item for item in items if item.league_name == "Missing"]
        self.assertEqual(len(problem), 1)
        self.assertEqual(problem[0].severity, 90)
        self.assertIn("data problem", problem[0].headline)

    def test_best_ball_league_with_no_data_stays_quiet_not_data_problem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            leagues_root = Path(tmp) / "leagues"
            with patch("src.league_paths.LEAGUES_ROOT", leagues_root):
                items = build_user_attention(
                    [{"league_id": "bb", "name": "Passive BB", "league_type": "best_ball", "roster_id": 2, "season": "2026"}],
                    datetime(2026, 7, 5, 12, tzinfo=timezone.utc),
                )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, "quiet")
        self.assertLess(items[0].severity, 10)
        self.assertIn("runs itself", items[0].headline)

    def test_best_ball_suppresses_market_windows_and_reduces_roster_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "best")
            entry = {"league_id": "best", "name": "Best", "league_type": "best_ball", "roster_id": 2, "season": "2026"}
            self._write_csv(paths.processed_dir / "roster_players.csv", ["roster_id", "player_id", "player_name"], [{"roster_id": "2", "player_id": "p1", "player_name": "Best Hurt"}])
            self._write_csv(paths.processed_dir / "players.csv", ["player_id", "full_name", "status"], [{"player_id": "p1", "full_name": "Best Hurt", "status": "Out"}])
            self._write_csv(paths.processed_dir / "league_news_impact.csv", ["event_id", "player_id", "impact_type"], [])
            self._write_csv(paths.processed_dir / "player_dossiers.csv", ["player_id", "market_value"], [{"player_id": "p1", "market_value": "30"}])
            self._write_csv(paths.processed_dir / "action_recommendations.csv", ["roster_id", "player_id", "player_name", "action_label", "action_score"], [{"roster_id": "2", "player_id": "p1", "player_name": "Best Hurt", "action_label": "sell_window", "action_score": "200"}])

            items = build_league_attention(entry, paths, datetime(2026, 7, 5, 12, tzinfo=timezone.utc))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, "roster_health")
        self.assertEqual(items[0].severity, 50)

    def test_save_load_attention_round_trip_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attention.json"
            items = [
                AttentionItem("l1", "Alpha", "dynasty", "deadline", 90, "A", "Detail", "/league/l1", "e=1", "2026-07-05T12:00:00+00:00"),
                AttentionItem("l2", "Beta", "redraft", "quiet", 5, "B", "Detail", "", "e=2", "2026-07-05T12:00:00+00:00"),
            ]

            save_attention(items, path)
            loaded = load_attention(path)

        self.assertEqual(loaded, items)

    def _paths(self, tmp: str, league_id: str) -> LeaguePaths:
        root = Path(tmp) / "leagues" / league_id
        return LeaguePaths(
            league_id=league_id,
            root=root,
            raw_dir=root / "raw",
            raw_external_dir=root / "raw_external",
            processed_dir=root / "processed",
            cache_dir=root / "cache",
            reports_dir=root / "reports",
            site_dir=root / "site",
            analysis_dir=root / "analysis",
            operator_inbox_dir=root / "operator" / "inbox",
            operator_outbox_dir=root / "operator" / "outbox",
            operator_status_dir=root / "operator" / "status",
        )

    def _write_csv(self, path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


class FastAPIClerkAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "app.db"
        self.leagues_root = self.tmp_path / "leagues"
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key()))
        jwk["kid"] = "test-key"
        self.jwks = {"keys": [jwk]}
        self.patches = [
            patch.object(db, "DB_PATH", self.db_path),
            patch("src.league_paths.LEAGUES_ROOT", self.leagues_root),
            patch("src.league_paths.USERS_ROOT", self.tmp_path / "users"),
            patch("src.league_registry.USERS_ROOT", self.tmp_path / "users"),
            patch("src.attention.USERS_ROOT", self.tmp_path / "users"),
            patch.object(auth, "JWKS_PROVIDER", lambda: self.jwks),
            patch.dict(
                os.environ,
                {
                    "CLERK_ISSUER": "https://clerk.test",
                    "CLERK_JWKS_URL": "https://clerk.test/.well-known/jwks.json",
                    "CLERK_PUBLISHABLE_KEY": "pk_test_123",
                    "CLERK_AUTHORIZED_PARTIES": "http://localhost:8765,https://fantasy.test",
                    "FRONT_OFFICE_SCHEDULER": "off",
                    "OPENAI_API_KEY": "",
                    "ANTHROPIC_API_KEY": "",
                    "FRONT_OFFICE_LLM_PROVIDER": "",
                },
                clear=False,
            ),
        ]
        for patcher in self.patches:
            patcher.start()
        self.app = create_app()
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_no_token_redirects_html_and_rejects_api(self) -> None:
        html_response = self.client.get("/", follow_redirects=False)
        api_response = self.client.get("/api/attention")

        self.assertEqual(html_response.status_code, 303)
        self.assertEqual(html_response.headers["location"], "/login")
        self.assertEqual(api_response.status_code, 401)

    def test_login_uses_canonical_public_url_for_clerk_redirects(self) -> None:
        with patch.dict(os.environ, {"FRONT_OFFICE_PUBLIC_URL": "https://fantasy.test"}, clear=False):
            response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn('forceRedirectUrl: "https://fantasy.test/"', response.text)
        self.assertIn('signUpFallbackRedirectUrl: "https://fantasy.test/"', response.text)

    def test_login_honors_forwarded_https_scheme_when_public_url_is_unset(self) -> None:
        with patch.dict(os.environ, {"FRONT_OFFICE_PUBLIC_URL": ""}, clear=False):
            response = self.client.get(
                "/login",
                headers={"host": "fantasy.test", "x-forwarded-proto": "https"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('forceRedirectUrl: "https://fantasy.test/"', response.text)

    def test_login_uses_railway_public_domain_when_explicit_url_is_unset(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRONT_OFFICE_PUBLIC_URL": "",
                "RAILWAY_PUBLIC_DOMAIN": "fantasy.test",
                "CLERK_PUBLISHABLE_KEY": "pk_live_123",
                "FRONT_OFFICE_DATA_DIR": "/app/data",
                "FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret",
                "FRONT_OFFICE_SCHEDULER": "on",
            },
            clear=False,
        ):
            response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn('forceRedirectUrl: "https://fantasy.test/"', response.text)

    def test_login_blocks_unready_railway_deployment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RAILWAY_PUBLIC_DOMAIN": "fantasy.test",
                "CLERK_PUBLISHABLE_KEY": "pk_test_123",
                "FRONT_OFFICE_ALLOW_DEVELOPMENT_AUTH": "false",
                "FRONT_OFFICE_DATA_DIR": "",
                "FRONT_OFFICE_OPERATOR_TOKEN": "",
                "FRONT_OFFICE_SCHEDULER": "on",
            },
            clear=False,
        ):
            response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Production setup incomplete", response.text)
        self.assertIn("live Clerk publishable key", response.text)
        self.assertIn("FRONT_OFFICE_DATA_DIR", response.text)
        self.assertNotIn("mountSignIn", response.text)

    def test_private_railway_deployment_allows_existing_development_auth(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RAILWAY_PUBLIC_DOMAIN": "fantasy.test",
                "CLERK_PUBLISHABLE_KEY": "pk_test_123",
                "FRONT_OFFICE_ALLOW_DEVELOPMENT_AUTH": "true",
                "FRONT_OFFICE_DATA_DIR": "/app/data",
                "FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret",
                "FRONT_OFFICE_SCHEDULER": "on",
            },
            clear=False,
        ):
            response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auth_mode"], "development")
        self.assertTrue(response.json()["development_auth_allowed"])
        self.assertTrue(response.json()["deployment_ready"])
        self.assertEqual(response.json()["deployment_blockers"], [])

    def test_healthz_reports_safe_deployment_signals(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CLERK_PUBLISHABLE_KEY": "pk_test_123",
                "FRONT_OFFICE_PUBLIC_URL": "https://fantasy.test",
                "FRONT_OFFICE_DATA_DIR": "/app/data",
                "FRONT_OFFICE_ALLOW_DEVELOPMENT_AUTH": "false",
            },
            clear=False,
        ):
            response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "revision": "",
                "auth_mode": "development",
                "development_auth_allowed": False,
                "auth_issuer_configured": True,
                "auth_jwks_configured": True,
                "auth_configuration_ready": True,
                "public_url_configured": True,
                "public_url_ready": True,
                "data_root_configured": True,
                "database_present": True,
                "database_schema_ready": True,
                "database_table_count": 9,
                "writer_api_configured": False,
                "writer_provider": "openai",
                "writer_model": "gpt-5.6-luna",
                "writer_api_key_env": "OPENAI_API_KEY",
                "operator_token_configured": False,
                "scheduler_enabled": False,
                "deployment_ready": True,
                "deployment_blockers": [],
            },
        )

    def test_valid_token_serves_home_and_auto_provisions_user(self) -> None:
        response = self.client.get("/", cookies={"__session": self._token("user_valid")})

        self.assertEqual(response.status_code, 200)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT clerk_user_id FROM users").fetchone()
        self.assertEqual(row[0], "user_valid")

    def test_home_explains_production_operator_gate_for_writer_controls(self) -> None:
        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            token = self._token("user_writer_gate")
            self.client.get("/", cookies={"__session": token})
            user_id = self._user_id("user_writer_gate")
            db.upsert_user_league(
                user_id,
                {"league_id": "writer-gate", "season": "2026", "league_type": "dynasty", "name": "Writer Gate", "roster_id": 1},
            )
            response = self.client.get("/", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-testid="writer-operator-note"', response.text)
        self.assertIn("FRONT_OFFICE_OPERATOR_TOKEN", response.text)
        self.assertIn("requires FRONT_OFFICE_OPERATOR_TOKEN", response.text)
        self.assertIn('data-testid="writer-readiness"', response.text)
        self.assertIn("gpt-5.6-luna", response.text)
        self.assertIn('data-testid="writer-setup-note"', response.text)
        self.assertIn("OPENAI_API_KEY", response.text)

    def test_profile_api_persists_two_leagues_and_writer_request_keeps_selected_scope(self) -> None:
        clerk_token = self._token("user_two_league_profiles")
        self.client.get("/", cookies={"__session": clerk_token})
        user_id = self._user_id("user_two_league_profiles")
        db.upsert_user_league(
            user_id,
            {"league_id": "alpha", "season": "2026", "league_type": "dynasty", "name": "Alpha", "roster_id": 1},
        )
        db.upsert_user_league(
            user_id,
            {"league_id": "beta", "season": "2026", "league_type": "redraft", "name": "Beta", "roster_id": 2},
        )

        alpha_profile = {
            "team_name": "Alpha Rebuilders",
            "display_name": "alpha-joe",
            "strategy_name": "Build through 2027",
            "team_direction": "rebuild",
            "contention_window": "2027-2029",
            "strategy_profile": {
                "name": "Build through 2027",
                "team_direction": "rebuild",
                "horizon_fit_weights": {
                    "rebuilder": {"next_game": 5, "rest_of_season": 20, "dynasty": 45, "career_window": 30},
                },
            },
            "writer_preferences": {"persona_id": "scout", "custom_instructions": "Lead with role evidence."},
        }
        beta_profile = {
            "team_name": "Beta Blitz",
            "display_name": "beta-joe",
            "strategy_name": "Win this season",
            "team_direction": "contend",
            "contention_window": "2026",
            "strategy_profile": {"name": "Win this season", "team_direction": "contend"},
            "writer_preferences": {"persona_id": "commissioner", "custom_instructions": "Make the league angle fun."},
        }

        alpha_saved = self.client.put(
            "/api/leagues/alpha/profile",
            cookies={"__session": clerk_token},
            json=alpha_profile,
        )
        beta_saved = self.client.put(
            "/api/leagues/beta/profile",
            cookies={"__session": clerk_token},
            json=beta_profile,
        )

        self.assertEqual(alpha_saved.status_code, 200)
        self.assertEqual(beta_saved.status_code, 200)
        self.assertEqual(alpha_saved.json()["team_name"], "Alpha Rebuilders")
        self.assertEqual(beta_saved.json()["team_name"], "Beta Blitz")
        self.assertEqual(
            self.client.get("/api/leagues/alpha/profile", cookies={"__session": clerk_token}).json()["writer_preferences"]["persona_id"],
            "scout",
        )
        self.assertEqual(
            self.client.get("/api/leagues/beta/profile", cookies={"__session": clerk_token}).json()["writer_preferences"]["persona_id"],
            "commissioner",
        )
        self.assertEqual(
            self.client.get("/api/leagues/alpha/profile", cookies={"__session": clerk_token}).json()["strategy_profile"]["team_direction"],
            "rebuild",
        )
        self.assertEqual(
            self.client.get("/api/leagues/alpha/profile", cookies={"__session": clerk_token}).json()["strategy_profile"]["horizon_fit_weights"]["rebuilder"]["dynasty"],
            45,
        )
        self.assertEqual(
            self.client.get("/api/leagues/beta/profile", cookies={"__session": clerk_token}).json()["strategy_profile"]["team_direction"],
            "contend",
        )

        other_token = self._token("different_user")
        self.client.get("/", cookies={"__session": other_token})
        self.assertEqual(
            self.client.get("/api/leagues/alpha/profile", cookies={"__session": other_token}).status_code,
            404,
        )

        def run_job(action: str, callback: object, **kwargs: object) -> dict[str, object]:
            del action, kwargs
            return {"accepted": True, "result": callback()}

        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            with patch("app.main._generate_insights_job", return_value={"state": "complete"}) as generate:
                with patch("app.main.front_operator.start_job", side_effect=run_job):
                    queued = self.client.post(
                        "/api/operator/generate-insights",
                        cookies={"__session": clerk_token},
                        headers={"x-front-office-token": "operator-secret"},
                        json={"league_id": "beta"},
                    )

        self.assertEqual(queued.status_code, 200)
        self.assertTrue(queued.json()["accepted"])
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[0]["league_id"], "beta")
        self.assertEqual(generate.call_args.args[1], user_id)

    def test_writer_request_without_league_id_keeps_all_editions_scope(self) -> None:
        clerk_token = self._token("user_all_editions")
        self.client.get("/", cookies={"__session": clerk_token})
        user_id = self._user_id("user_all_editions")
        db.upsert_user_league(
            user_id,
            {"league_id": "alpha", "season": "2026", "league_type": "dynasty", "name": "Alpha", "roster_id": 1},
        )
        db.upsert_user_league(
            user_id,
            {"league_id": "beta", "season": "2026", "league_type": "redraft", "name": "Beta", "roster_id": 2},
        )

        def run_job(action: str, callback: object, **kwargs: object) -> dict[str, object]:
            del action, kwargs
            return {"accepted": True, "result": callback()}

        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            with patch("app.main._generate_insights_job", return_value={"state": "complete"}) as generate:
                with patch("app.main.front_operator.start_job", side_effect=run_job):
                    queued = self.client.post(
                        "/api/operator/generate-insights",
                        cookies={"__session": clerk_token},
                        headers={"x-front-office-token": "operator-secret"},
                        json={},
                    )

        self.assertEqual(queued.status_code, 200)
        self.assertTrue(queued.json()["accepted"])
        generate.assert_called_once_with(None, user_id)

    def test_generate_insights_preserves_failed_workflow_diagnostics(self) -> None:
        league = {
            "league_id": "diagnostic-league",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Diagnostic League",
            "roster_id": 2,
        }
        workflow = {
            "state": "failed",
            "message": "OPENAI_API_KEY is not set. No LLM call was attempted.",
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "articles": {},
        }
        with patch("app.main._refresh_job"), \
             patch("app.main._context_for_league", return_value=object()), \
             patch("app.main._private_paths", return_value=MagicMock()), \
             patch("app.main.front_operator.generate_articles_workflow", return_value=workflow), \
             patch("app.main._rebuild_browser_job", return_value={"state": "complete"}):
            result = app_main._generate_insights_job(league, 42)

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["message"], workflow["message"])
        self.assertEqual(result["model"], "gpt-5.6-luna")

    def test_blank_profile_has_same_scalar_contract_as_saved_profile(self) -> None:
        token = self._token("user_blank_profile")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_blank_profile")
        db.upsert_user_league(
            user_id,
            {"league_id": "blank", "season": "2026", "league_type": "dynasty", "name": "Blank", "roster_id": 1},
        )

        response = self.client.get("/api/leagues/blank/profile", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for field in ("team_name", "display_name", "strategy_name", "team_direction", "contention_window"):
            self.assertIn(field, payload)
            self.assertEqual(payload[field], "")

    def test_continuity_receipt_reports_linked_leagues_and_profiles(self) -> None:
        token = self._token("user_continuity")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_continuity")
        db.upsert_user_league(
            user_id,
            {"league_id": "continuity-league", "season": "2026", "league_type": "dynasty", "name": "Continuity", "roster_id": 2},
        )
        db.upsert_team_profile(
            user_id,
            "continuity-league",
            {"team_name": "Continuity Team", "writer_preferences": {"persona_id": "quant"}},
        )

        with patch.dict(os.environ, {"FRONT_OFFICE_DATA_DIR": ""}, clear=False):
            response = self.client.get("/api/continuity", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["state"], "local_default")
        self.assertEqual(payload["linked_leagues"], 1)
        self.assertEqual(payload["team_profiles"], 1)
        self.assertEqual(payload["private_workspaces"], 0)
        self.assertEqual(payload["identity_state"], "linked")

    def test_empty_home_reports_identity_check_without_exposing_other_leagues(self) -> None:
        token = self._token("user_new_identity")
        self.client.get("/", cookies={"__session": token})
        self.client.get("/", cookies={"__session": self._token("user_existing_identity")})
        existing_user_id = self._user_id("user_existing_identity")
        db.upsert_user_league(
            existing_user_id,
            {"league_id": "private-league", "season": "2026", "league_type": "dynasty", "name": "Private League", "roster_id": 1},
        )

        response = self.client.get("/", cookies={"__session": token})
        continuity = self.client.get("/api/continuity", cookies={"__session": token}).json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-testid="identity-check-message"', response.text)
        self.assertNotIn("Private League", response.text)
        self.assertEqual(continuity["identity_state"], "identity_check")
        self.assertNotIn("league_id", continuity["identity_message"])

    def test_home_renders_phone_first_attention_feed_and_league_pills(self) -> None:
        token = self._token("user_home_feed")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_home_feed")
        db.upsert_user_league(user_id, {"league_id": "alpha", "season": "2026", "league_type": "dynasty", "name": "Alpha League", "roster_id": 1})
        db.upsert_user_league(user_id, {"league_id": "beta", "season": "2026", "league_type": "redraft", "name": "Beta League", "roster_id": 2})
        db.toggle_league(user_id, "beta", False)
        status_path = self.leagues_root / "alpha" / "site" / "refresh_status.json"
        status_path.parent.mkdir(parents=True)
        status_path.write_text(json.dumps({"state": "complete", "updated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        _write_writer_brief(
            self.tmp_path / "users" / str(user_id) / "leagues" / "alpha" / "analysis",
            "Alpha's private read: protect the young receiver and wait for the next usage spike.",
        )
        _write_complete_bundle(
            status_path.parent,
            "<h1>Alpha edition</h1>",
            {
                "kicker": "Personal league edition",
                "edition_label": "Today",
                "headline": "Your rookie receiver is the morning's real market leak",
                "dek": "The model found a role signal worth opening.",
                "stories": [
                    {"eyebrow": "Manager lens", "headline": "A rival is buying the wrong window", "dek": "Observed behavior gives us an angle."}
                ],
                "as_of_label": "As of today's refresh",
                "reporter_persona": {"name": "The Scout"},
                "source_health": [
                    {
                        "label": "News desk",
                        "status": "refreshed",
                        "status_label": "Current",
                        "healthy": True,
                        "checked_at": "2026-07-05T12:00:00+00:00",
                        "row_count": 3,
                    }
                ],
            },
        )
        items = [
            AttentionItem("alpha", "Alpha League", "dynasty", "deadline", 88, "Waivers process today", "Claims need a look.", "/league/alpha/#view-today", "e=1", "2026-07-05T12:00:00+00:00"),
            AttentionItem("alpha", "Alpha League", "dynasty", "roster_health", 72, "Player is Out", "Lineup math got worse.", "/league/alpha/#player-1", "e=2", "2026-07-05T12:00:00+00:00"),
            AttentionItem("alpha", "Alpha League", "dynasty", "market_window", 55, "Buy-low target: Receiver", "Someone else is bored.", "/league/alpha/#player-2", "e=3", "2026-07-05T12:00:00+00:00"),
            AttentionItem("alpha", "Alpha League", "dynasty", "quiet", 5, "Nothing needs you in Alpha League", "Quiet detail stays hidden.", "", "e=4", "2026-07-05T12:00:00+00:00"),
        ]

        with patch("app.main.load_attention", return_value=items):
            response = self.client.get("/", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', html)
        self.assertIn('data-testid="attention-feed"', html)
        self.assertIn("attention-card cat-alert item-deadline", html)
        self.assertIn("attention-card cat-sell item-roster_health", html)
        self.assertIn("attention-card cat-buy item-market_window", html)
        self.assertIn("quiet-divider", html)
        self.assertIn("All quiet", html)
        self.assertEqual(html.count('<span class="score-tile'), 4)
        self.assertIn('class="league-pill selected" href="/?league_id=alpha"', html)
        self.assertIn("type-badge dynasty", html)
        self.assertIn("DYNASTY", html.upper())
        self.assertIn("fresh-dot fresh", html)
        self.assertNotIn("/league/beta/", html)
        self.assertIn('data-profile-form', html)
        self.assertIn('data-profile-league', html)
        self.assertIn('Save league profile', html)
        self.assertIn('data-profile-field="persona_id"', html)
        self.assertIn('data-profile-field="horizon_fit_weights"', html)
        self.assertIn("Personal horizon weights", html)
        self.assertIn("edition refresh queued", html)
        self.assertIn("Build manager trade profiles", html)
        self.assertIn('data-manager-trade-form', html)
        self.assertIn('data-manager-trade-field="trade_style"', html)
        self.assertIn("The Scout", html)
        self.assertIn("The Commissioner", html)
        self.assertIn('data-writer-button', html)
        self.assertIn("Generate this edition", html)
        self.assertIn('data-writer-all-button', html)
        self.assertIn('data-testid="writer-readiness"', html)
        self.assertIn('data-testid="writer-setup-note"', html)
        self.assertIn("Your Clerk session expired. Sign in again before running the writer.", html)
        self.assertIn("Generate all editions", html)
        self.assertIn("'/api/operator/status?league_id=' + encodeURIComponent(leagueId)", html)
        self.assertIn("statusUrl = allEditions", html)
        self.assertIn("Watching the selected league for completion.", html)
        self.assertIn("Read the new edition", html)
        self.assertIn('data-testid="writer-fallback-note"', html)
        self.assertIn('data-storage-audit-button', html)
        self.assertIn("fetch('/api/operator/storage-audit'", html)
        self.assertIn('data-testid="edition-hero"', html)
        self.assertIn('data-testid="edition-proof"', html)
        self.assertIn('data-testid="edition-lineup"', html)
        self.assertIn("All league editions", html)
        self.assertIn('class="edition-card selected"', html)
        self.assertIn("news rows", html)
        self.assertIn("news sources current", html)
        self.assertIn("Latest news:", html)
        self.assertIn("Writer output:", html)
        self.assertIn("writer-content-status", html)
        self.assertIn('data-testid="article-shelf"', html)
        self.assertIn("Daily GM Brief", html)
        self.assertIn("Manager Intel", html)
        self.assertIn("Market Clock Read", html)
        self.assertIn("How value changes with time", html)
        self.assertIn(f"/league/alpha/#view-trade-desk", html)
        self.assertIn("Edition:", html)
        self.assertIn("#view-draft-room", html)
        self.assertIn('data-testid="front-page"', html)
        self.assertIn('data-testid="writer-preview"', html)
        self.assertIn("Alpha&#39;s private read", html)
        self.assertIn("Evidence-led fallback", html)
        self.assertIn("Read the full brief", html)
        self.assertIn("Your rookie receiver is the morning", html)
        self.assertIn("A rival is buying the wrong window", html)
        self.assertIn("Your leagues, edited into a daily read.", html)
        self.assertIn("Evidence-backed briefs", html)
        self.assertIn('data-testid="league-readiness"', html)
        self.assertIn("Ready", html)
        self.assertIn("fetch('/api/leagues/refresh'", html)
        self.assertNotIn("fetch('/api/operator/refresh'", html)

    def test_home_query_focuses_selected_owned_league_and_falls_back_safely(self) -> None:
        token = self._token("user_home_focus")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_home_focus")
        db.upsert_user_league(
            user_id,
            {"league_id": "alpha", "season": "2026", "league_type": "dynasty", "name": "Alpha League", "roster_id": 1},
        )
        db.upsert_user_league(
            user_id,
            {"league_id": "beta", "season": "2026", "league_type": "redraft", "name": "Beta League", "roster_id": 2},
        )
        for league_id, headline in (("alpha", "Alpha focus headline"), ("beta", "Beta focus headline")):
            site_dir = self.leagues_root / league_id / "site"
            _write_complete_bundle(
                site_dir,
                f"<h1>{headline}</h1>",
                {
                    "kicker": "Personal league edition",
                    "edition_label": "Today",
                    "headline": headline,
                    "dek": f"{league_id.title()} evidence-led read.",
                    "reporter_persona": {"name": "The Scout"},
                    "source_health": [
                        {
                            "label": "News desk",
                            "status": "refreshed",
                            "status_label": "Current",
                            "healthy": True,
                            "checked_at": "2026-07-05T12:00:00+00:00",
                            "row_count": 3,
                        }
                    ],
                },
            )

        with patch("app.main.load_attention", return_value=[]):
            response = self.client.get("/?league_id=beta", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Beta focus headline", html)
        self.assertIn("Alpha focus headline", html)
        self.assertIn("In focus: <strong>Beta League</strong>", html)
        self.assertIn('class="league-pill selected" href="/?league_id=beta"', html)
        self.assertIn('value="beta" selected', html)
        self.assertIn('href="/?league_id=alpha"', html)

        remembered = self.client.get("/", cookies={"__session": token})
        self.assertIn("In focus: <strong>Beta League</strong>", remembered.text)

        with patch("app.main.load_attention", return_value=[]):
            fallback = self.client.get("/?league_id=not-owned", cookies={"__session": token})

        self.assertEqual(fallback.status_code, 200)
        self.assertIn("Alpha focus headline", fallback.text)
        self.assertIn("Beta focus headline", fallback.text)
        self.assertIn("In focus: <strong>Beta League</strong>", fallback.text)

    def test_direct_edition_visit_updates_the_remembered_league(self) -> None:
        """Encodes AGENTS.md identity continuity: an owned route is a league selection."""
        token = self._token("user_direct_league_focus")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_direct_league_focus")
        for league_id, name in (("alpha", "Alpha League"), ("beta", "Beta League")):
            db.upsert_user_league(
                user_id,
                {"league_id": league_id, "season": "2026", "league_type": "dynasty", "name": name, "roster_id": 1},
            )
            _write_complete_bundle(self.leagues_root / league_id / "site", f"<h1>{name}</h1>")

        self.client.get("/?league_id=alpha", cookies={"__session": token})
        direct = self.client.get("/league/beta/", cookies={"__session": token})
        self.assertEqual(direct.status_code, 200)
        remembered = self.client.get("/", cookies={"__session": token})
        self.assertIn("In focus: <strong>Beta League</strong>", remembered.text)

    def test_persisted_bundle_is_rebuilt_when_running_source_revision_changes(self) -> None:
        """Encodes AGENTS.md anti-recursive deployment guardrail: a live SHA is not enough if a durable shell is old."""
        token = self._token("user_stale_source_bundle")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_source_bundle")
        db.upsert_user_league(
            user_id,
            {"league_id": "stale-source", "season": "2026", "league_type": "dynasty", "name": "Stale Source", "roster_id": 1},
        )
        site_dir = self.leagues_root / "stale-source" / "site"
        _write_complete_bundle(site_dir, "<h1>Persisted old shell</h1>")

        with patch("app.main._deployment_revision", return_value="release-new") as revision:
            with patch("app.main._rebuild_missing_bundle") as rebuild:
                response = self.client.get("/league/stale-source/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        revision.assert_called()
        rebuild.assert_called_once()

    def test_persisted_bundle_is_rebuilt_when_fallback_receipt_schema_is_old(self) -> None:
        """A current SHA must not hide a stale durable fallback payload."""
        token = self._token("user_stale_fallback_schema")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_fallback_schema")
        db.upsert_user_league(
            user_id,
            {"league_id": "stale-fallback", "season": "2026", "league_type": "dynasty", "name": "Stale Fallback", "roster_id": 1},
        )
        site_dir = self.leagues_root / "stale-fallback" / "site"
        _write_complete_bundle(site_dir, "<h1>Persisted old fallback</h1>")
        manifest_path = site_dir / "data" / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "auditTables": {},
                    "sourceRevision": "release-current",
                    "articleReceipts": {
                        "daily_brief": {"mode": "deterministic_template", "structured": {}}
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch("app.main._deployment_revision", return_value="release-current"):
            with patch("app.main._rebuild_missing_bundle") as rebuild:
                response = self.client.get("/league/stale-fallback/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        rebuild.assert_called_once()

    def test_persisted_bundle_is_rebuilt_when_manager_dossier_schema_is_old(self) -> None:
        """Encodes the anti-recursive seam rule for newly added dossier fields."""
        token = self._token("user_stale_manager_dossier")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_manager_dossier")
        db.upsert_user_league(
            user_id,
            {"league_id": "stale-manager", "season": "2026", "league_type": "dynasty", "name": "Stale Manager", "roster_id": 1},
        )
        site_dir = self.leagues_root / "stale-manager" / "site"
        _write_complete_bundle(site_dir, "<h1>Persisted old manager dossier</h1>")
        fallback_receipts = {
            "daily_brief": {
                "mode": "deterministic_template",
                "structured": {"fallback_schema_version": "deterministic_fallback_v2"},
            }
        }
        (site_dir / "data" / "manifest.json").write_text(
            json.dumps({"auditTables": {}, "sourceRevision": "release-current", "articleReceipts": fallback_receipts}),
            encoding="utf-8",
        )
        (site_dir / "data" / "app_bundle.json").write_text(
            json.dumps(
                {
                    "myRosterId": 1,
                    "identityReceipt": {"roster_id": 1},
                    "analysis": {"articleReceipts": fallback_receipts, "managerDossierItems": [{"roster_id": 8}]},
                }
            ),
            encoding="utf-8",
        )

        with patch("app.main._deployment_revision", return_value="release-current"):
            with patch("app.main._rebuild_missing_bundle") as rebuild:
                response = self.client.get("/league/stale-manager/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        rebuild.assert_called_once()

    def test_persisted_bundle_is_rebuilt_when_data_quality_receipt_is_missing(self) -> None:
        """Encodes docs/front_office_operating_lessons.md's reader-quality contract."""
        token = self._token("user_stale_data_quality")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_data_quality")
        league = {
            "league_id": "stale-data-quality",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Stale Data Quality",
            "roster_id": 1,
        }
        db.upsert_user_league(user_id, league)
        site_dir = self.leagues_root / "stale-data-quality" / "site"
        _write_complete_bundle(site_dir, "Cross-season valuation lanes trade_fit_evaluation")
        receipts = {
            "daily_brief": {
                "mode": "deterministic_template",
                "structured": {"fallback_schema_version": "deterministic_fallback_v2"},
            }
        }
        (site_dir / "data" / "manifest.json").write_text(
            json.dumps({"auditTables": {}, "sourceRevision": "release-current", "articleReceipts": receipts, "dataQuality": _empty_data_quality()}),
            encoding="utf-8",
        )
        (site_dir / "data" / "app_bundle.json").write_text(
            json.dumps({
                "myRosterId": 1,
                "identityReceipt": {"roster_id": 1},
                "analysis": {"articleReceipts": receipts},
            }),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "release-current"}, clear=False):
            with patch("app.main._rebuild_missing_bundle") as rebuild:
                response = self.client.get("/league/stale-data-quality/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        rebuild.assert_called_once()

    def test_persisted_bundle_is_rebuilt_when_reader_shell_contract_is_old(self) -> None:
        """A current payload receipt cannot bless an older generated interface."""
        token = self._token("user_stale_reader_shell")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_reader_shell")
        db.upsert_user_league(
            user_id,
            {"league_id": "stale-shell", "season": "2026", "league_type": "dynasty", "name": "Stale Shell", "roster_id": 1},
        )
        site_dir = self.leagues_root / "stale-shell" / "site"
        _write_complete_bundle(site_dir, "<h1>Old interface</h1>")
        fallback_receipts = {
            "daily_brief": {
                "mode": "deterministic_template",
                "structured": {"fallback_schema_version": "deterministic_fallback_v2"},
            }
        }
        (site_dir / "data" / "manifest.json").write_text(
            json.dumps({"auditTables": {}, "sourceRevision": "release-current", "articleReceipts": fallback_receipts}),
            encoding="utf-8",
        )
        (site_dir / "data" / "app_bundle.json").write_text(
            json.dumps(
                {
                    "myRosterId": 1,
                    "identityReceipt": {"roster_id": 1},
                    "analysis": {"articleReceipts": fallback_receipts},
                }
            ),
            encoding="utf-8",
        )

        with patch("app.main._deployment_revision", return_value="release-current"):
            with patch("app.main._rebuild_missing_bundle") as rebuild:
                response = self.client.get("/league/stale-shell/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        rebuild.assert_called_once()

    def test_persisted_bundle_is_rebuilt_when_recommendation_learning_contract_is_old(self) -> None:
        """Encodes AGENTS.md's entry-path rule for the decision-learning surface."""
        token = self._token("user_stale_recommendation_learning")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_recommendation_learning")
        league = {
            "league_id": "stale-recommendation-learning",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Stale Recommendation Learning",
            "roster_id": 1,
        }
        db.upsert_user_league(user_id, league)
        site_dir = self.leagues_root / "stale-recommendation-learning" / "site"
        # This represents the deployed 7fb6219 shell: the dossier contract is
        # current, but the later recommendation outcome controls are absent.
        _write_complete_bundle(site_dir, "Cross-season valuation lanes trade_fit_evaluation")
        fallback_receipts = {
            "daily_brief": {
                "mode": "deterministic_template",
                "structured": {"fallback_schema_version": "deterministic_fallback_v2"},
            }
        }
        (site_dir / "data" / "manifest.json").write_text(
            json.dumps(
                {
                    "auditTables": {},
                    "sourceRevision": "release-current",
                    "articleReceipts": fallback_receipts,
                    "dataQuality": _empty_data_quality(),
                }
            ),
            encoding="utf-8",
        )
        (site_dir / "data" / "app_bundle.json").write_text(
            json.dumps(
                {
                    "myRosterId": 1,
                    "identityReceipt": {"roster_id": 1},
                    "analysis": {"articleReceipts": fallback_receipts},
                    "dataQuality": _empty_data_quality(),
                }
            ),
            encoding="utf-8",
        )

        with patch("app.main._deployment_revision", return_value="release-current"):
            with patch("app.main._rebuild_missing_bundle") as rebuild:
                response = self.client.get(
                    "/league/stale-recommendation-learning/",
                    cookies={"__session": token},
                )

        self.assertEqual(response.status_code, 503)
        rebuild.assert_called_once()

    def test_writer_preview_is_private_and_follows_selected_league(self) -> None:
        token = self._token("user_writer_preview")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_writer_preview")
        db.upsert_user_league(
            user_id,
            {"league_id": "alpha", "season": "2026", "league_type": "dynasty", "name": "Alpha League", "roster_id": 1},
        )
        db.upsert_user_league(
            user_id,
            {"league_id": "beta", "season": "2026", "league_type": "redraft", "name": "Beta League", "roster_id": 2},
        )
        _write_writer_brief(
            self.tmp_path / "users" / str(user_id) / "leagues" / "alpha" / "analysis",
            "Alpha-only writer read.",
            persona_id="quant",
            mode="automatic_llm",
        )
        _write_writer_brief(
            self.tmp_path / "users" / str(user_id) / "leagues" / "beta" / "analysis",
            "Beta-only writer read.",
            persona_id="commissioner",
        )
        _write_writer_brief(
            self.tmp_path / "users" / "other-user" / "leagues" / "alpha" / "analysis",
            "Foreign user's writer read.",
            persona_id="front_office",
        )

        with patch("app.main.load_attention", return_value=[]):
            alpha = self.client.get("/?league_id=alpha", cookies={"__session": token})
            beta = self.client.get("/?league_id=beta", cookies={"__session": token})

        self.assertEqual(alpha.status_code, 200)
        self.assertIn("Alpha-only writer read.", alpha.text)
        self.assertIn("The Quant", alpha.text)
        self.assertIn("API reporter", alpha.text)
        self.assertNotIn("Beta-only writer read.", alpha.text)
        self.assertNotIn("Foreign user's writer read.", alpha.text)

        self.assertEqual(beta.status_code, 200)
        self.assertIn("Beta-only writer read.", beta.text)
        self.assertIn("The Commissioner", beta.text)
        self.assertIn("Evidence-led fallback", beta.text)
        self.assertNotIn("Alpha-only writer read.", beta.text)
        self.assertNotIn("Foreign user's writer read.", beta.text)

    def test_writer_preview_follows_current_source_team_label(self) -> None:
        token = self._token("user_writer_label")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_writer_label")
        _write_writer_brief(
            self.tmp_path / "users" / str(user_id) / "leagues" / "alpha" / "analysis",
            "The Melkor Lord of Light edition has a live read.",
            team_name="Melkor Lord of Light",
        )
        league = {
            "league_id": "alpha",
            "season": "2026",
            "roster_id": 1,
            "sleeper_team_name": "Lulu’s Potatoe’s",
        }
        with patch.object(
            app_main,
            "_source_team_rows_for_league",
            return_value=[
                {"league_id": "alpha", "season": "2026", "roster_id": 1, "owner_id": "joe", "team_name": "Lulu’s Potatoe’s"},
                {"league_id": "prior", "season": "2025", "roster_id": 1, "owner_id": "joe", "team_name": "Melkor Lord of Light"},
            ],
        ):
            preview = app_main._load_writer_preview(user_id, league)

        self.assertIn("Lulu’s Potatoe’s", preview["text"])
        self.assertNotIn("Melkor Lord of Light", preview["text"])

    def test_manager_trade_profiles_are_private_league_scoped_and_reach_writer_context(self) -> None:
        token = self._token("user_manager_trade_profiles")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_manager_trade_profiles")
        league = {
            "league_id": "alpha",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Alpha League",
            "roster_id": 1,
        }
        db.upsert_user_league(user_id, league)

        initial = self.client.get(
            "/api/leagues/alpha/manager-trade-profiles",
            cookies={"__session": token},
        )
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["profiles"], [])

        saved = self.client.put(
            "/api/leagues/alpha/manager-trade-profiles/7",
            cookies={"__session": token},
            json={
                "manager_name": "The Semiquincentennials",
                "trade_style": "pick seller / win-now buyer",
                "preferred_assets": "young pass catchers",
                "protected_assets": "future firsts",
                "editor_note": "Lead with the role window and keep the first-round ask visible.",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["customized"])
        self.assertEqual(saved.json()["roster_id"], "7")
        self.assertEqual(saved.json()["trade_style"], "pick seller / win-now buyer")

        listed = self.client.get(
            "/api/leagues/alpha/manager-trade-profiles",
            cookies={"__session": token},
        ).json()["profiles"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["editor_note"], "Lead with the role window and keep the first-round ask visible.")

        context = app_main._context_for_league(user_id, league)
        self.assertEqual(context.manager_trade_profiles[0]["manager_name"], "The Semiquincentennials")
        from src import operator

        prompt = operator._article_context_prompt_block(context)
        self.assertIn("Personal manager trade profiles", prompt)
        self.assertIn("pick seller / win-now buyer", prompt)
        self.assertIn("The Semiquincentennials", prompt)

        other_token = self._token("different_manager_profile_user")
        self.client.get("/", cookies={"__session": other_token})
        self.assertEqual(
            self.client.get(
                "/api/leagues/alpha/manager-trade-profiles",
                cookies={"__session": other_token},
            ).status_code,
            404,
        )

    def test_source_receipt_view_summarizes_news_and_limited_sources(self) -> None:
        receipt = _source_receipt_view(
            {
                "as_of_label": "As of today's refresh",
                "reporter_persona": {"name": "The Scout"},
                "source_health": [
                    {"label": "News desk", "status_label": "Current", "healthy": True, "row_count": 3, "checked_at": "2026-07-05T12:00:00+00:00"},
                    {"label": "Market and usage", "status_label": "Limited", "healthy": False, "row_count": 0, "checked_at": "2026-07-05T11:00:00+00:00"},
                ],
            }
        )

        self.assertEqual(receipt["label"], "1/2 current; 1 limited")
        self.assertEqual(receipt["news_row_count"], 3)
        self.assertEqual(receipt["news_current"], 1)
        self.assertEqual(receipt["reporter_name"], "The Scout")
        self.assertEqual(receipt["writer_mode"], "Evidence-led template")
        self.assertEqual(receipt["latest_news_label"], "Not recorded")

    def test_source_receipt_view_groups_real_news_datasets(self) -> None:
        receipt = _source_receipt_view(
            {
                "signal_summary": {"news_signals": 55},
                "source_health": [
                    {"label": "RotoWire · NFL player news", "source": "rotowire_rss", "dataset": "nfl_player_news", "status_label": "Current", "healthy": True, "row_count": 5},
                    {"label": "Sleeper trending · Trending adds", "source": "sleeper_trending", "dataset": "trending_add", "status_label": "Current", "healthy": True, "row_count": 25},
                    {"label": "Sleeper trending · Trending drops", "source": "sleeper_trending", "dataset": "trending_drop", "status_label": "Current", "healthy": True, "row_count": 25},
                    {"label": "DynastyProcess · Player Values", "source": "dynastyprocess", "dataset": "player_values", "status_label": "Current", "healthy": True, "row_count": 788},
                ],
            }
        )

        self.assertEqual(receipt["news_current"], 3)
        self.assertEqual(receipt["news_total"], 3)
        self.assertEqual(receipt["news_row_count"], 55)

    def test_home_empty_state_uses_sleeper_link_form(self) -> None:
        token = self._token("user_empty_home")

        with patch("app.main.load_attention", return_value=[]):
            response = self.client.get("/", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', html)
        self.assertIn('class="empty-hero"', html)
        self.assertIn('action="/api/leagues/link"', html)
        self.assertIn('name="sleeper_username"', html)
        self.assertIn("Point me at your Sleeper username. I'll find the bodies.", html)

    def test_expired_and_wrong_issuer_tokens_are_rejected(self) -> None:
        expired = self._token("user_expired", exp=datetime.now(timezone.utc) - timedelta(minutes=5))
        wrong_issuer = self._token("user_wrong", issuer="https://other-clerk.test")

        self.assertEqual(self.client.get("/api/attention", headers={"Authorization": f"Bearer {expired}"}).status_code, 401)
        self.assertEqual(self.client.get("/api/attention", headers={"Authorization": f"Bearer {wrong_issuer}"}).status_code, 401)

    def test_azp_authorized_parties_reject_and_empty_config_accepts(self) -> None:
        token = self._token("user_azp", azp="https://wrong.test")
        self.assertEqual(self.client.get("/api/attention", headers={"Authorization": f"Bearer {token}"}).status_code, 401)

        with patch.dict(os.environ, {"CLERK_AUTHORIZED_PARTIES": ""}, clear=False):
            accepted = self.client.get("/api/attention", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(accepted.status_code, 200)

    def test_league_serving_requires_owner_rejects_traversal_and_serves_index(self) -> None:
        """Private generated shells must not remain cached after a source deploy."""
        own_token = self._token("user_owner")
        other_token = self._token("user_other")
        self.client.get("/", cookies={"__session": own_token})
        self.client.get("/", cookies={"__session": other_token})
        owner_id = self._user_id("user_owner")
        db.upsert_user_league(owner_id, {"league_id": "league-a", "season": "2026", "league_type": "dynasty", "name": "Alpha", "roster_id": 7})
        site_dir = self.leagues_root / "league-a" / "site"
        site_dir.mkdir(parents=True)
        _write_complete_bundle(site_dir, "<h1>Alpha</h1>")
        (self.tmp_path / "outside.txt").write_text("nope", encoding="utf-8")

        other_response = self.client.get("/league/league-a/", cookies={"__session": other_token})
        traversal = self.client.get("/league/league-a/%2e%2e/%2e%2e/outside.txt", cookies={"__session": own_token})
        index = self.client.get("/league/league-a/", cookies={"__session": own_token})
        bundle = self.client.get("/league/league-a/data/app_bundle.json", cookies={"__session": own_token})

        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(traversal.status_code, 404)
        self.assertEqual(index.status_code, 200)
        self.assertIn("Alpha", index.text)
        self.assertEqual(bundle.status_code, 200)
        self.assertIn("no-store", index.headers["cache-control"])
        self.assertIn("no-store", bundle.headers["cache-control"])

    def test_league_serving_uses_legacy_bundle_when_private_root_is_incomplete(self) -> None:
        token = self._token("user_migration_fallback")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_migration_fallback")
        db.upsert_user_league(user_id, {"league_id": "league-fallback", "season": "2026", "league_type": "dynasty", "name": "Fallback", "roster_id": 7})
        legacy_site = self.leagues_root / "league-fallback" / "site"
        legacy_site.mkdir(parents=True)
        _write_complete_bundle(legacy_site, "<h1>Legacy edition</h1>")

        with patch("src.league_paths.USERS_ROOT", self.tmp_path / "users"):
            private_root = self.tmp_path / "users" / str(user_id) / "leagues" / "league-fallback"
            private_root.mkdir(parents=True)
            response = self.client.get("/league/league-fallback/", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Legacy edition", response.text)

    def test_stale_private_bundle_cannot_mask_current_legacy_bundle(self) -> None:
        """Encodes the identity and stale-shell rule at the bundle-selection seam."""
        token = self._token("user_stale_private")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_private")
        league = {"league_id": "private-stale", "season": "2026", "league_type": "dynasty", "roster_id": 7}
        db.upsert_user_league(user_id, {**league, "name": "Private Stale"})
        private_site = self.tmp_path / "users" / str(user_id) / "leagues" / "private-stale" / "site"
        legacy_site = self.leagues_root / "private-stale" / "site"
        _write_complete_bundle(private_site, "<h1>Stale private shell</h1>")
        _write_complete_bundle(
            legacy_site,
            '<script>Cross-season valuation lanes trade_fit_evaluation Team construction Recommendation outcome decision_outcome Recommendation learning</script>',
        )
        receipts = {
            "daily_brief": {
                "mode": "deterministic_template",
                "structured": {"fallback_schema_version": "deterministic_fallback_v2"},
            }
        }
        for site in (private_site, legacy_site):
            (site / "data" / "manifest.json").write_text(
                json.dumps({"auditTables": {}, "sourceRevision": "release-current", "articleReceipts": receipts, "dataQuality": _empty_data_quality()}),
                encoding="utf-8",
            )
            (site / "data" / "app_bundle.json").write_text(
                json.dumps({
                    "myRosterId": 7,
                    "identityReceipt": {"roster_id": 7},
                    "articleReceipts": receipts,
                    "dataQuality": _empty_data_quality(),
                }),
                encoding="utf-8",
            )

        with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "release-current"}, clear=False):
            selected = app_main._paths_for_user_league({"id": user_id}, league)

        self.assertEqual(selected.root, self.leagues_root / "private-stale")

    def test_link_leagues_upserts_and_returns_discovered_entries(self) -> None:
        # Design source: AGENTS.md identity boundary; relinking must resolve
        # Sleeper ownership from source data rather than stale cache labels.
        token = self._token("user_link")
        entries = [
            {"league_id": "l1", "name": "Linked", "season": "2026", "league_type": "dynasty", "roster_id": 3},
        ]
        with patch("app.main.discover_leagues", return_value=entries) as mocked_discover:
            response = self.client.post(
                "/api/leagues/link",
                headers={"Authorization": f"Bearer {token}"},
                json={"sleeper_username": "sleeperjoe", "season": "2026"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["leagues"][0]["league_id"], "l1")
        mocked_discover.assert_called_once()
        self.assertTrue(mocked_discover.call_args.kwargs["force"])
        stored = db.list_user_leagues(self._user_id("user_link"))
        self.assertEqual(stored[0]["name"], "Linked")

    def test_identity_refresh_uses_stored_sleeper_account_and_repairs_stale_profile(self) -> None:
        token = self._token("user_identity_refresh")
        home = self.client.get("/", cookies={"__session": token})
        self.assertIn("AbortController", home.text)
        user_id = self._user_id("user_identity_refresh")
        db.set_sleeper_account(user_id, "joe3489", "old-sleeper-id")
        db.upsert_user_league(
            user_id,
            {
                "league_id": "league-a",
                "season": "2026",
                "league_type": "dynasty",
                "name": "Alpha",
                "roster_id": 4,
                "identity_status": "unverified",
            },
        )
        db.upsert_team_profile(
            user_id,
            "league-a",
            {"roster_id": 4, "team_name": "Moose Caboose", "strategy_profile": {"name": "Rebuild"}},
        )
        entries = [
            {
                "league_id": "league-a",
                "name": "Alpha",
                "season": "2026",
                "league_type": "dynasty",
                "roster_id": 2,
                "sleeper_user_id": "78858689238679552",
                "identity_status": "verified_roster_match",
            }
        ]
        with patch("app.main.discover_leagues", return_value=entries) as discover:
            response = self.client.post("/api/leagues/identity/refresh", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        discover.assert_called_once()
        self.assertEqual(discover.call_args.args[1:], ("joe3489", "2026"))
        self.assertTrue(discover.call_args.kwargs["force"])
        stored = db.get_user_league(user_id, "league-a")
        profile = db.get_team_profile(user_id, "league-a")
        self.assertEqual(stored["roster_id"], 2)
        self.assertEqual(stored["identity_status"], "verified_roster_match")
        self.assertEqual(profile["roster_id"], 2)
        self.assertEqual(profile["team_name"], "")
        self.assertEqual(profile["strategy_profile"]["name"], "Rebuild")

    def test_unverified_profile_label_cannot_appear_as_managed_team(self) -> None:
        token = self._token("user_unverified_profile")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_unverified_profile")
        db.upsert_user_league(
            user_id,
            {
                "league_id": "league-a",
                "season": "2026",
                "league_type": "dynasty",
                "name": "Alpha",
                "roster_id": None,
                "identity_status": "unverified",
            },
        )
        db.upsert_team_profile(user_id, "league-a", {"roster_id": 4, "team_name": "Moose Caboose"})

        home = self.client.get("/?league_id=league-a", cookies={"__session": token})
        profile = self.client.get("/api/leagues/league-a/profile", cookies={"__session": token})

        self.assertEqual(home.status_code, 200)
        self.assertNotIn("Managing: <strong>Moose Caboose</strong>", home.text)
        self.assertIn("Roster needs verification", home.text)
        self.assertEqual(profile.json()["team_name"], "")

    def test_league_view_repairs_stale_newsroom_lineup_from_identity_scoped_profile(self) -> None:
        """Design source: AGENTS.md; a new desk must reach the authenticated facade even in an old bundle."""

        stale_editorial = {
            "team_name": "Melkor Lord of Light",
            "headline": "Melkor Lord of Light needs a new read",
            "dek": "Melkor Lord of Light is still the old label.",
            "reporter_lineup": [
                {"article_key": "team_report", "name": "Topline Tony"},
                {"article_key": "market_watch", "name": "Waiver Wire Waverly"},
                {"article_key": "trade_desk", "name": "Trade Desk Talia"},
                {"article_key": "manager_intel", "name": "Dossier Dana"},
                {"article_key": "daily_brief", "name": "Look-Ahead Lonnie"},
            ]
        }
        row = {
            "league_id": "stale-newsroom",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Stale Newsroom",
            "roster_id": 7,
            "identity_status": "verified_roster_match",
            "enabled": 1,
        }
        profile = {
            "roster_id": 7,
            "team_name": "Melkor Lord of Light",
            "writer_preferences": {
                "article_reporters": {"horizon_watch": "scout"},
            },
        }
        with patch.object(db, "get_team_profile", return_value=profile), \
            patch.object(
                app_main,
                "_source_team_rows_for_league",
                return_value=[
                    {"league_id": "stale-newsroom", "season": "2026", "roster_id": 7, "owner_id": "joe", "team_name": "Lulu’s Potatoe’s"},
                    {"league_id": "prior-newsroom", "season": "2025", "roster_id": 7, "owner_id": "joe", "team_name": "Melkor Lord of Light"},
                ],
            ), \
            patch.object(
                app_main,
                "_source_bundle_payload_for_league",
                return_value={
                    "tables": {
                        "teams": [
                            {"league_id": "stale-newsroom", "season": "2026", "roster_id": 7, "owner_id": "joe", "team_name": "Lulu’s Potatoe’s"},
                            {"league_id": "prior-newsroom", "season": "2025", "roster_id": 7, "owner_id": "joe", "team_name": "Melkor Lord of Light"},
                        ],
                    },
                    "analysis": {},
                },
            ), \
            patch.object(app_main, "_refresh_status", return_value={}), \
            patch.object(app_main, "_edition_readiness", return_value={"dot_class": "fresh"}), \
            patch.object(app_main, "_load_editorial_issue", return_value=stale_editorial), \
            patch.object(app_main, "_load_publication_receipt", return_value={}), \
            patch.object(app_main, "_load_writer_preview", return_value={"available": False}), \
            patch.object(db, "content_artifact_status", return_value={}):
            view = app_main._league_view(row, user_id=23)

        lineup = view["editorial"]["reporter_lineup"]
        self.assertEqual(len(lineup), 6)
        self.assertEqual(
            [item["name"] for item in lineup],
            [
                "Topline Tony",
                "Waiver Wire Waverly",
                "The Scout",
                "Trade Desk Talia",
                "Dossier Dana",
                "Look-Ahead Lonnie",
            ],
        )
        self.assertEqual(view["managed_team_name"], "Lulu’s Potatoe’s")
        self.assertEqual(view["editorial"]["team_name"], "Lulu’s Potatoe’s")
        self.assertNotIn("Melkor Lord of Light", view["editorial"].get("headline", ""))

    def test_unready_railway_blocks_linking_into_ephemeral_store(self) -> None:
        token = self._token("user_unready_link")
        with patch.dict(
            os.environ,
            {
                "RAILWAY_PUBLIC_DOMAIN": "fantasy.test",
                "CLERK_PUBLISHABLE_KEY": "pk_test_123",
                "FRONT_OFFICE_DATA_DIR": "",
                "FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret",
                "FRONT_OFFICE_SCHEDULER": "on",
            },
            clear=False,
        ):
            with patch("app.main.discover_leagues") as discover:
                response = self.client.post(
                    "/api/leagues/link",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"sleeper_username": "joe", "season": "2026"},
                )

        self.assertEqual(response.status_code, 503)
        discover.assert_not_called()

    def test_operator_endpoint_requires_auth_and_invokes_start_job(self) -> None:
        unauthenticated = self.client.post("/api/operator/refresh", json={})
        with patch("app.main.front_operator.start_job", return_value={"accepted": True}) as start_job:
            authenticated = self.client.post(
                "/api/operator/refresh",
                headers={"Authorization": f"Bearer {self._token('user_operator')}"},
                json={},
            )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)
        start_job.assert_called_once()
        self.assertEqual(start_job.call_args.args[0], "refresh")

    def test_operator_status_is_league_scoped_and_redacts_private_paths(self) -> None:
        token = self._token("user_status_scope")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_status_scope")
        db.upsert_user_league(
            user_id,
            {"league_id": "status-league", "season": "2026", "league_type": "dynasty", "name": "Status League", "roster_id": 1},
        )
        status_payload = {
            "state": "complete",
            "job": "generate-insights",
            "message": "League refreshed and written.",
            "updated_at": "2026-08-22T18:00:00+00:00",
            "packet_path": "C:/private/packet.json",
            "output_path": "C:/private/output.json",
            "validated_path": "C:/private/validated.json",
            "site_path": "C:/private/index.html",
            "traceback": "C:/private/traceback.py:1",
            "reporter_persona": {"persona_id": "scout"},
        }

        with patch("app.main.front_operator.status", return_value=status_payload) as status, patch(
            "app.main.writer_api_configuration",
            return_value={
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "max",
                "api_key_env": "OPENAI_API_KEY",
                "configured": True,
            },
        ):
            response = self.client.get(
                "/api/operator/status?league_id=status-league",
                cookies={"__session": token},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["state"], "complete")
        self.assertEqual(payload["league_id"], "status-league")
        self.assertEqual(payload["league_name"], "Status League")
        self.assertEqual(payload["reporter_persona"]["persona_id"], "scout")
        self.assertTrue(payload["writer_api_configured"])
        self.assertEqual(payload["writer_provider"], "openai")
        self.assertEqual(payload["writer_model"], "gpt-5.6-luna")
        self.assertEqual(payload["writer_reasoning_effort"], "max")
        self.assertEqual(payload["writer_api_key_env"], "OPENAI_API_KEY")
        self.assertNotIn("packet_path", payload)
        self.assertNotIn("output_path", payload)
        self.assertNotIn("validated_path", payload)
        self.assertNotIn("site_path", payload)
        self.assertNotIn("traceback", payload)
        status.assert_called_once_with(LeaguePaths.for_user_league(str(user_id), "status-league"))

    def test_generation_plan_is_operator_gated_and_league_scoped(self) -> None:
        token = self._token("user_generation_plan")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_generation_plan")
        db.upsert_user_league(
            user_id,
            {"league_id": "plan-league", "season": "2026", "league_type": "dynasty", "name": "Plan League", "roster_id": 2},
        )

        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            denied = self.client.get("/api/operator/generation-plan?league_id=plan-league", cookies={"__session": token})
            with patch(
                "app.main.front_operator.plan_articles_workflow",
                return_value={"state": "ready", "message": "No provider request was made.", "articles": {}},
            ) as plan:
                response = self.client.get(
                    "/api/operator/generation-plan?league_id=plan-league",
                    cookies={"__session": token},
                    headers={"x-front-office-token": "operator-secret"},
                )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "ready")
        plan.assert_called_once()
        self.assertEqual(plan.call_args.args[0], LeaguePaths.for_user_league(str(user_id), "plan-league"))
        self.assertEqual(plan.call_args.args[1].league_id, "plan-league")

    def test_operator_status_reports_safe_selected_reader_contract(self) -> None:
        """Encodes AGENTS.md's deployment-proof rule without exposing bundle paths."""
        token = self._token("user_reader_receipt")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_reader_receipt")
        league = {
            "league_id": "reader-receipt",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Reader Receipt League",
            "roster_id": 1,
        }
        db.upsert_user_league(user_id, league)
        site = self.tmp_path / "users" / str(user_id) / "leagues" / "reader-receipt" / "site"
        _write_complete_bundle(
            site,
            "Cross-season valuation lanes trade_fit_evaluation Team construction Recommendation outcome decision_outcome Recommendation learning",
        )
        receipts = {
            "daily_brief": {
                "mode": "deterministic_template",
                "structured": {"fallback_schema_version": "deterministic_fallback_v2"},
            }
        }
        (site / "data" / "manifest.json").write_text(
            json.dumps({"auditTables": {}, "sourceRevision": "release-current", "bundleRevision": "bundle-1", "articleReceipts": receipts, "dataQuality": _empty_data_quality()}),
            encoding="utf-8",
        )
        (site / "data" / "app_bundle.json").write_text(
            json.dumps({"myRosterId": 1, "identityReceipt": {"roster_id": 1}, "articleReceipts": receipts, "dataQuality": _empty_data_quality()}),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "release-current"}, clear=False), patch(
            "app.main.front_operator.status", return_value={"state": "idle"}
        ), patch(
            "app.main.writer_api_configuration",
            return_value={
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "medium",
                "api_key_env": "OPENAI_API_KEY",
                "configured": False,
            },
        ):
            response = self.client.get(
                "/api/operator/status?league_id=reader-receipt",
                cookies={"__session": token},
            )

        self.assertEqual(response.status_code, 200)
        reader = response.json()["reader_bundle"]
        self.assertEqual(reader["state"], "current")
        self.assertEqual(reader["selected_root"], "private")
        self.assertEqual(reader["served_revision"], "release-current")
        self.assertTrue(reader["shell_contract"])
        self.assertTrue(reader["recommendation_learning_contract"])
        self.assertTrue(reader["manager_dossier_contract"])
        self.assertTrue(reader["data_quality_contract"])
        self.assertTrue(reader["identity_match"])
        self.assertNotIn("site_path", json.dumps(reader))
        self.assertNotIn(str(self.tmp_path), json.dumps(reader))

    def test_stale_reader_is_not_served_when_recovery_does_not_make_it_current(self) -> None:
        """A failed migration must produce an honest recovery state, not old HTML."""
        token = self._token("user_stale_recovery")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_stale_recovery")
        league = {
            "league_id": "stale-recovery",
            "season": "2026",
            "league_type": "dynasty",
            "name": "Stale Recovery League",
            "roster_id": 1,
        }
        db.upsert_user_league(user_id, league)
        site = self.tmp_path / "users" / str(user_id) / "leagues" / "stale-recovery" / "site"
        _write_complete_bundle(site, "OLD PRIVATE READER")
        (site / "data" / "manifest.json").write_text(
            json.dumps({"auditTables": {}, "sourceRevision": "release-old"}),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "release-new"}, clear=False), patch(
            "app.main._rebuild_missing_bundle"
        ) as rebuild:
            response = self.client.get("/league/stale-recovery/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        self.assertIn("edition", response.text.lower())
        self.assertNotIn("OLD PRIVATE READER", response.text)
        rebuild.assert_called_once()

    def test_operator_endpoint_requires_configured_operator_token(self) -> None:
        token = self._token("user_operator_token")
        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            denied = self.client.post(
                "/api/operator/refresh",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
            with patch("app.main.front_operator.start_job", return_value={"accepted": True}):
                allowed = self.client.post(
                    "/api/operator/refresh",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "x-front-office-token": "operator-secret",
                    },
                    json={},
                )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_storage_audit_is_operator_gated_and_does_not_expose_other_identity(self) -> None:
        token = self._token("user_storage_audit")
        self.client.get("/", cookies={"__session": token})
        current_user_id = self._user_id("user_storage_audit")
        other_user = db.get_or_create_user("other_storage_identity")
        db.upsert_user_league(
            current_user_id,
            {"league_id": "current-league", "season": "2026", "league_type": "dynasty", "name": "Current", "roster_id": 1},
        )
        db.upsert_user_league(
            int(other_user["id"]),
            {"league_id": "other-league", "season": "2026", "league_type": "dynasty", "name": "Other Secret", "roster_id": 2},
        )

        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            denied = self.client.get("/api/operator/storage-audit", cookies={"__session": token})
            allowed = self.client.get(
                "/api/operator/storage-audit",
                cookies={"__session": token},
                headers={"x-front-office-token": "operator-secret"},
            )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        payload = allowed.json()
        self.assertTrue(payload["current_user_present"])
        self.assertEqual(payload["current_user_leagues"], 1)
        self.assertEqual(payload["other_users"], 1)
        self.assertEqual(payload["other_user_leagues"], 1)
        self.assertNotIn("Other Secret", str(payload))
        self.assertNotIn("other_storage_identity", str(payload))

    def test_content_artifact_status_distinguishes_reporter_output_from_fallback(self) -> None:
        user = db.get_or_create_user("user_content_status")
        user_id = int(user["id"])
        fallback = db.content_artifact_status(user_id, "content-league", "2026")
        self.assertEqual(fallback["state"], "fallback")
        self.assertEqual(fallback["label"], "0/6 reporter articles · evidence-led fallback")

        db.record_content_artifact(
            user_id,
            "content-league",
            "2026",
            "article",
            "team_report",
            "team_report.md",
            source={"mode": "automatic_llm"},
            evidence_fingerprint="evidence-1",
            bundle_revision="bundle-current",
            content_hash="content-1",
            reporter_id="topline_tony",
            writer_mode="automatic_llm",
            model="gpt-5.6-luna",
            generation_metadata={"usage": {"total_tokens": 1234}, "cost_known": False},
        )
        partial = db.content_artifact_status(
            user_id,
            "content-league",
            "2026",
            expected_model="gpt-5.6-luna",
        )
        self.assertEqual(partial["state"], "partial")
        self.assertEqual(partial["label"], "1/6 reporter articles")
        self.assertEqual(partial["generated_keys"], ["team_report"])
        self.assertTrue(partial["last_generated_at"])
        self.assertEqual(partial["last_generated_model"], "gpt-5.6-luna")
        self.assertEqual(partial["model_mismatch_count"], 0)
        self.assertEqual(partial["model_reconciliation"], "prior runs match configured model")

        stale_bundle = db.content_artifact_status(
            user_id,
            "content-league",
            "2026",
            current_receipts={"team_report": {"mode": "automatic_llm", "content_hash": "wrong-content"}},
            current_bundle_revision="bundle-stale",
        )
        self.assertEqual(stale_bundle["state"], "fallback")
        self.assertTrue(stale_bundle["receipt_verified"])
        self.assertEqual(stale_bundle["bundle_revision"], "bundle-stale")

        current_bundle = db.content_artifact_status(
            user_id,
            "content-league",
            "2026",
            current_receipts={"team_report": {"mode": "automatic_llm", "content_hash": "content-1"}},
            current_bundle_revision="bundle-current",
        )
        self.assertEqual(current_bundle["generated_keys"], ["team_report"])

        db.record_content_artifact(
            user_id,
            "content-league",
            "2026",
            "article",
            "team_report",
            "team_report.md",
            source={"mode": "automatic_llm"},
            evidence_fingerprint="evidence-1",
            bundle_revision="bundle-next",
            content_hash="content-1",
            reporter_id="topline_tony",
            writer_mode="automatic_llm",
            model="gpt-5.6-luna",
            generation_metadata={"usage": {"total_tokens": 1234}, "cost_known": False},
        )
        unchanged = db.list_content_artifact_changes(user_id, "content-league", "2026")
        self.assertEqual(unchanged[0]["change_type"], "new")
        self.assertEqual(unchanged[0]["usage"]["total_tokens"], 1234)

        db.record_content_artifact(
            user_id,
            "content-league",
            "2026",
            "article",
            "team_report",
            "team_report.md",
            source={"mode": "automatic_llm"},
            evidence_fingerprint="evidence-2",
            bundle_revision="bundle-next",
            content_hash="content-2",
            reporter_id="topline_tony",
            writer_mode="automatic_llm",
            model="gpt-5.6-luna",
        )
        changed = db.list_content_artifact_changes(user_id, "content-league", "2026")
        self.assertEqual(changed[0]["change_type"], "updated")
        self.assertEqual(changed[0]["prior_evidence_fingerprint"], "evidence-1")

        db.record_content_artifact(
            user_id,
            "content-league",
            "2026",
            "article",
            "market_watch",
            "market_watch.md",
            source={"mode": "automatic_llm"},
            evidence_fingerprint="evidence-old-model",
            bundle_revision="bundle-old-model",
            content_hash="content-old-model",
            reporter_id="waiver_wire_waverly",
            writer_mode="automatic_llm",
            model="legacy-writer-model",
        )
        mismatched = db.content_artifact_status(
            user_id,
            "content-league",
            "2026",
            expected_model="gpt-5.6-luna",
        )
        self.assertEqual(mismatched["last_generated_model"], "legacy-writer-model")
        self.assertEqual(mismatched["model_mismatch_count"], 1)
        self.assertEqual(mismatched["model_reconciliation"], "prior run needs regeneration")

    def test_content_feedback_is_explicit_and_scoped_to_the_verified_roster(self) -> None:
        """Encodes docs/front_office_realization_epic.md Workstream 9 and AGENTS.md privacy rules."""
        token = self._token("user_content_feedback")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_content_feedback")
        db.upsert_user_league(
            user_id,
            {"league_id": "feedback-league", "season": "2026", "league_type": "dynasty", "name": "Feedback", "roster_id": 7},
        )

        saved = self.client.post(
            "/api/leagues/feedback-league/content-interactions",
            cookies={"__session": token},
            json={
                "artifact_key": "trade_desk",
                "interaction_type": "useful",
                "payload": {"bundle_revision": "rev-1"},
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["roster_id"], 7)

        listed = self.client.get("/api/leagues/feedback-league/content-interactions", cookies={"__session": token})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["interactions"][0]["interaction_type"], "useful")
        self.assertEqual(listed.json()["interactions"][0]["payload"]["bundle_revision"], "rev-1")

        outcome = self.client.post(
            "/api/leagues/feedback-league/content-interactions",
            cookies={"__session": token},
            json={
                "artifact_key": "trade_desk",
                "interaction_type": "outcome",
                "payload": {"outcome": "confirmed", "prediction_key": "trade_desk:trade_desk"},
            },
        )
        self.assertEqual(outcome.status_code, 200)
        self.assertEqual(outcome.json()["payload"]["outcome"], "confirmed")
        outcome_rows = self.client.get(
            "/api/leagues/feedback-league/content-interactions",
            cookies={"__session": token},
        ).json()["interactions"]
        self.assertEqual(next(row for row in outcome_rows if row["interaction_type"] == "outcome")["payload"]["prediction_key"], "trade_desk:trade_desk")

        recommendation_outcome = self.client.post(
            "/api/leagues/feedback-league/content-interactions",
            cookies={"__session": token},
            json={
                "artifact_type": "recommendation",
                "artifact_key": "target:player-11566",
                "interaction_type": "decision_outcome",
                "payload": {
                    "outcome": "confirmed",
                    "prediction_key": "recommendation:target:player-11566:rev-1",
                    "decision_type": "target",
                    "subject_id": "11566",
                    "bundle_revision": "rev-1",
                },
            },
        )
        self.assertEqual(recommendation_outcome.status_code, 200)
        self.assertEqual(recommendation_outcome.json()["artifact_type"], "recommendation")

        summary = self.client.get(
            "/api/leagues/feedback-league/learning-summary",
            cookies={"__session": token},
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["roster_id"], 7)
        self.assertEqual(summary.json()["interaction_count"], 3)
        self.assertEqual(summary.json()["artifact_count"], 2)
        self.assertEqual(summary.json()["feedback_counts"]["useful"], 1)
        self.assertEqual(summary.json()["outcome_counts"]["confirmed"], 1)
        self.assertEqual(summary.json()["confirmed_rate"], 1.0)
        self.assertEqual(summary.json()["recommendation_count"], 1)
        self.assertEqual(summary.json()["recommendation_outcome_counts"]["confirmed"], 1)
        self.assertEqual(summary.json()["recommendation_resolved_outcomes"], 1)
        self.assertEqual(summary.json()["recommendation_confirmed_rate"], 1.0)

        db.record_content_artifact(
            user_id,
            "feedback-league",
            "2026",
            "article",
            "trade_desk",
            "trade_desk.md",
            roster_id=7,
            evidence_fingerprint="packet-1",
            content_hash="article-1",
            reporter_id="trade_desk_talia",
            writer_mode="automatic_llm",
            model="gpt-5.6-luna",
        )
        reporter_summary = self.client.get(
            "/api/leagues/feedback-league/learning-summary",
            cookies={"__session": token},
        )
        self.assertEqual(reporter_summary.status_code, 200)
        breakdown = reporter_summary.json()["reporter_breakdown"]
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["reporter_id"], "trade_desk_talia")
        self.assertEqual(breakdown[0]["artifact_count"], 1)
        self.assertEqual(breakdown[0]["interaction_count"], 2)
        self.assertEqual(breakdown[0]["confirmed_rate"], 1.0)
        changes = self.client.get(
            "/api/leagues/feedback-league/edition-changes",
            cookies={"__session": token},
        )
        self.assertEqual(changes.status_code, 200)
        self.assertEqual(changes.json()["roster_id"], 7)
        self.assertEqual(changes.json()["changes"][0]["change_type"], "new")

        denied = self.client.post(
            "/api/leagues/feedback-league/content-interactions",
            cookies={"__session": token},
            json={"artifact_key": "trade_desk", "interaction_type": "invented"},
        )
        self.assertEqual(denied.status_code, 422)
        invalid_outcome = self.client.post(
            "/api/leagues/feedback-league/content-interactions",
            cookies={"__session": token},
            json={
                "artifact_type": "recommendation",
                "artifact_key": "target:player-11566",
                "interaction_type": "decision_outcome",
                "payload": {"outcome": "maybe"},
            },
        )
        self.assertEqual(invalid_outcome.status_code, 422)

    def test_user_refresh_endpoint_is_not_operator_protected(self) -> None:
        token = self._token("user_refresh")
        with patch.dict(os.environ, {"FRONT_OFFICE_OPERATOR_TOKEN": "operator-secret"}, clear=False):
            with patch("app.main.front_operator.start_job", return_value={"accepted": True}) as start_job:
                response = self.client.post(
                    "/api/leagues/refresh",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(response.status_code, 200)
        start_job.assert_called_once()
        self.assertEqual(start_job.call_args.args[0], "refresh")

    def test_targeted_refresh_endpoint_queues_owned_league_refresh(self) -> None:
        token = self._token("user_targeted_refresh")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_targeted_refresh")
        db.upsert_user_league(
            user_id,
            {"league_id": "targeted", "season": "2026", "league_type": "dynasty", "name": "Targeted", "roster_id": 2},
        )

        with patch("app.main.front_operator.start_job", return_value={"accepted": True}) as start_job:
            response = self.client.post("/api/leagues/targeted/refresh", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        start_job.assert_called_once()
        self.assertEqual(start_job.call_args.args[0], "refresh")

    def test_league_readiness_reports_building_then_failed(self) -> None:
        token = self._token("user_readiness")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_readiness")
        db.upsert_user_league(
            user_id,
            {"league_id": "readiness", "season": "2026", "league_type": "dynasty", "name": "Readiness", "roster_id": 1},
        )
        run_id = db.start_refresh_run(user_id, "readiness", "2026")

        building = self.client.get("/api/leagues/readiness/readiness", cookies={"__session": token})
        self.assertEqual(building.status_code, 200)
        self.assertEqual(building.json()["state"], "building")
        self.assertEqual(building.json()["label"], "Building")

        db.finish_refresh_run(run_id, "failed", "Sleeper timed out")
        failed = self.client.get("/api/leagues/readiness/readiness", cookies={"__session": token})
        self.assertEqual(failed.status_code, 200)
        self.assertEqual(failed.json()["state"], "needs_refresh")
        self.assertEqual(failed.json()["refresh_state"], "failed")
        self.assertIn("Sleeper timed out", failed.json()["error"])

        paths = LeaguePaths.for_user_league(str(user_id), "readiness")
        paths.site_dir.mkdir(parents=True)
        _write_complete_bundle(paths.site_dir, "<h1>Last good edition</h1>")
        stale = self.client.get("/api/leagues/readiness/readiness", cookies={"__session": token})
        self.assertEqual(stale.json()["state"], "stale")

    def test_missing_league_bundle_returns_branded_recovery_page(self) -> None:
        token = self._token("user_missing_bundle")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_missing_bundle")
        db.upsert_user_league(
            user_id,
            {"league_id": "missing-bundle", "season": "2026", "league_type": "dynasty", "name": "Missing Bundle", "roster_id": 1},
        )

        response = self.client.get("/league/missing-bundle/", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        self.assertIn('data-testid="edition-recovery"', response.text)
        self.assertIn("Your edition is Needs refresh.", response.text)
        self.assertIn("Back to headquarters", response.text)
        self.assertEqual(response.headers["retry-after"], "15")

    def test_incomplete_bundle_never_returns_raw_missing_file_json(self) -> None:
        token = self._token("user_incomplete_bundle")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_incomplete_bundle")
        db.upsert_user_league(
            user_id,
            {"league_id": "incomplete", "season": "2026", "league_type": "dynasty", "name": "Incomplete", "roster_id": 1},
        )
        paths = LeaguePaths.for_user_league(str(user_id), "incomplete")
        paths.site_dir.mkdir(parents=True)
        (paths.site_dir / "index.html").write_text("<h1>Shell only</h1>", encoding="utf-8")

        response = self.client.get("/league/incomplete/data/app_bundle.json", cookies={"__session": token})

        self.assertEqual(response.status_code, 503)
        self.assertIn('data-testid="edition-recovery"', response.text)
        self.assertIn('data-testid="reader-contract-status"', response.text)
        self.assertNotIn('"detail":"league file not found"', response.text)

    def test_missing_bundle_rebuilds_from_processed_facts(self) -> None:
        token = self._token("user_bundle_repair")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_bundle_repair")
        db.upsert_user_league(
            user_id,
            {"league_id": "repair", "season": "2026", "league_type": "dynasty", "name": "Repair", "roster_id": 1},
        )
        paths = LeaguePaths.for_user_league(str(user_id), "repair")
        paths.processed_dir.mkdir(parents=True)
        (paths.processed_dir / "refresh_metadata.csv").write_text("generated_at\n2026-08-01T00:00:00+00:00\n", encoding="utf-8")

        def fake_build(site_dir: Path, *args: object, **kwargs: object) -> Path:
            _write_complete_bundle(
                site_dir,
                "Cross-season valuation lanes trade_fit_evaluation Team construction <h1>Recovered edition</h1>",
            )
            return site_dir / "index.html"

        with patch("app.main.build_browser_site", side_effect=fake_build) as builder:
            response = self.client.get("/league/repair/", cookies={"__session": token})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Recovered edition", response.text)
        builder.assert_called_once()

    def test_rebuild_browser_job_embeds_user_league_profile(self) -> None:
        token = self._token("user_scoped_bundle")
        self.client.get("/", cookies={"__session": token})
        user_id = self._user_id("user_scoped_bundle")
        league = db.upsert_user_league(
            user_id,
            {
                "league_id": "scoped-league",
                "season": "2026",
                "league_type": "dynasty",
                "name": "Scoped League",
                "roster_id": 4,
            },
        )
        db.upsert_team_profile(
            user_id,
            "scoped-league",
            {
                "team_name": "The Actual Team",
                "display_name": "joe3489",
                "strategy_name": "Win the window",
                "team_direction": "contend",
                "writer_preferences": {"persona_id": "scout", "custom_instructions": "Stay close to role evidence."},
            },
        )

        with patch("app.main.build_browser_site", return_value=Path("scoped/index.html")) as builder:
            app_main._rebuild_browser_job(league, user_id)

        config = builder.call_args.kwargs["config"]
        self.assertEqual(config["current_season"], "2026")
        self.assertEqual(config["current_team"]["team_name"], "The Actual Team")
        self.assertEqual(config["strategy_profile"]["name"], "Win the window")
        self.assertEqual(config["writer_preferences"]["persona_id"], "scout")
        self.assertEqual(config["writer_preferences"]["custom_instructions"], "Stay close to role evidence.")
        self.assertEqual(config["context"]["league_id"], "scoped-league")

    def test_healthz_is_open(self) -> None:
        payload = self.client.get("/healthz").json()
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["auth_mode"], "development")
        self.assertIn("revision", payload)
        self.assertIn("auth_configuration_ready", payload)
        self.assertIn("public_url_configured", payload)
        self.assertIn("public_url_ready", payload)
        self.assertIn("data_root_configured", payload)
        self.assertIn("database_present", payload)
        self.assertIn("database_schema_ready", payload)
        self.assertIn("writer_api_configured", payload)
        self.assertIn("operator_token_configured", payload)
        self.assertIn("scheduler_enabled", payload)
        self.assertIn("deployment_ready", payload)
        self.assertIn("deployment_blockers", payload)

    def _token(
        self,
        sub: str,
        exp: datetime | None = None,
        issuer: str = "https://clerk.test",
        azp: str = "http://localhost:8765",
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "iss": issuer,
            "sub": sub,
            "exp": exp or now + timedelta(minutes=10),
            "nbf": now - timedelta(minutes=1),
            "azp": azp,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256", headers={"kid": "test-key"})

    def _user_id(self, clerk_user_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM users WHERE clerk_user_id = ?", (clerk_user_id,)).fetchone()
        self.assertIsNotNone(row)
        return int(row[0])

if __name__ == "__main__":
    unittest.main()
