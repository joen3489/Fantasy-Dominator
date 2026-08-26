from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from src.articles import ArticleContext, _scope_horizon_watch, _scope_market_watch, _scope_team_report, _scope_trade_desk
from src.context import FantasyContext, context_from_league_row, scoped_config
from src.league_paths import LeaguePaths


class ContextIsolationTests(unittest.TestCase):
    def test_horizon_writer_packet_keeps_percentiles_position_local(self) -> None:
        """Design source: docs/data_contract.md; do not create a cross-position percentile leaderboard."""
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp)
            (processed / "player_horizon_market_scores.csv").write_text(
                "season,player_id,player_name,position,next_game_market_score,rest_of_season_market_score,rest_of_season_minus_next_game_delta,dynasty_market_score,dynasty_minus_rest_of_season_delta,career_projection_score,career_minus_dynasty_delta,contender_fit_score,rebuilder_fit_score,rebuilder_contender_spread,value_lane,market_value,market_percentile,source_trace\n"
                "2026,qb-1,Quarterback One,QB,90,80,-10,55,-25,50,-5,82,57,-25,contender_edge,75,92,horizon\n"
                "2026,qb-2,Quarterback Two,QB,88,82,-6,60,-22,55,-5,80,62,-18,contender_edge,60,85,horizon\n"
                "2026,wr-1,Receiver One,WR,35,50,15,88,38,91,3,44,86,42,rebuilder_edge,35,70,horizon\n",
                encoding="utf-8",
            )
            rows = _scope_horizon_watch(
                ArticleContext(
                    analysis_dir=processed,
                    processed_dir=processed,
                    active_roster_id=2,
                    season="2026",
                )
            )

        self.assertEqual(
            {row["name"] for row in rows},
            {"Quarterback One", "Quarterback Two", "Receiver One"},
        )
        self.assertEqual({row["position"] for row in rows}, {"QB", "WR"})
        self.assertTrue(all(row["evidence_id"].startswith("player:") for row in rows))

    def test_horizon_writer_packet_rejects_other_league_rows(self) -> None:
        """Design source: AGENTS.md; league identity precedes writer evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp)
            (processed / "player_horizon_market_scores.csv").write_text(
                "season,league_id,player_id,player_name,position,next_game_market_score,rest_of_season_market_score,dynasty_market_score,career_projection_score,contender_fit_score,rebuilder_fit_score,rebuilder_contender_spread,value_lane,market_value,market_percentile\n"
                "2026,league-a,a-qb,League A QB,QB,70,70,70,70,70,70,0,balanced_window,50,70\n"
                "2026,league-b,b-qb,League B QB,QB,99,99,99,99,99,99,0,balanced_window,90,99\n",
                encoding="utf-8",
            )
            rows = _scope_horizon_watch(
                ArticleContext(
                    analysis_dir=processed,
                    processed_dir=processed,
                    active_roster_id=2,
                    league_id="league-a",
                    season="2026",
                )
            )

        self.assertEqual({row["name"] for row in rows}, {"League A QB"})

    def test_scoped_config_clears_singleton_team_customization(self) -> None:
        base = {
            "current_team": {
                "roster_id": 2,
                "display_name": "Legacy Joe",
                "team_name": "Legacy Team",
            },
            "strategy_profile": {"name": "Legacy rebuild", "team_direction": "rebuild"},
            "current_season": "2026",
        }
        context = FantasyContext(
            user_id="17",
            league_id="league-b",
            season="2026",
            roster_id=9,
            team_name="New Team",
            strategy_profile={"name": "Win now", "team_direction": "contend"},
        )

        scoped = scoped_config(base, context)

        self.assertEqual(scoped["current_team"]["roster_id"], 9)
        self.assertEqual(scoped["current_team"]["team_name"], "New Team")
        self.assertEqual(scoped["current_team"]["display_name"], "")
        self.assertEqual(scoped["strategy_profile"]["name"], "Win now")
        self.assertEqual(scoped["context"]["league_id"], "league-b")
        self.assertEqual(base["strategy_profile"]["name"], "Legacy rebuild")

    def test_unverified_league_cannot_inherit_roster_from_private_profile(self) -> None:
        context = context_from_league_row(
            "17",
            {
                "league_id": "league-a",
                "season": "2026",
                "sleeper_user_id": "sleeper-17",
                "identity_status": "unverified",
                "roster_id": None,
            },
            {"roster_id": 4, "team_name": "Moose Caboose"},
        )

        self.assertIsNone(context.roster_id)
        self.assertEqual(context.team_name, "")
        self.assertEqual(context.sleeper_user_id, "sleeper-17")

    def test_scoped_config_carries_sleeper_identity_without_using_it_as_roster_identity(self) -> None:
        """Design source: AGENTS.md; the Sleeper user is lineage, roster_id is team identity."""
        context = FantasyContext(
            user_id="17",
            sleeper_user_id="sleeper-17",
            league_id="league-a",
            season="2026",
            roster_id=2,
        )

        scoped = scoped_config({}, context)

        self.assertEqual(scoped["context"]["sleeper_user_id"], "sleeper-17")
        self.assertEqual(scoped["context"]["roster_id"], 2)

    def test_user_league_rows_retain_linked_sleeper_user_id(self) -> None:
        """Design source: docs/front_office_principles.md; league rows retain owner lineage."""
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("clerk-17")
                db.set_sleeper_account(int(user["id"]), "sleeperjoe", "sleeper-17")
                db.upsert_user_league(
                    int(user["id"]),
                    {
                        "league_id": "league-a",
                        "season": "2026",
                        "league_type": "dynasty",
                        "name": "Alpha",
                        "roster_id": 2,
                        "identity_status": "verified_roster_match",
                    },
                )

                stored = db.list_user_leagues(int(user["id"]))

        self.assertEqual(stored[0]["sleeper_user_id"], "sleeper-17")

    def test_user_league_paths_are_private_and_reject_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "users"
            with patch("src.league_paths.USERS_ROOT", root):
                first = LeaguePaths.for_user_league("101", "league-a")
                second = LeaguePaths.for_user_league("202", "league-a")
                self.assertNotEqual(first.root, second.root)
                self.assertEqual(first.root, root / "101" / "leagues" / "league-a")
                with self.assertRaises(ValueError):
                    LeaguePaths.for_user_league("101", "../other")

    def test_team_profiles_and_content_artifacts_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "app.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                first = db.get_or_create_user("first")
                second = db.get_or_create_user("second")
                db.upsert_team_profile(
                    int(first["id"]),
                    "league-a",
                    {
                        "roster_id": 1,
                        "season": "2026",
                        "team_name": "First Team",
                        "strategy_profile": {"team_direction": "contend"},
                    },
                )
                db.upsert_team_profile(
                    int(second["id"]),
                    "league-a",
                    {
                        "roster_id": 2,
                        "season": "2026",
                        "team_name": "Second Team",
                        "strategy_profile": {"team_direction": "rebuild"},
                    },
                )

                self.assertEqual(
                    db.get_team_profile(int(first["id"]), "league-a")["team_name"],
                    "First Team",
                )
                self.assertEqual(
                    db.get_team_profile(int(second["id"]), "league-a")["strategy_profile"]["team_direction"],
                    "rebuild",
                )
                db.record_content_artifact(
                    int(first["id"]), "league-a", "2026", "article", "market_watch", "first.md"
                )
                self.assertIsNone(db.get_team_profile(int(first["id"]), "league-b"))

    def test_legacy_profile_migration_does_not_overwrite_customization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("custom")
                db.upsert_team_profile(
                    int(user["id"]),
                    "league-a",
                    {"roster_id": 2, "season": "2026", "team_name": "Custom Team", "strategy_profile": {"name": "Contend"}},
                )
                migrated = db.migrate_legacy_team_profile(
                    int(user["id"]),
                    {"league_id": "league-a", "season": "2026", "roster_id": 2},
                    {
                        "current_team": {"roster_id": 2, "team_name": "Legacy Team"},
                        "strategy_profile": {"name": "Legacy Rebuild"},
                    },
                )

                self.assertEqual(migrated["team_name"], "Custom Team")
                self.assertEqual(db.get_team_profile(int(user["id"]), "league-a")["strategy_profile"]["name"], "Contend")

    def test_team_profile_update_preserves_unedited_private_strategy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("strategy-preservation")
                user_id = int(user["id"])
                db.upsert_team_profile(
                    user_id,
                    "league-a",
                    {
                        "roster_id": 2,
                        "season": "2026",
                        "team_name": "Original Team",
                        "strategy_profile": {
                            "name": "Build through 2027",
                            "team_direction": "deep_rebuild",
                            "core_holds": ["Jayden Daniels"],
                            "tracked_picks": [{"pick_season": "2027", "round": 1}],
                            "horizon_fit_weights": {
                                "contender": {"next_game": 60, "rest_of_season": 25, "dynasty": 10, "career_window": 5},
                                "rebuilder": {"next_game": 5, "rest_of_season": 20, "dynasty": 45, "career_window": 30},
                            },
                        },
                    },
                )
                db.upsert_team_profile(
                    user_id,
                    "league-a",
                    {
                        "roster_id": 2,
                        "season": "2026",
                        "team_name": "Renamed Team",
                        "strategy_profile": {"name": "Updated strategy", "team_direction": "rebuild"},
                    },
                )

                strategy = db.get_team_profile(user_id, "league-a")["strategy_profile"]
                self.assertEqual(strategy["name"], "Updated strategy")
                self.assertEqual(strategy["team_direction"], "rebuild")
                self.assertEqual(strategy["core_holds"], ["Jayden Daniels"])
                self.assertEqual(strategy["tracked_picks"][0]["pick_season"], "2027")
                self.assertEqual(strategy["horizon_fit_weights"]["rebuilder"]["dynasty"], 45)

    def test_identity_reconciliation_rekeys_profile_and_clears_stale_team_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(db, "DB_PATH", Path(temporary) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("identity-repair")
                user_id = int(user["id"])
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
                    {
                        "roster_id": 4,
                        "season": "2026",
                        "team_name": "Moose Caboose",
                        "display_name": "stale-manager",
                        "strategy_profile": {"name": "Keep this strategy", "team_direction": "rebuild"},
                        "writer_preferences": {"persona_id": "scout"},
                    },
                )

                previous = db.get_user_league(user_id, "league-a")
                current = db.upsert_user_league(
                    user_id,
                    {
                        "league_id": "league-a",
                        "season": "2026",
                        "league_type": "dynasty",
                        "name": "Alpha",
                        "roster_id": 2,
                        "identity_status": "verified_roster_match",
                    },
                )
                repaired = db.reconcile_team_profile_identity(user_id, current, previous)

                self.assertEqual(repaired["roster_id"], 2)
                self.assertEqual(repaired["team_name"], "")
                self.assertEqual(repaired["display_name"], "")
                self.assertEqual(repaired["strategy_profile"]["name"], "Keep this strategy")
                self.assertEqual(repaired["writer_preferences"]["persona_id"], "scout")

    def test_article_scope_reads_selected_processed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            processed = Path(temporary) / "processed"
            analysis = Path(temporary) / "analysis"
            processed.mkdir()
            analysis.mkdir()
            with (processed / "player_dossiers.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["roster_id", "player_id", "player_name", "market_value"],
                )
                writer.writeheader()
                writer.writerow({"roster_id": "9", "player_id": "p9", "player_name": "Private Player", "market_value": "40"})

            context = ArticleContext(analysis_dir=analysis, active_roster_id=9, processed_dir=processed)
            rows = _scope_team_report(context)

            self.assertEqual([row["name"] for row in rows], ["Private Player"])

    def test_market_writer_packet_preserves_four_window_scores(self) -> None:
        """Design source: docs/data_contract.md and AGENTS.md horizon evidence rules."""
        with tempfile.TemporaryDirectory() as temporary:
            processed = Path(temporary) / "processed"
            analysis = Path(temporary) / "analysis"
            processed.mkdir()
            analysis.mkdir()
            with (processed / "player_horizon_market_scores.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "season", "horizon_model_version", "horizon_score_basis", "player_id", "player_name", "market_value", "market_percentile", "next_game_market_score",
                        "next_game_baseline_points", "next_game_expected_points", "next_game_status", "next_game_minus_market_delta", "rest_of_season_market_score",
                        "rest_of_season_weeks", "rest_of_season_baseline_points", "rest_of_season_ppg", "rest_of_season_basis", "rest_of_season_minus_market_delta", "rest_of_season_minus_next_game_delta",
                        "dynasty_market_score", "dynasty_minus_market_delta", "dynasty_minus_rest_of_season_delta", "dynasty_status", "injury_status", "availability_note",
                        "next_game_matchup_validation_status", "next_game_matchup_validation_games", "next_game_matchup_validation_mae_delta", "next_game_matchup_adjustment_status",
                        "career_projection_score", "career_minus_market_delta", "career_minus_dynasty_delta", "career_projection_status",
                        "career_history_join_method", "career_history_source_player_id", "career_history_status", "career_history_seasons", "career_history_games", "career_history_ppg", "career_history_latest_season",
                        "contender_fit_score", "rebuilder_fit_score", "fit_basis", "rebuilder_contender_spread",
                        "value_lane", "risk", "confidence", "source_trace",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "season": "2026",
                        "horizon_model_version": "horizon_market_v2",
                        "horizon_score_basis": "position-relative percentile score from 0-100 within the current season cohort; not a dollar market value and not a cross-position price ranking",
                        "player_id": "p1",
                        "player_name": "Horizon Player",
                        "market_value": "40",
                        "market_percentile": "35",
                        "next_game_market_score": "42",
                        "next_game_minus_market_delta": "7",
                        "next_game_baseline_points": "14.0",
                        "next_game_expected_points": "12.5",
                        "next_game_status": "opponent_neutral_weekly_allocation",
                        "next_game_matchup_validation_status": "validated_improvement",
                        "next_game_matchup_validation_games": "24",
                        "next_game_matchup_validation_mae_delta": "1.75",
                        "next_game_matchup_adjustment_status": "applied",
                        "rest_of_season_market_score": "71",
                        "rest_of_season_minus_market_delta": "36",
                        "rest_of_season_minus_next_game_delta": "29",
                        "rest_of_season_weeks": "16",
                        "rest_of_season_baseline_points": "224",
                        "rest_of_season_ppg": "14",
                        "rest_of_season_basis": "production baseline; rest-of-season baseline is not recovery-adjusted",
                        "dynasty_market_score": "88",
                        "dynasty_minus_market_delta": "53",
                        "dynasty_minus_rest_of_season_delta": "17",
                        "dynasty_status": "external_market_plus_timeline",
                        "injury_status": "Questionable",
                        "availability_note": "Questionable (knee)",
                        "career_projection_score": "82",
                        "career_minus_market_delta": "47",
                        "career_minus_dynasty_delta": "-6",
                        "career_projection_status": "internal_age_curve_5yr",
                        "career_history_join_method": "normalized_name_position_unique_source_id",
                        "career_history_source_player_id": "history-p1",
                        "career_history_status": "matched",
                        "career_history_seasons": "2",
                        "career_history_games": "34",
                        "career_history_ppg": "17.25",
                        "career_history_latest_season": "2025",
                        "contender_fit_score": "53",
                        "rebuilder_fit_score": "90",
                        "fit_basis": "contender fit weights next game 52%",
                        "rebuilder_contender_spread": "37",
                        "value_lane": "rebuilder_edge",
                        "risk": "medium",
                        "confidence": "medium",
                        "source_trace": "horizon:test",
                    }
                )

            rows = _scope_market_watch(
                ArticleContext(
                    analysis_dir=analysis,
                    active_roster_id=None,
                    processed_dir=processed,
                    season="2026",
                )
            )

        horizon = next(row for row in rows if row["name"] == "Horizon Player")
        self.assertIn("model=horizon_market_v2", horizon["text"])
        self.assertIn("next game score=42", horizon["text"])
        self.assertIn("rest of season score=71", horizon["text"])
        self.assertIn("dynasty market score=88", horizon["text"])
        self.assertIn("five-year career-window score=82", horizon["text"])
        self.assertIn("matchup holdout=validated_improvement", horizon["text"])
        self.assertEqual(horizon["next_game_matchup_adjustment_status"], "applied")
        self.assertIn("availability=Questionable (knee)", horizon["text"])
        self.assertIn("rest-of-season basis=production baseline; rest-of-season baseline is not recovery-adjusted", horizon["text"])
        self.assertIn("score basis=position-relative percentile", horizon["text"])
        self.assertIn("cross-position price anchor market value=40", horizon["text"])
        self.assertIn("market percentile (position)=35", horizon["text"])
        self.assertEqual(horizon["contender_fit_score"], "53")
        self.assertEqual(horizon["rebuilder_fit_score"], "90")
        self.assertEqual(horizon["rest_of_season_minus_next_game_delta"], "29")
        self.assertEqual(horizon["next_game_minus_market_delta"], "7")
        self.assertEqual(horizon["rest_of_season_minus_market_delta"], "36")
        self.assertEqual(horizon["dynasty_minus_market_delta"], "53")
        self.assertEqual(horizon["career_minus_market_delta"], "47")
        self.assertEqual(horizon["dynasty_minus_rest_of_season_delta"], "17")
        self.assertEqual(horizon["career_minus_dynasty_delta"], "-6")
        self.assertEqual(horizon["horizon_model_version"], "horizon_market_v2")
        self.assertIn("not a dollar market value", horizon["horizon_score_basis"])
        self.assertIn("contender fit weights", horizon["fit_basis"])
        self.assertEqual(horizon["horizon_lane"], "rebuilder edge")
        self.assertEqual(horizon["career_projection_score"], "82")
        self.assertIn("career history=matched", horizon["text"])
        self.assertEqual(horizon["career_history_join_method"], "normalized_name_position_unique_source_id")
        self.assertEqual(horizon["career_history_source_player_id"], "history-p1")
        self.assertEqual(horizon["career_history_games"], "34")

    def test_market_writer_packet_only_carries_identity_resolved_available_rows(self) -> None:
        """Design source: AGENTS.md identity boundary and docs/data_contract.md available-market contract."""
        with tempfile.TemporaryDirectory() as temporary:
            processed = Path(temporary)
            (processed / "available_player_horizon_scores.csv").write_text(
                "league_id,season,player_id,player_name,position,availability_status,identity_status,fit_coverage,next_game_market_score,rest_of_season_market_score,dynasty_market_score,career_projection_score,rebuilder_contender_spread,value_lane,market_value,market_percentile,source_trace\n"
                "league-a,2026,p-available,Available Clock WR,WR,not_rostered_in_selected_league,sleeper_id,4/4,72,84,61,70,18,rebuilder_edge,12,66,horizon:available\n"
                "league-a,2026,p-rostered,Rostered By Rival,WR,not_rostered_in_selected_league,sleeper_id,4/4,95,95,95,95,0,balanced_window,horizon:bad\n"
                "league-b,2026,p-other-league,Other League WR,WR,not_rostered_in_selected_league,sleeper_id,4/4,95,95,95,95,0,balanced_window,horizon:wrong-league\n"
                "league-a,2026,p-unresolved,Unresolved WR,WR,not_rostered_in_selected_league,unresolved,4/4,95,95,95,95,0,balanced_window,horizon:unresolved\n"
                "league-a,2026,p-not-available,Not Available WR,WR,rostered_in_selected_league,sleeper_id,4/4,95,95,95,95,0,balanced_window,horizon:status\n",
                encoding="utf-8",
            )
            (processed / "roster_players.csv").write_text(
                "league_id,season,roster_id,player_id,player_name\n"
                "league-a,2026,4,p-rostered,Rostered By Rival\n",
                encoding="utf-8",
            )

            rows = _scope_market_watch(
                ArticleContext(
                    analysis_dir=processed,
                    processed_dir=processed,
                    active_roster_id=2,
                    league_id="league-a",
                    season="2026",
                )
            )

        available = [row for row in rows if row["name"] == "Available Clock WR"]
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0]["availability_scope"], "available_market_research")
        self.assertIn("this-week score=72", available[0]["text"])
        self.assertIn("not a waiver-eligibility or claim receipt", available[0]["text"])
        self.assertNotIn("Rostered By Rival", {row["name"] for row in rows})
        self.assertNotIn("Other League WR", {row["name"] for row in rows})
        self.assertNotIn("Unresolved WR", {row["name"] for row in rows})
        self.assertNotIn("Not Available WR", {row["name"] for row in rows})

    def test_team_report_writer_packet_fails_closed_at_league_boundary(self) -> None:
        """AGENTS.md identity rule: roster matches cannot substitute for league identity."""
        with tempfile.TemporaryDirectory() as temporary:
            processed = Path(temporary) / "processed"
            analysis = Path(temporary) / "analysis"
            processed.mkdir()
            analysis.mkdir()

            def write_rows(filename: str, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
                with (processed / filename).open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)

            write_rows(
                "player_dossiers.csv",
                ["roster_id", "player_id", "player_name", "market_value"],
                [{"roster_id": "2", "player_id": "p1", "player_name": "Current Player", "market_value": "40"}],
            )
            current_float_id = 1.313490073630548e18
            other_float_id = 1.1802096767965307e18
            write_rows(
                "league_news_impact.csv",
                ["event_id", "player_id", "player_name", "league_id", "season", "impact_type", "evidence", "confidence", "risk"],
                [
                    {"event_id": "current-news", "player_id": "p1", "player_name": "Current Player", "league_id": current_float_id, "season": "2026", "impact_type": "role", "evidence": "Current league news", "confidence": "high", "risk": "low"},
                    {"event_id": "other-news", "player_id": "p1", "player_name": "Current Player", "league_id": other_float_id, "season": "2026", "impact_type": "role", "evidence": "Other league news", "confidence": "high", "risk": "low"},
                ],
            )
            write_rows(
                "matchups.csv",
                ["season", "league_id", "week", "matchup_id", "roster_id", "opponent_team_name", "result", "points_for", "points_against", "margin"],
                [
                    {"season": "2026", "league_id": current_float_id, "week": "3", "matchup_id": "match-current", "roster_id": "2", "opponent_team_name": "Current Opponent", "result": "win", "points_for": "120", "points_against": "100", "margin": "20"},
                    {"season": "2026", "league_id": other_float_id, "week": "3", "matchup_id": "match-other", "roster_id": "2", "opponent_team_name": "Other Opponent", "result": "loss", "points_for": "90", "points_against": "100", "margin": "-10"},
                ],
            )
            write_rows(
                "trades.csv",
                ["season", "league_id", "week", "transaction_id", "team_a_roster_id", "team_a_name", "team_a_players_received", "team_a_picks_received", "team_a_faab_received", "team_b_roster_id", "team_b_name", "team_b_players_received", "team_b_picks_received", "team_b_faab_received"],
                [
                    {"season": "2026", "league_id": current_float_id, "week": "4", "transaction_id": "trade-current", "team_a_roster_id": "2", "team_a_name": "Current Team", "team_a_players_received": "Current Asset", "team_a_picks_received": "", "team_a_faab_received": "", "team_b_roster_id": "4", "team_b_name": "Current Counterparty", "team_b_players_received": "", "team_b_picks_received": "", "team_b_faab_received": ""},
                    {"season": "2026", "league_id": other_float_id, "week": "4", "transaction_id": "trade-other", "team_a_roster_id": "2", "team_a_name": "Other Team", "team_a_players_received": "Other Asset", "team_a_picks_received": "", "team_a_faab_received": "", "team_b_roster_id": "4", "team_b_name": "Other Counterparty", "team_b_players_received": "", "team_b_picks_received": "", "team_b_faab_received": ""},
                ],
            )
            write_rows(
                "waivers.csv",
                ["season", "league_id", "week", "transaction_id", "roster_id", "player_added", "player_dropped", "waiver_bid"],
                [
                    {"season": "2026", "league_id": current_float_id, "week": "5", "transaction_id": "waiver-current", "roster_id": "2", "player_added": "Current Waiver", "player_dropped": "", "waiver_bid": "7"},
                    {"season": "2026", "league_id": other_float_id, "week": "5", "transaction_id": "waiver-other", "roster_id": "2", "player_added": "Other Waiver", "player_dropped": "", "waiver_bid": "7"},
                ],
            )

            rows = _scope_team_report(
                ArticleContext(
                    analysis_dir=analysis,
                    active_roster_id=2,
                    processed_dir=processed,
                    league_id="1313490073630547968",
                    season="2026",
                )
            )

        self.assertEqual([row["entity_id"] for row in rows if row["entity_type"] == "news"], ["current-news"])
        self.assertEqual([row["entity_id"] for row in rows if row["entity_type"] == "matchup"], ["2026:3:match-current"])
        self.assertEqual(
            [row["entity_id"] for row in rows if row["entity_type"] == "transaction"],
            ["waiver-current", "trade-current"],
        )

    def test_trade_desk_article_scope_preserves_offer_candidate_evidence(self) -> None:
        """The Trade Desk entry path must carry the structured shortlist to writers."""
        with tempfile.TemporaryDirectory() as temporary:
            analysis = Path(temporary)
            (analysis / "trade_theses.json").write_text(
                json.dumps(
                    {"items": [
                        {
                            "target_manager_roster_id": 4,
                            "target_manager_name": "Moose Caboose",
                            "horizon_market_disagreement_window": "dynasty",
                            "horizon_market_disagreement_delta": 18.5,
                            "horizon_market_disagreement_read": "clock_leads_market",
                            "offer_candidates": [
                                {
                                    "asset_name": "My Wideout",
                                    "position_group": "PASS_CATCHER",
                                    "manager_preference_evidence_count": 5,
                                }
                            ],
                        }
                    ]}
                ),
                encoding="utf-8",
            )
            rows = _scope_trade_desk(ArticleContext(analysis_dir=analysis, active_roster_id=2))

        self.assertEqual(rows[0]["offer_candidates"][0]["asset_name"], "My Wideout")
        self.assertEqual(rows[0]["offer_candidates"][0]["manager_preference_evidence_count"], 5)
        self.assertEqual(rows[0]["horizon_market_disagreement_window"], "dynasty")
        self.assertEqual(rows[0]["horizon_market_disagreement_delta"], 18.5)


if __name__ == "__main__":
    unittest.main()
