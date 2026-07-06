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
from app.main import create_app
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
                    "total_rosters": 12,
                },
                {
                    "league_id": "league-b",
                    "name": "Beta",
                    "season": "2026",
                    "league_type": "best_ball",
                    "roster_id": None,
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
            patch.object(auth, "JWKS_PROVIDER", lambda: self.jwks),
            patch.dict(
                os.environ,
                {
                    "CLERK_ISSUER": "https://clerk.test",
                    "CLERK_JWKS_URL": "https://clerk.test/.well-known/jwks.json",
                    "CLERK_PUBLISHABLE_KEY": "pk_test_123",
                    "CLERK_AUTHORIZED_PARTIES": "http://localhost:8765,https://fantasy.test",
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

    def test_valid_token_serves_home_and_auto_provisions_user(self) -> None:
        response = self.client.get("/", cookies={"__session": self._token("user_valid")})

        self.assertEqual(response.status_code, 200)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT clerk_user_id FROM users").fetchone()
        self.assertEqual(row[0], "user_valid")

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
        own_token = self._token("user_owner")
        other_token = self._token("user_other")
        self.client.get("/", cookies={"__session": own_token})
        self.client.get("/", cookies={"__session": other_token})
        owner_id = self._user_id("user_owner")
        db.upsert_user_league(owner_id, {"league_id": "league-a", "season": "2026", "league_type": "dynasty", "name": "Alpha", "roster_id": 7})
        site_dir = self.leagues_root / "league-a" / "site"
        site_dir.mkdir(parents=True)
        (site_dir / "index.html").write_text("<h1>Alpha</h1>", encoding="utf-8")
        (self.tmp_path / "outside.txt").write_text("nope", encoding="utf-8")

        other_response = self.client.get("/league/league-a/", cookies={"__session": other_token})
        traversal = self.client.get("/league/league-a/%2e%2e/%2e%2e/outside.txt", cookies={"__session": own_token})
        index = self.client.get("/league/league-a/", cookies={"__session": own_token})

        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(traversal.status_code, 404)
        self.assertEqual(index.status_code, 200)
        self.assertIn("Alpha", index.text)

    def test_link_leagues_upserts_and_returns_discovered_entries(self) -> None:
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
        stored = db.list_user_leagues(self._user_id("user_link"))
        self.assertEqual(stored[0]["name"], "Linked")

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

    def test_healthz_is_open(self) -> None:
        self.assertEqual(self.client.get("/healthz").json(), {"ok": True})

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
