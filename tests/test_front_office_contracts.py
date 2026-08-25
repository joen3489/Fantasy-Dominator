from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from src import articles, operator
from src.llm import call_structured_tool, configured_llm
from src.personas import persona_prompt_block, reporter_lineup


class FrontOfficeContractsTests(unittest.TestCase):
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
        self.assertEqual(config.reasoning_effort, "medium")
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

    def test_reporter_lineup_has_distinct_default_lenses(self) -> None:
        lineup = reporter_lineup({})

        self.assertEqual(
            [item["persona_id"] for item in lineup],
            ["topline_tony", "waiver_wire_waverly", "trade_desk_talia", "dossier_dana", "look_ahead_lonnie"],
        )
        self.assertIn("Trade Desk Talia", persona_prompt_block({}, "trade_desk"))
        self.assertIn("Waiver Wire Waverly", persona_prompt_block({}, "market_watch"))


if __name__ == "__main__":
    unittest.main()
