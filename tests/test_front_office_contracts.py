from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import articles, operator
from src.llm import call_structured_tool, configured_llm
from src.personas import persona_prompt_block, reporter_lineup
from src.editorial import review_publication_article


class FrontOfficeContractsTests(unittest.TestCase):
    def test_writer_progress_receipt_names_the_active_desk(self) -> None:
        """Design source: AGENTS.md; a long newsroom run must expose truthful progress before publication."""
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "operator" / "status" / "operator_status.json"
            article = articles.ARTICLES[0]
            with patch.object(operator, "STATUS_PATH", status_path):
                operator._write_writer_progress(
                    {"team_report": {"state": "complete", "message": "Team Report written."}},
                    current_article=article,
                    completed_count=1,
                    total_count=6,
                    model="gpt-5.6-luna",
                    reasoning_effort="max",
                    editor_mode="deterministic",
                    writer_preferences={"article_reporters": {article.key: "quant"}},
                )
                receipt = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertEqual(receipt["state"], "running")
            self.assertEqual(receipt["completed_count"], 1)
            self.assertEqual(receipt["total_count"], 6)
            self.assertEqual(receipt["current_article"], article.key)
            self.assertEqual(receipt["model"], "gpt-5.6-luna")
            self.assertEqual(receipt["reasoning_effort"], "max")
            self.assertIn("team_report", receipt["articles"])
            self.assertEqual(receipt["current_reporter"]["persona_id"], "quant")

    def test_persisted_running_status_fails_closed_after_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_dir = Path(tmp) / "operator" / "status"
            status_path = status_dir / "operator_status.json"
            status_dir.mkdir(parents=True)
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "job": "generate-insights",
                        "message": "generate-insights started.",
                        "updated_at": "2026-08-26T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(operator, "STATUS_PATH", status_path), patch.object(
                operator, "OPERATOR_STATUS_DIR", status_dir
            ), patch.object(operator, "_ACTIVE_JOB", False):
                recovered = operator.status()

            self.assertEqual(recovered["state"], "failed")
            self.assertTrue(recovered["recovered_from_restart"])
            self.assertIn("interrupted", recovered["message"])
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "failed")

    def test_evidence_packet_labels_source_quality_and_interpretation_boundary(self) -> None:
        """Encodes docs/front_office_realization_epic.md Workstream 2 and AGENTS.md evidence rules."""
        packet = articles._evidence(
            "player",
            "p1",
            1,
            "Player One",
            "Usage rose while production lagged.",
            source_trace="nflverse:usage.csv",
            checked_at="2026-08-25T12:00:00+00:00",
            confidence="medium",
        )

        self.assertEqual(packet["source_ids"], ["nflverse:usage.csv"])
        self.assertEqual(packet["source_count"], 1)
        self.assertEqual(packet["source_quality"], "single_source")
        self.assertIn("Do not infer motive", packet["permitted_interpretation"][1])
        self.assertEqual(packet["source_receipt"]["freshness"], "2026-08-25T12:00:00+00:00")
        self.assertEqual(packet["player_name"], "Player One")

    def test_article_boundary_review_sees_scope_generated_player_packets(self) -> None:
        """Design source: AGENTS.md; the writer seam must catch unsupported current-role claims."""
        packet = articles._evidence(
            "player",
            "p1",
            1,
            "Conditional Veteran",
            "Historical production is useful context only.",
            source_trace="nflverse:usage.csv",
            current_availability_status="no_current_nfl_team",
            availability_note="No current NFL team; historical baseline only",
        )

        result = operator.validate_article_output(
            {
                "narrative_markdown": "## Read\nConditional Veteran is projected for 16 PPG this season.",
                "cited_evidence_ids": [packet["evidence_id"]],
            },
            {packet["evidence_id"]},
            ("## Read",),
            [packet],
        )

        self.assertFalse(result["valid"])
        self.assertIn("no current nfl team", " ".join(result["errors"]).lower())

    def test_article_validation_returns_structured_contract_without_breaking_legacy_fallbacks(self) -> None:
        """Encodes the epic's structured article contract; old deterministic mocks remain readable."""
        result = operator.validate_article_output(
            {
                "narrative_markdown": "## Cornerstones\nA grounded read.",
                "cited_evidence_ids": ["player:p1:1"],
                "headline": "The role signal is real",
                "thesis": "The market has not caught up.",
                "action": "Price it, then decide.",
                "confidence": "medium",
            },
            {"player:p1:1"},
            ("## Cornerstones",),
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["structured"]["headline"], "The role signal is real")
        self.assertEqual(result["structured"]["confidence"], "medium")
        self.assertIn("counter_evidence", result["structured"])
    def test_default_writer_is_luna(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = configured_llm()

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model, "gpt-5.6-luna")
        self.assertEqual(config.reasoning_effort, "max")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")

    def test_luna_configuration_is_explicit_and_uses_openai_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FRONT_OFFICE_LLM_PROVIDER": "openai",
                "FRONT_OFFICE_LLM_MODEL": "gpt-5.6-luna",
                "FRONT_OFFICE_LLM_REASONING_EFFORT": "max",
            },
            clear=True,
        ):
            config = configured_llm()

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model, "gpt-5.6-luna")
        self.assertEqual(config.reasoning_effort, "max")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")

    def test_openai_responses_function_call_is_normalized(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "output": [
                {
                    "type": "function_call",
                    "name": "emit_article",
                    "arguments": json.dumps({"narrative_markdown": "ok", "cited_evidence_ids": ["p:1"]}),
                }
            ]
        }
        response.raise_for_status.return_value = None
        post = MagicMock(return_value=response)
        with patch.dict(
            os.environ,
            {
                "FRONT_OFFICE_LLM_PROVIDER": "openai",
                "FRONT_OFFICE_LLM_REASONING_EFFORT": "high",
            },
            clear=True,
        ):
            result = call_structured_tool(
                system_prompt="system",
                evidence=[{"evidence_id": "p:1"}],
                editorial_context=[{"kind": "peer_edition", "reporter": "Other desk", "excerpt": "A different read."}],
                api_key="secret",
                model="gpt-5.6-luna",
                tool={
                    "name": "emit_article",
                    "description": "Write an article",
                    "input_schema": {"type": "object", "properties": {}},
                },
                request_post=post,
            )

        self.assertEqual(result["narrative_markdown"], "ok")
        request = post.call_args.kwargs
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(request["json"]["reasoning"], {"effort": "high"})
        self.assertEqual(request["json"]["tool_choice"], {"type": "function", "name": "emit_article"})
        self.assertFalse(request["json"]["store"])
        payload = json.loads(request["json"]["input"][1]["content"])
        self.assertEqual(payload["editorial_context"][0]["kind"], "peer_edition")

    def test_transient_openai_rate_limit_is_retried_with_a_bound(self) -> None:
        rate_limited = MagicMock(status_code=429, headers={})
        final = MagicMock(status_code=200)
        final.json.return_value = {
            "output": [
                {
                    "type": "function_call",
                    "name": "emit_article",
                    "arguments": json.dumps({"narrative_markdown": "retried", "cited_evidence_ids": ["p:1"]}),
                }
            ]
        }
        post = MagicMock(side_effect=[rate_limited, final])
        with patch("src.llm.time.sleep") as sleep:
            result = call_structured_tool(
                system_prompt="system",
                evidence=[{"evidence_id": "p:1"}],
                api_key="secret",
                model="gpt-5.6-luna",
                tool={"name": "emit_article", "input_schema": {"type": "object", "properties": {}}},
                request_post=post,
            )

        self.assertEqual(result["narrative_markdown"], "retried")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once()

    def test_desk_editor_holds_an_article_without_a_source_receipt(self) -> None:
        """Design source: AGENTS.md; publication must fail closed at the writer-to-reader seam."""

        review = review_publication_article(
            "market_watch",
            "## Buy-Low Targets\nA read.",
            {
                "structured": {
                    "headline": "A read",
                    "thesis": "The price is worth checking.",
                    "what_changed": "The packet changed.",
                    "action": "Open the evidence.",
                    "evidence_ids": ["player:1:1"],
                    "source_ids": [],
                }
            },
            "automatic_llm",
        )

        self.assertEqual(review["status"], "held")
        self.assertIn("no source receipt", " ".join(review["errors"]))

    def test_persisted_llm_editor_decision_is_visible_but_cannot_bypass_deterministic_gate(self) -> None:
        """Design source: AGENTS.md; editorial approval is subordinate to validated evidence."""
        receipt = {
            "structured": {
                "headline": "A supported read",
                "thesis": "The packet supports a measured action.",
                "what_changed": "The evidence packet changed.",
                "action": "Open the receipt before acting.",
                "evidence_ids": ["player:1:1"],
                "source_ids": ["source:values"],
            },
            "editorial_review": {
                "mode": "llm",
                "model": "gpt-5.6-luna",
                "status": "approved",
                "decision": "modify",
                "editor_notes": "Added a supported limitation.",
                "changes": ["Clarified the evidence boundary."],
            },
        }
        approved = review_publication_article("market_watch", "## Buy-Low Targets\nA read.", receipt, "automatic_llm")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["decision"], "modify")
        self.assertEqual(approved["mode"], "llm")

        receipt["structured"]["source_ids"] = []
        held = review_publication_article("market_watch", "## Buy-Low Targets\nA read.", receipt, "automatic_llm")
        self.assertEqual(held["status"], "held")
        self.assertIn("no source receipt", " ".join(held["errors"]))

    def test_editor_candidate_must_be_complete_and_cited_before_modify_can_publish(self) -> None:
        """Design source: docs/front_office_realization_epic.md; repair is a full replacement under the same evidence contract."""
        article = articles.ARTICLES[0]
        evidence = [{"evidence_id": "player:p1:1", "source_ids": ["source:stats"]}]
        writer = {
            "headline": "Writer read",
            "thesis": "The writer sees a supported signal.",
            "what_changed": "The packet changed.",
            "action": "Compare the options.",
            "confidence": "medium",
            "narrative_markdown": "## Cornerstones\nWriter read.\n\n## Shop Candidates\nNames.",
            "cited_evidence_ids": ["player:p1:1"],
        }
        editor = {
            **writer,
            "decision": "modify",
            "editor_notes": "Tightened the claim.",
            "changes": ["Added a limitation."],
            "narrative_markdown": "## Cornerstones\nEditor read with a limitation.\n\n## Shop Candidates\nNames.",
        }
        writer_validation = operator.validate_article_output(writer, {"player:p1:1"}, article.headers, evidence)
        candidate, review = operator._editor_review_result(
            article,
            writer,
            writer_validation,
            editor,
            evidence,
            "gpt-5.6-luna",
        )
        self.assertEqual(review["status"], "approved")
        self.assertEqual(review["decision"], "modify")
        self.assertIn("Editor read", candidate["narrative_markdown"])

        invalid_editor = {**editor, "cited_evidence_ids": ["player:missing:9"]}
        _, held_review = operator._editor_review_result(
            article,
            writer,
            writer_validation,
            invalid_editor,
            evidence,
            "gpt-5.6-luna",
        )
        self.assertEqual(held_review["status"], "held")
        self.assertEqual(held_review["decision"], "hold")

    def test_reporter_lineup_has_distinct_default_lenses(self) -> None:
        lineup = reporter_lineup({})

        self.assertEqual(
            [item["persona_id"] for item in lineup],
            ["topline_tony", "waiver_wire_waverly", "market_clock_morgan", "trade_desk_talia", "dossier_dana", "look_ahead_lonnie"],
        )
        self.assertIn("Trade Desk Talia", persona_prompt_block({}, "trade_desk"))
        self.assertIn("Waiver Wire Waverly", persona_prompt_block({}, "market_watch"))
        self.assertIn("Market Clock Morgan", persona_prompt_block({}, "horizon_watch"))


if __name__ == "__main__":
    unittest.main()
