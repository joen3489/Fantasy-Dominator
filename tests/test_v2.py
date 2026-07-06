from __future__ import annotations

"""Focused tests for the multi-league path and orchestration layer."""

import inspect
import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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

if __name__ == "__main__":
    unittest.main()
