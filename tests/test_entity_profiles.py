from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.context import FantasyContext
from src.entity_profiles import build_profile_packet, import_profile_output
from src.league_paths import LeaguePaths


class CanonicalEntityProfileTests(unittest.TestCase):
    """Design source: docs/single_brain_decision_product_epic.md Slice 3."""

    def _paths(self, root: Path) -> LeaguePaths:
        operator_root = root / "operator"
        return LeaguePaths(
            league_id="league-1",
            root=root,
            raw_dir=root / "raw",
            raw_external_dir=root / "raw_external",
            processed_dir=root / "processed",
            cache_dir=root / "cache",
            reports_dir=root / "reports",
            site_dir=root / "site",
            analysis_dir=root / "analysis",
            operator_inbox_dir=operator_root / "inbox",
            operator_outbox_dir=operator_root / "outbox",
            operator_status_dir=operator_root / "status",
            user_id="9",
        )

    def _context(self) -> FantasyContext:
        return FantasyContext(
            user_id="9",
            league_id="league-1",
            season="2026",
            roster_id=4,
            league_name="Profile League",
            team_name="Fourth and Long",
            identity_status="verified_roster_match",
        )

    def _write_csv(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _seed(self, paths: LeaguePaths) -> None:
        paths.ensure()
        self._write_csv(
            paths.processed_dir / "roster_players.csv",
            [{
                "league_id": "league-1",
                "season": "2026",
                "roster_id": 4,
                "player_id": "101",
                "player_name": "Roster Player",
                "position": "WR",
                "availability_scope": "current_season_snapshot",
                "source_trace": "sleeper_rosters;sleeper_players",
            }],
        )
        self._write_csv(
            paths.processed_dir / "available_player_horizon_scores.csv",
            [{
                "league_id": "league-1",
                "season": "2026",
                "player_id": "202",
                "player_name": "Waiver Player",
                "market_rank": 1,
                "market_value": 44,
                "availability_status": "absent_from_rosters",
                "source_trace": "sleeper_rosters;market_consensus_values",
            }],
        )
        self._write_csv(
            paths.processed_dir / "action_recommendations.csv",
            [{
                "league_id": "league-1",
                "season": "2026",
                "roster_id": 4,
                "player_id": "101",
                "player_name": "Roster Player",
                "action_rank": 1,
                "action_score": 81,
                "action_label": "hold",
                "why": "The current fit remains strong.",
                "risk": "Role volatility.",
                "confidence": "medium",
                "source_trace": "player_signal_scores;team_fit_scores",
            }],
        )
        self._write_csv(
            paths.processed_dir / "manager_behavior_signals.csv",
            [{
                "league_id": "league-1",
                "season": "2026",
                "roster_id": 8,
                "team_name": "Counterparty",
                "plain_language_label": "active trader",
                "source_trace": "manager_event_log",
            }],
        )
        (paths.analysis_dir / "player_dossiers.json").write_text(
            json.dumps({
                "items": [
                    {"player_id": "101", "player_name": "Roster Player", "analysis_text": "Strong fit.", "source_trace": "player_dossiers"},
                    {"player_id": "202", "player_name": "Waiver Player", "analysis_text": "Available-market candidate.", "source_trace": "player_dossiers"},
                ]
            }),
            encoding="utf-8",
        )
        (paths.analysis_dir / "manager_dossiers.json").write_text(
            json.dumps({"items": [{"roster_id": 8, "team_name": "Counterparty", "analysis_text": "Observed activity only.", "source_trace": "manager_dossiers"}]}),
            encoding="utf-8",
        )
        (paths.analysis_dir / "trade_theses.json").write_text(
            json.dumps({"items": [{"target_manager_roster_id": 8, "target_manager_name": "Counterparty", "analysis_text": "Ask about timeline fit.", "source_trace": "trade_theses"}]}),
            encoding="utf-8",
        )

    def _output(self, entity_type: str, evidence_id: str) -> dict:
        availability = "Current Sleeper snapshot; confirm claim eligibility before acting." if entity_type == "player" else "Not applicable to a manager profile."
        return {
            "headline": "A current, league-specific read",
            "summary": "This profile turns the entity's deterministic evidence into one bounded decision lens.",
            "current_state": "The latest packet supports attention without certainty.",
            "role_or_behavior": "Observed role or behavior is recorded in the evidence receipt.",
            "market_or_trade_lane": "Use the recorded market or conversation lane; missing price evidence stays missing.",
            "availability": availability,
            "team_fit": "The fit is specific to roster 4 and its recorded strategy context.",
            "recommended_action": "Review the evidence and decide whether to investigate now.",
            "counter_evidence": "The sample and freshness limits can change the read.",
            "risk": "Treat interpretation as uncertain and read-only.",
            "confidence": "medium",
            "reconsideration_trigger": "Reconsider when role, market, availability, or roster facts change.",
            "narrative_markdown": "## Current read\nUse the current evidence, not a generic player take.\n\n## Decision\nInvestigate before acting.",
            "cited_evidence_ids": [evidence_id],
        }

    def test_profile_cohort_import_reuse_and_isolated_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._seed(paths)
            packet = build_profile_packet(paths, self._context())

            self.assertEqual(packet["state"], "ready")
            self.assertEqual(set(packet["entity_keys"]), {"player:101", "player:202", "manager:8"})
            outputs = {
                item["entity_key"]: {
                    "evidence_fingerprint": item["evidence_fingerprint"],
                    "output": self._output(item["entity_type"], item["evidence"][0]["evidence_id"]),
                }
                for item in packet["profiles"]
            }
            with patch("app.db.record_content_artifact") as record_artifact:
                imported = import_profile_output(
                    {
                        "packet_fingerprint": packet["packet_fingerprint"],
                        "model": "gpt-5.6-luna",
                        "profiles": outputs,
                    },
                    paths,
                    self._context(),
                )

            self.assertEqual(imported["state"], "complete")
            self.assertEqual(record_artifact.call_count, 3)
            index = json.loads((paths.analysis_dir / "canonical_entity_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["items"]), 3)
            self.assertTrue(all(item["writer_mode"] == "codex_task" for item in index["items"]))

            unchanged = build_profile_packet(paths, self._context())
            self.assertEqual(unchanged["state"], "unchanged")
            self.assertEqual(unchanged["entity_keys"], [])
            self.assertEqual(set(unchanged["reused_entity_keys"]), {"player:101", "player:202", "manager:8"})

            self._write_csv(
                paths.processed_dir / "action_recommendations.csv",
                [{
                    "league_id": "league-1",
                    "season": "2026",
                    "roster_id": 4,
                    "player_id": "101",
                    "player_name": "Roster Player",
                    "action_rank": 1,
                    "action_score": 93,
                    "action_label": "hold",
                    "why": "The fit strengthened.",
                    "risk": "Role volatility.",
                    "confidence": "high",
                    "source_trace": "player_signal_scores;team_fit_scores",
                }],
            )
            changed = build_profile_packet(paths, self._context())
            self.assertEqual(changed["entity_keys"], ["player:101"])
            self.assertEqual(set(changed["reused_entity_keys"]), {"player:202", "manager:8"})

            selected = build_profile_packet(paths, self._context(), {"player:101"})
            selected_item = selected["profiles"][0]
            with patch("app.db.record_content_artifact"):
                selected_import = import_profile_output(
                    {
                        "packet_fingerprint": selected["packet_fingerprint"],
                        "profiles": {
                            "player:101": {
                                "evidence_fingerprint": selected_item["evidence_fingerprint"],
                                "output": self._output("player", selected_item["evidence"][0]["evidence_id"]),
                            }
                        },
                    },
                    paths,
                    self._context(),
                )
            self.assertEqual(selected_import["state"], "complete")
            selected_index = json.loads((paths.analysis_dir / "canonical_entity_profiles.json").read_text(encoding="utf-8"))
            self.assertTrue(all(item["status"] == "current" for item in selected_index["items"]))

    def test_profile_import_rejects_invented_evidence_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._seed(paths)
            packet = build_profile_packet(paths, self._context(), {"player:202"})
            item = packet["profiles"][0]
            output = self._output("player", "invented:evidence")
            with patch("app.db.record_content_artifact") as record_artifact:
                receipt = import_profile_output(
                    {
                        "packet_fingerprint": packet["packet_fingerprint"],
                        "profiles": {
                            "player:202": {
                                "evidence_fingerprint": item["evidence_fingerprint"],
                                "output": output,
                            }
                        },
                    },
                    paths,
                    self._context(),
                )

            self.assertEqual(receipt["state"], "rejected")
            self.assertEqual(receipt["written_entity_keys"], [])
            record_artifact.assert_not_called()
            self.assertFalse((paths.analysis_dir / "canonical_entity_profiles.json").exists())

    def test_available_profile_bench_covers_more_than_the_current_front_five(self) -> None:
        """Design source: docs/single_brain_decision_product_epic.md waiver entry-path requirement."""

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._seed(paths)
            self._write_csv(
                paths.processed_dir / "available_player_horizon_scores.csv",
                [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "player_id": str(player_id),
                        "player_name": f"Available Player {player_id}",
                        "market_rank": rank,
                        "market_value": 50 - rank,
                        "availability_status": "absent_from_rosters",
                        "source_trace": "sleeper_rosters;market_consensus_values",
                    }
                    for rank, player_id in enumerate(range(202, 208), start=1)
                ],
            )

            packet = build_profile_packet(paths, self._context())

            self.assertIn("player:207", packet["cohort_entity_keys"])

    def test_reader_waiver_market_resolves_unique_sleeper_identity_for_profiles(self) -> None:
        """Design source: AGENTS.md entry-path and exact-identity rules."""

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._seed(paths)
            self._write_csv(
                paths.processed_dir / "players.csv",
                [{"player_id": "4098", "player_name": "Kareem Hunt", "position": "RB", "source_trace": "sleeper_players"}],
            )
            self._write_csv(
                paths.processed_dir / "player_market_values.csv",
                [{
                    "player_id": "",
                    "player_name": "Kareem Hunt",
                    "position": "RB",
                    "market_rank": 441,
                    "market_value": 0.07,
                    "source_trace": "market_consensus_values",
                }],
            )
            self._write_csv(
                paths.processed_dir / "available_player_horizon_scores.csv",
                [{
                    "league_id": "league-1",
                    "season": "2026",
                    "player_id": "4098",
                    "player_name": "Kareem Hunt",
                    "availability_status": "not_rostered_in_selected_league",
                    "source_trace": "sleeper_rosters;market_consensus_values",
                }],
            )

            packet = build_profile_packet(paths, self._context(), {"player:4098"})

            self.assertEqual(packet["entity_keys"], ["player:4098"])
            evidence_tables = {row["source_table"] for row in packet["profiles"][0]["evidence"]}
            self.assertIn("available_player_horizon_scores", evidence_tables)


if __name__ == "__main__":
    unittest.main()
