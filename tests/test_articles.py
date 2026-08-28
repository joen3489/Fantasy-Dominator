import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.availability import baseline_ppg_label, baseline_ppg_text
from src.articles import ArticleContext, _scope_daily_brief, _scope_horizon_watch, _scope_manager_intel, _scope_team_report, build_evidence_manifest


class ArticleScopeTests(unittest.TestCase):
    def test_evidence_manifest_keeps_boundary_fields_without_prompt_prose_or_paths(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; publication receipts must prove scope without copying packets."""
        manifest = build_evidence_manifest([
            {
                "evidence_id": "player:hill:1",
                "entity_type": "player",
                "entity_id": "hill",
                "name": "Tyreek Hill",
                "text": "Tyreek Hill is unavailable with no current NFL team.",
                "claim_candidates": ["do not publish this as current projection"],
                "supporting_rows": [{"secret": "raw row"}],
                "current_availability_status": "no_current_nfl_team",
                "availability_scope": "current Sleeper snapshot",
                "availability_note": "No current NFL team; historical baseline only",
                "source_ids": ["sleeper:players"],
                "source_trace": "sleeper:players",
                "reality_check": {"status": "warning", "detail": "verify before acting"},
                "calculation": "C:\\Users\\joeno\\private-prompt.txt",
            }
        ])
        self.assertEqual(len(manifest), 1)
        item = manifest[0]
        self.assertEqual(item["evidence_id"], "player:hill:1")
        self.assertEqual(item["player_name"], "Tyreek Hill")
        self.assertEqual(item["current_availability_status"], "no_current_nfl_team")
        self.assertEqual(item["calculation"], "[redacted-path]")
        self.assertNotIn("text", item)
        self.assertNotIn("claim_candidates", item)
        self.assertNotIn("supporting_rows", item)

    def test_shared_ppg_label_uses_availability_note_when_status_is_missing(self) -> None:
        """Design source: docs/data_contract.md; a status note is current-only evidence."""
        self.assertEqual(
            baseline_ppg_label({"availability_note": "Questionable (knee)"}),
            "conditional baseline PPG if active",
        )
        self.assertEqual(
            baseline_ppg_label({"availability_note": "No current Sleeper injury flag"}),
            "season baseline PPG",
        )
        self.assertEqual(
            baseline_ppg_text({"injury_status": "Active"}, "15"),
            "season baseline 15 PPG",
        )
        self.assertEqual(
            baseline_ppg_label({"availability_note": "Available without issue"}),
            "season baseline PPG",
        )

    def test_team_report_packet_distinguishes_limiting_and_active_statuses(self) -> None:
        """Design source: AGENTS.md; writer packets must preserve deterministic availability facts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir()
            self._write_csv(
                processed / "player_dossiers.csv",
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": "2",
                        "player_id": "p1",
                        "player_name": "Questionable Player",
                        "position": "WR",
                        "market_value": "20",
                        "projected_ppg": "16",
                        "availability_note": "Questionable (knee)",
                    },
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": "2",
                        "player_id": "p2",
                        "player_name": "Active Player",
                        "position": "WR",
                        "market_value": "18",
                        "projected_ppg": "15",
                        "availability_note": "Active",
                    },
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": "2",
                        "player_id": "p3",
                        "player_name": "Conditional Veteran",
                        "position": "WR",
                        "market_value": "22",
                        "projected_ppg": "16",
                        "availability_note": "No current NFL team; historical baseline only",
                    },
                ],
            )
            self._write_csv(
                processed / "player_horizon_market_scores.csv",
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": "2",
                        "player_id": "p1",
                        "injury_status": "Questionable",
                        "next_game_market_score": "40",
                        "rest_of_season_market_score": "70",
                    },
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": "2",
                        "player_id": "p2",
                        "injury_status": "Active",
                        "next_game_market_score": "55",
                        "rest_of_season_market_score": "65",
                    },
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "roster_id": "2",
                        "player_id": "p3",
                        "current_availability_status": "no_current_nfl_team",
                        "availability_scope": "current_sleeper_snapshot",
                        "availability_note": "No current NFL team; historical baseline only",
                        "dynasty_market_score": "80",
                    },
                ],
            )

            rows = _scope_team_report(
                ArticleContext(
                    analysis_dir=root / "analysis",
                    active_roster_id=2,
                    processed_dir=processed,
                    league_id="league-1",
                    season="2026",
                )
            )

        text_by_name = {row["name"]: row["text"] for row in rows if row.get("entity_type") == "player"}
        self.assertIn("conditional baseline PPG if active", text_by_name["Questionable Player"])
        self.assertIn("season baseline 15 PPG", text_by_name["Active Player"])
        self.assertNotIn("conditional baseline PPG if active", text_by_name["Active Player"])
        self.assertNotIn("Conditional Veteran", text_by_name)
        self.assertTrue(all(row.get("player_name") == row["name"] for row in rows if row.get("entity_type") == "player"))

    def test_team_report_does_not_fall_back_to_another_roster(self) -> None:
        """Design source: AGENTS.md; a missing exact roster join must stay unavailable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir()
            self._write_csv(
                processed / "roster_players.csv",
                [
                    {"league_id": "league-1", "season": "2026", "roster_id": "2", "player_id": "right", "player_name": "Right Team Player"},
                    {"league_id": "league-1", "season": "2026", "roster_id": "8", "player_id": "wrong", "player_name": "Wrong Team Player"},
                ],
            )
            self._write_csv(
                processed / "player_dossiers.csv",
                [
                    {"roster_id": "8", "player_id": "wrong", "player_name": "Wrong Team Player", "position": "WR", "market_value": "90", "projected_ppg": "20"},
                    {"roster_id": "2", "player_id": "right", "player_name": "Right Team Player", "position": "WR", "market_value": "10", "projected_ppg": "8"},
                ],
            )

            rows = _scope_team_report(
                ArticleContext(
                    analysis_dir=root / "analysis",
                    active_roster_id=2,
                    processed_dir=processed,
                    league_id="league-1",
                    season="2026",
                )
            )

        player_names = [row["name"] for row in rows if row.get("entity_type") == "player"]
        self.assertEqual(player_names, ["Right Team Player"])
        self.assertNotIn("Wrong Team Player", player_names)

    def test_team_report_includes_only_played_player_matchup_receipts(self) -> None:
        """Design source: durable_newsroom_epic.md; Topline Tony must attribute points to exact receipts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir()
            self._write_csv(
                processed / "player_dossiers.csv",
                [{
                    "league_id": "league-1", "season": "2026", "roster_id": "2", "player_id": "p1",
                    "player_name": "Anchor QB", "position": "QB", "market_value": "70",
                    "projected_ppg": "20", "availability_note": "Active",
                }],
            )
            self._write_csv(
                processed / "matchup_player_points.csv",
                [
                    {
                        "league_id": "league-1", "season": "2026", "week": "1", "matchup_id": "m1",
                        "roster_id": "2", "player_id": "p1", "player_name": "Anchor QB",
                        "opponent_team_name": "Rival Team", "is_starter": "True", "player_points": "24.5",
                        "matchup_status": "played", "source_trace": "source-matchup",
                    },
                    {
                        "league_id": "league-1", "season": "2026", "week": "2", "matchup_id": "m2",
                        "roster_id": "2", "player_id": "p1", "player_name": "Anchor QB",
                        "opponent_team_name": "Future Team", "is_starter": "True", "player_points": "0",
                        "matchup_status": "unplayed", "source_trace": "source-matchup",
                    },
                ],
            )

            rows = _scope_team_report(
                ArticleContext(
                    analysis_dir=root / "analysis",
                    active_roster_id=2,
                    processed_dir=processed,
                    league_id="league-1",
                    season="2026",
                )
            )

        receipts = [row for row in rows if row.get("entity_type") == "matchup_player"]
        self.assertEqual(len(receipts), 1)
        self.assertIn("scored 24.5 points as a starter", receipts[0]["text"])
        self.assertEqual(receipts[0]["player_id"], "p1")

    def test_team_report_includes_reconciled_lineup_receipt_for_latest_matchup(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; lineup attribution must reconcile to the aggregate receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir()
            self._write_csv(
                processed / "player_dossiers.csv",
                [{
                    "league_id": "league-1", "season": "2026", "roster_id": "2", "player_id": "p1",
                    "player_name": "Anchor QB", "position": "QB", "market_value": "70", "projected_ppg": "20",
                }],
            )
            self._write_csv(
                processed / "matchups.csv",
                [{
                    "league_id": "league-1", "season": "2026", "week": "3", "matchup_id": "m3",
                    "roster_id": "2", "opponent_roster_id": "8", "opponent_team_name": "Rival Team",
                    "points_for": "54.5", "points_against": "48.0", "margin": "6.5", "result": "win",
                    "source_trace": "source-matchups",
                }],
            )
            self._write_csv(
                processed / "matchup_player_points.csv",
                [
                    {
                        "league_id": "league-1", "season": "2026", "week": "3", "matchup_id": "m3",
                        "roster_id": "2", "player_id": "p1", "player_name": "Anchor QB", "opponent_team_name": "Rival Team",
                        "is_starter": "True", "player_points": "24.5", "matchup_status": "played", "source_trace": "source-points",
                    },
                    {
                        "league_id": "league-1", "season": "2026", "week": "3", "matchup_id": "m3",
                        "roster_id": "2", "player_id": "p2", "player_name": "Anchor WR", "opponent_team_name": "Rival Team",
                        "is_starter": "True", "player_points": "30.0", "matchup_status": "played", "source_trace": "source-points",
                    },
                ],
            )

            rows = _scope_team_report(
                ArticleContext(
                    analysis_dir=root / "analysis",
                    active_roster_id=2,
                    processed_dir=processed,
                    league_id="league-1",
                    season="2026",
                )
            )

        lineup = [row for row in rows if row.get("entity_type") == "lineup"]
        self.assertEqual(len(lineup), 1)
        self.assertIn("starters supplied 54.50", lineup[0]["text"])
        self.assertIn("reconciles to team total 54.5", lineup[0]["text"])
        self.assertEqual(lineup[0]["starter_points"], 54.5)
        self.assertEqual(lineup[0]["known_player_rows"], 2)

    def test_horizon_packet_includes_changed_exact_scope_movement_receipts(self) -> None:
        """Design source: docs/data_contract.md; writers interpret dated movement receipts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "processed"
            processed.mkdir()
            self._write_csv(
                processed / "player_horizon_market_scores.csv",
                [{
                    "league_id": "league-1", "season": "2026", "roster_id": "2", "player_id": "p1",
                    "player_name": "Moved Receiver", "position": "WR", "horizon_model_version": "horizon_market_v2",
                    "next_game_market_score": "60", "rest_of_season_market_score": "65",
                    "dynasty_market_score": "70", "career_projection_score": "68", "value_lane": "balanced_window",
                }],
            )
            self._write_csv(
                processed / "horizon_market_movements.csv",
                [{
                    "league_id": "league-1", "season": "2026", "player_id": "p1", "player_name": "Moved Receiver",
                    "position": "WR", "horizon_model_version": "horizon_market_v2", "prior_as_of_week": "1",
                    "current_as_of_week": "2", "largest_clock_movement_window": "dynasty",
                    "largest_clock_movement_delta": "12", "largest_clock_movement_magnitude": "12",
                    "movement_status": "changed", "market_value_delta": "-2", "value_lane": "rebuilder_edge",
                    "source_trace": "horizon_snapshot_history.csv; player_horizon_market_scores",
                }],
            )

            rows = _scope_horizon_watch(
                ArticleContext(
                    analysis_dir=root / "analysis",
                    active_roster_id=2,
                    processed_dir=processed,
                    league_id="league-1",
                    season="2026",
                )
            )

        movement = [row for row in rows if row.get("entity_type") == "horizon_movement"]
        self.assertEqual(len(movement), 1)
        self.assertEqual(movement[0]["movement_status"], "changed")
        self.assertIn("exact-scope horizon receipt", movement[0]["text"])
        self.assertIn("week 1", movement[0]["text"])

    def test_manager_writer_packet_bounds_raw_history_but_keeps_dossier_context(self) -> None:
        """Design source: AGENTS.md; deterministic depth stays durable while provider context is bounded."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "analysis"
            analysis.mkdir()
            history = [{"week": index, "transaction": "x" * 1200, "details": {"player": "Player" * 80}} for index in range(30)]
            (analysis / "manager_dossiers.json").write_text(
                json.dumps({
                    "items": [{
                        "roster_id": 9,
                        "team_name": "Historical Team",
                        "analysis_text": "Observed manager pattern.",
                        "season_history": history,
                        "transaction_timeline": history,
                        "trade_fits": history,
                        "source_trace": "manager_dossiers;manager_season_history",
                    }]
                }),
                encoding="utf-8",
            )

            rows = _scope_manager_intel(
                ArticleContext(
                    analysis_dir=analysis,
                    processed_dir=root / "processed",
                    active_roster_id=2,
                    league_id="league-1",
                    season="2026",
                )
            )

        self.assertEqual(len(rows), 1)
        self.assertIn("manager_context", rows[0])
        self.assertLess(len(json.dumps(rows, ensure_ascii=False)), 30_000)
        self.assertLessEqual(len(rows[0]["manager_context"]["season_history"]), 4)

    def test_daily_brief_carries_prior_desk_receipts_into_synthesis_context(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; synthesis may use desk context without losing its source receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            analysis = Path(tmp)
            (analysis / "team_report.md").write_text(
                "---\nsource_receipt_json: {\"source_ids\": [\"player_dossiers\"], \"source_count\": 1}\narticle_payload_json: {\"room_move\": \"opens\", \"room_question\": \"What changed?\"}\n---\n\n## Cornerstones\nA team read.",
                encoding="utf-8",
            )
            rows = _scope_daily_brief(
                ArticleContext(
                    analysis_dir=analysis,
                    active_roster_id=2,
                    section_outputs={"team_report": "## Cornerstones\nA team read."},
                )
            )

        self.assertEqual(rows[0]["source_ids"], ["player_dossiers"])
        self.assertEqual(rows[0]["source_quality"], "editorial_context")
        self.assertEqual(rows[0]["claim_candidates"], [])
        self.assertTrue(rows[0]["editorial_only"])
        self.assertEqual(rows[0]["room_move"], "opens")
        self.assertEqual(rows[0]["room_question"], "What changed?")

    def test_daily_brief_does_not_treat_prior_peer_context_as_current_run_output(self) -> None:
        """Design source: AGENTS.md; stale editorial context cannot masquerade as current evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = _scope_daily_brief(
                ArticleContext(
                    analysis_dir=Path(tmp),
                    active_roster_id=2,
                    prior_section_outputs={"team_report": "Last edition's desk read."},
                )
            )

        self.assertEqual([row for row in rows if row.get("entity_type") == "section"], [])

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        fields = sorted({key for row in rows for key in row})
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
