from __future__ import annotations

import unittest

from src.editorial import build_editorial_issue
from src.editorial_ui import inject_editorial_facade


class EditorialIssueTests(unittest.TestCase):
    def test_issue_prioritizes_my_team_and_keeps_claim_evidence(self) -> None:
        tables = {
            "refresh_metadata": [{"generated_at": "2026-08-01T16:48:16+00:00", "current_season": "2026"}],
            "today_priority_board": [
                {
                    "item_type": "core_hold",
                    "item_type_label": "Core Hold",
                    "entity_type": "player",
                    "entity_id": "11",
                    "entity_name": "Pillar Player",
                    "roster_id": "2",
                    "team_name": "My Team",
                    "priority_score": "98",
                    "why": "The projection and timeline make this a roster pillar.",
                    "evidence": "ppg=20.4; points=300; projection=high; market=70; manager=patient builder",
                    "risk": "medium: verify role",
                    "confidence": "high",
                    "source_trace": "https://example.test/nflverse.csv; https://example.test/values.csv",
                },
                {
                    "item_type": "true_buy_low",
                    "item_type_label": "True Buy Low",
                    "entity_type": "player",
                    "entity_id": "12",
                    "entity_name": "League Target",
                    "roster_id": "9",
                    "team_name": "Other Team",
                    "priority_score": "100",
                    "why": "The market gap is wider than the projection risk.",
                    "evidence": "ppg=16.2; market=30; projection=high",
                    "risk": "medium",
                    "confidence": "high",
                    "source_trace": "https://example.test/values.csv",
                },
            ],
            "league_news_impact": [
                {
                    "event_id": "news-1",
                    "published_at": "2026-08-01T08:00:00+00:00",
                    "player_id": "13",
                    "player_name": "News Player",
                    "roster_id": "2",
                    "team_name": "My Team",
                    "impact_type": "role_or_value_change",
                    "evidence": "News Player: role changed.",
                    "confidence": "medium",
                    "risk": "watch role",
                    "source_trace": "https://example.test/news",
                }
            ],
            "manager_behavior_signals": [
                {
                    "roster_id": "2",
                    "team_name": "My Team",
                    "trade_activity_score": "67",
                    "pick_buyer_score": "20",
                    "pick_seller_score": "60",
                    "plain_language_label": "pick seller / win-now buyer",
                    "evidence": "trades=46; future_1sts_out=7",
                    "confidence": "high",
                }
            ],
            "market_consensus_values": [{"player_id": "11"}],
            "source_freshness": [
                {"source": "market", "dataset": "values", "status": "cached", "row_count": "1"},
                {"source": "picks", "dataset": "pick_values", "status": "unavailable:HTTPError", "row_count": "0"},
            ],
            "news_source_freshness": [{"source": "news", "dataset": "rss", "status": "cached", "row_count": "1"}],
            "projection_source_freshness": [{"source": "projection", "dataset": "stats", "status": "cached", "row_count": "1"}],
        }

        issue = build_editorial_issue(
            tables,
            {"dailyGmBriefMode": "deterministic_template"},
            league_id="league-1",
            my_roster_id=2,
            my_team_name="My Team",
        )

        self.assertEqual(issue["schema_version"], "issue_v1")
        self.assertEqual(issue["league_id"], "league-1")
        self.assertEqual(issue["team_name"], "My Team")
        self.assertEqual(issue["lead"]["entity_name"], "Pillar Player")
        self.assertIn("pillar", issue["lead"]["headline"].lower())
        self.assertIn("Projected PPG", {claim["label"] for claim in issue["lead"]["claims"]})
        self.assertEqual(issue["lead"]["sources"][0]["label"], "nflverse")
        self.assertEqual(issue["source_health_summary"]["label"], "3/4 sources current · read the limits")
        self.assertEqual({story["story_type"] for story in issue["stories"]}, {"market", "news", "manager"})

    def test_empty_issue_is_an_honest_quiet_edition(self) -> None:
        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            league_id="quiet",
            my_roster_id=4,
            my_team_name="Quiet Team",
        )

        self.assertEqual(issue["lead"]["story_type"], "quiet")
        self.assertIn("No forced moves", issue["lead"]["headline"])
        self.assertEqual(issue["stories"], [])
        self.assertEqual(issue["freshness_label"], "Freshness unavailable")

    def test_reporter_persona_changes_deterministic_reader_voice(self) -> None:
        tables = {
            "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
            "today_priority_board": [
                {
                    "item_type": "true_buy_low",
                    "item_type_label": "True Buy Low",
                    "entity_type": "player",
                    "entity_id": "11",
                    "entity_name": "Signal Player",
                    "roster_id": "8",
                    "priority_score": "90",
                    "why": "The market gap is measurable.",
                    "evidence": "market=20; projection=high",
                    "risk": "medium",
                    "confidence": "high",
                }
            ],
        }

        quant = build_editorial_issue(
            tables,
            league_id="quant-league",
            my_roster_id=2,
            my_team_name="Quant Team",
            config={"writer_preferences": {"persona_id": "quant"}},
        )
        scout = build_editorial_issue(
            tables,
            league_id="scout-league",
            my_roster_id=2,
            my_team_name="Scout Team",
            config={"writer_preferences": {"persona_id": "scout"}},
        )

        self.assertEqual(quant["reporter_persona"]["persona_id"], "quant")
        self.assertIn("gap is measurable", quant["lead"]["headline"])
        self.assertIn("role signal", scout["lead"]["headline"])
        self.assertNotEqual(quant["lead"]["headline"], scout["lead"]["headline"])


class EditorialUiTests(unittest.TestCase):
    def test_injector_adds_reader_facade_and_preserves_workbench_hooks(self) -> None:
        page = """<html><head><style></style></head><body>
<div class="brand-kicker">Dynasty Command</div>
<p>Find the market leak, then pretend it was obvious all along.</p>
<p><span id="active-team-label">Team</span> weekly command surface. Read-only, because the league chat already has enough chaos.</p>
<section id="view-today">
    <div id="todays-board" class="view-block"><h2>Old board</h2></div>
    <div id="decision-board" class="view-block"><h2>Decision Board</h2></div>
</section>
<script>let analysis = {};
      analysis = app.analysis || {};
      document.getElementById('active-team-label').textContent = teamName;
    function priorityCards(rows) {</script>
</body></html>"""

        rendered = inject_editorial_facade(page)

        self.assertIn('data-testid="editorial-issue"', rendered)
        self.assertIn("Personal Edition", rendered)
        self.assertIn("Your league, edited into a morning read", rendered)
        self.assertIn("let editorial = {};", rendered)
        self.assertIn("editorial = app.editorial || {};", rendered)
        self.assertIn("function renderEditorial()", rendered)
        self.assertIn("Today's Board", rendered)
        self.assertIn("function priorityCards(rows)", rendered)


if __name__ == "__main__":
    unittest.main()
