from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from src.newsroom_evaluation import evaluate_newsroom_fixture, load_artifact_run


FIXTURE = Path(__file__).parent / "fixtures" / "newsroom_eval" / "reference.json"


class NewsroomEvaluationTests(unittest.TestCase):
    def _fixture(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_slice_zero_reference_fixture_scores_information_contracts_without_fabricating_usefulness(self) -> None:
        """Design source: durable_newsroom_epic.md Slice 0; outcomes stay unscored without receipts."""
        report = evaluate_newsroom_fixture(self._fixture())
        run = report["runs"][0]
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["metrics"]["evidence_coverage"]["score"], 1.0)
        self.assertEqual(run["metrics"]["horizon_alignment"]["score"], 1.0)
        self.assertEqual(run["metrics"]["voice_distinctness"]["score"], 1.0)
        self.assertEqual(run["metrics"]["unsupported_certainty"]["score"], 1.0)
        self.assertEqual(run["metrics"]["usefulness"]["status"], "not_scored")

    def test_slice_zero_catches_no_team_projection_regression_and_unknown_citation(self) -> None:
        """Design source: AGENTS.md; Reality Check must hold unsupported current-role claims."""
        fixture = self._fixture()
        article = fixture["runs"][0]["articles"][0]
        article["narrative_markdown"] = (
            "## Cornerstones\nTyreek Hill is projected for 16 points per game.\n\n"
            "## Shop Candidates\nReview the market."
        )
        article["cited_evidence_ids"] = ["player:hill:1", "evidence:not-in-packet"]
        report = evaluate_newsroom_fixture(fixture)
        team_report = report["runs"][0]["articles"][0]
        self.assertEqual(team_report["status"], "fail")
        self.assertTrue(any("no current NFL team" in error for error in team_report["errors"]))
        self.assertTrue(any("not present in its frozen packet" in error for error in team_report["errors"]))

    def test_slice_zero_same_fixture_compares_runs_without_rewriting_evidence(self) -> None:
        """Design source: durable_newsroom_epic.md; model/effort changes use one evidence fixture."""
        fixture = self._fixture()
        candidate = copy.deepcopy(fixture["runs"][0])
        candidate["run_id"] = "candidate-shared-voice"
        candidate["model"] = "gpt-5.6-luna"
        candidate["reasoning_effort"] = "xhigh"
        for article in candidate["articles"]:
            article["reporter_id"] = "topline_tony"
            article["decision_lens"] = "next_game"
        fixture["runs"].append(candidate)
        report = evaluate_newsroom_fixture(fixture)
        self.assertEqual(report["comparison"][0]["baseline_run_id"], "reference-luna-max")
        self.assertLess(report["comparison"][0]["metric_deltas"]["voice_distinctness"], 0)
        self.assertEqual(report["runs"][1]["status"], "fail")

    def test_published_artifact_evaluation_uses_the_persisted_manifest_and_stays_honest_about_outcomes(self) -> None:
        """Design source: durable_newsroom_epic.md; publication proof and recommendation outcomes are separate."""
        run = load_artifact_run(Path(__file__).parents[1] / "data" / "analysis")
        report = evaluate_newsroom_fixture(run)
        evaluated = report["runs"][0]
        self.assertEqual(evaluated["status"], "partial")
        self.assertFalse(evaluated["errors"])
        self.assertEqual(evaluated["metrics"]["evidence_coverage"]["status"], "scored")
        self.assertEqual(evaluated["metrics"]["usefulness"]["status"], "not_scored")
        self.assertEqual(evaluated["metrics"]["voice_distinctness"]["score"], 1.0)

    def test_claim_register_metric_scores_only_positions_inside_the_article_receipt(self) -> None:
        """Design source: durable_newsroom_epic.md; competing reads need measurable evidence boundaries."""
        fixture = self._fixture()
        article = fixture["runs"][0]["articles"][0]
        article["claim_positions"] = [{
            "subject_key": "hill",
            "subject_label": "Tyreek Hill",
            "decision_window": "availability",
            "stance": "conditional",
            "summary": "The current availability boundary makes the historical baseline conditional.",
            "evidence_ids": ["player:hill:1"],
        }]

        report = evaluate_newsroom_fixture(fixture)
        metric = report["runs"][0]["metrics"]["claim_register"]
        self.assertEqual(metric["status"], "scored")
        self.assertEqual(metric["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
