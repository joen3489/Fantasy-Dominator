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
        self.assertEqual(issue["latest_news_label"], "Aug 1")
        self.assertEqual(issue["lead"]["entity_name"], "Pillar Player")
        self.assertIn("pillar", issue["lead"]["headline"].lower())
        self.assertIn("Baseline PPG", {claim["label"] for claim in issue["lead"]["claims"]})
        self.assertEqual(issue["lead"]["sources"][0]["label"], "nflverse")
        self.assertEqual(issue["source_health_summary"]["label"], "3/4 sources current · read the limits")
        self.assertEqual(
            [row["label"] for row in issue["source_health"]],
            ["Market · Values", "Picks · Pick values", "News · Rss", "Projection · Stats"],
        )
        self.assertEqual({story["story_type"] for story in issue["stories"]}, {"market", "news", "manager"})
        self.assertTrue(all(story.get("reporter_id") and story.get("reporter_name") for story in issue["stories"]))
        self.assertNotIn("My Team", {story.get("reporter_name") for story in issue["stories"]})
        self.assertEqual(
            {panel["key"] for panel in issue["front_page_panels"]},
            {"team_pulse", "news_watch", "market_watch", "manager_watch"},
        )
        market_panel = next(panel for panel in issue["front_page_panels"] if panel["key"] == "market_watch")
        self.assertTrue(market_panel["uncertainty"])
        self.assertTrue(all("evidence" in item for item in market_panel["items"]))

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

    def test_market_panel_prefers_scoped_news_market_edges(self) -> None:
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "news_market_edges": [
                    {
                        "player_id": "11",
                        "player_name": "News Lag WR",
                        "position": "WR",
                        "roster_id": "2",
                        "team_name": "My Team",
                        "news_direction": "upside",
                        "edge_type": "news_lag_upside",
                        "news_impact": "market_heat",
                        "news_event_count": "2",
                        "market_value": "22",
                        "projected_ppg": "14.2",
                        "injury_status": "Questionable",
                        "news_market_edge_score": "51",
                        "evidence": "news=market_heat; market_gap=44",
                        "risk": "verify live price",
                        "confidence": "high",
                        "source_trace": "news_market_edges;league_news_impact",
                    }
                ],
            },
            my_roster_id=2,
            my_team_name="My Team",
        )

        market_panel = next(panel for panel in issue["front_page_panels"] if panel["key"] == "market_watch")
        self.assertEqual(market_panel["title"], "Where news is ahead of price")
        self.assertIn("market_heat", market_panel["items"][0]["summary"])
        self.assertIn("conditional baseline PPG if active is 14.2", market_panel["items"][0]["summary"])
        self.assertIn("news_market_edges", market_panel["items"][0]["evidence"])

    def test_horizon_market_panel_keeps_history_receipt_and_recovery_boundary_visible(self) -> None:
        # Encodes docs/data_contract.md: a bounded career scenario must expose
        # its historical join receipt alongside the separate market clocks.
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "player_horizon_market_scores": [
                    {
                        "player_id": "11",
                        "player_name": "Flagged Player",
                        "position": "RB",
                        "roster_id": "2",
                        "horizon_model_version": "horizon_market_v2",
                        "horizon_score_basis": "position-relative percentile score from 0-100 within the current season cohort; not a dollar market value and not a cross-position price ranking",
                        "market_value": "52",
                        "market_percentile": "64",
                        "next_game_market_score": "42",
                        "next_game_minus_market_delta": "-22",
                        "next_game_opponent": "DAL",
                        "rest_of_season_market_score": "71",
                        "rest_of_season_minus_market_delta": "7",
                        "rest_of_season_minus_next_game_delta": "29",
                        "dynasty_market_score": "55",
                        "dynasty_minus_market_delta": "-9",
                        "dynasty_minus_rest_of_season_delta": "-16",
                        "career_projection_score": "48",
                        "career_minus_market_delta": "-16",
                        "career_minus_dynasty_delta": "-7",
                        "career_history_join_method": "normalized_name_position_unique_source_id",
                        "career_history_source_player_id": "history-p1",
                        "career_history_status": "matched",
                        "career_history_seasons": "2",
                        "career_history_games": "34",
                        "career_history_ppg": "15.4",
                        "career_history_latest_season": "2025",
                        "contender_fit_score": "50",
                        "rebuilder_fit_score": "66",
                        "rebuilder_contender_spread": "16",
                        "value_lane": "rebuilder_edge",
                        "confidence": "medium",
                        "source_trace": "player_horizon_market_scores",
                    }
                ],
            },
            my_roster_id=2,
            my_team_name="My Team",
        )

        market_panel = next(panel for panel in issue["front_page_panels"] if panel["key"] == "market_watch")
        self.assertIn("Rest-of-season baseline is not recovery-adjusted", market_panel["items"][0]["summary"])
        self.assertIn("position-relative percentiles", market_panel["items"][0]["summary"])
        self.assertIn("price anchor is market value 52", market_panel["items"][0]["summary"])
        self.assertIn("change from next game 29", market_panel["items"][0]["summary"])
        self.assertIn("clock-minus-market -22", market_panel["items"][0]["summary"])
        self.assertIn("horizon_score_basis=position-relative percentile", market_panel["items"][0]["evidence"])
        self.assertIn("career history matched (15.4 PPG, 34 games / 2 seasons)", market_panel["items"][0]["summary"])
        self.assertIn("career_history_join_method=normalized_name_position_unique_source_id", market_panel["items"][0]["evidence"])
        self.assertIn("career_history_source_player_id=history-p1", market_panel["items"][0]["evidence"])
        self.assertIn("career_history_status=matched", market_panel["items"][0]["evidence"])

    def test_market_panel_publishes_an_available_clock_with_eligibility_boundary(self) -> None:
        """Design source: docs/data_contract.md; available rows are research, not waiver receipts."""
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-26T00:00:00+00:00", "current_season": "2026"}],
                "available_player_horizon_scores": [
                    {
                        "league_id": "league-1",
                        "season": "2026",
                        "player_id": "available-1",
                        "player_name": "Available Clock WR",
                        "position": "WR",
                        "availability_status": "not_rostered_in_selected_league",
                        "identity_status": "sleeper_id",
                        "fit_coverage": "4/4",
                        "next_game_market_score": "72",
                        "rest_of_season_market_score": "84",
                        "rest_of_season_minus_next_game_delta": "12",
                        "dynasty_market_score": "61",
                        "dynasty_minus_rest_of_season_delta": "-23",
                        "career_projection_score": "70",
                        "career_minus_dynasty_delta": "9",
                        "contender_fit_score": "78",
                        "rebuilder_fit_score": "65",
                        "value_lane": "contender_edge",
                        "market_value": "12",
                        "evidence": "availability=not_rostered_in_selected_league",
                        "source_trace": "available_player_horizon_scores",
                    }
                ],
            },
            league_id="league-1",
            my_roster_id=2,
            my_team_name="My Team",
            config={"current_season": "2026"},
        )

        market_panel = next(panel for panel in issue["front_page_panels"] if panel["key"] == "market_watch")
        available_item = next(item for item in market_panel["items"] if "Available Clock WR" in item["title"])
        self.assertIn("this-week score 72", available_item["summary"])
        self.assertIn("rest-of-season score 84", available_item["summary"])
        self.assertIn("not a waiver-eligibility receipt", available_item["summary"])
        self.assertIn("available_player_horizon_scores", available_item["evidence"])
        self.assertIn({"label": "Available clocks", "value": 1}, market_panel["facts"])

    def test_homepage_uses_richer_manager_dossier_when_available(self) -> None:
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-25T00:00:00+00:00", "current_season": "2026"}],
                "manager_behavior_signals": [{"roster_id": 2, "team_name": "My Team", "trade_activity_score": 20}],
            },
            {
                "managerDossierItems": [
                    {
                        "roster_id": 2,
                        "team_name": "My Team",
                        "dynasty_cycle": "rebuild",
                        "confidence": "medium",
                        "evidence": "18 observed trades; 3 seasons",
                        "source_trace": "manager_profiles;manager_season_history",
                        "analysis_text": "My Team has a long-memory profile.",
                        "sample_size": {"seasons": 3, "trades": 18},
                        "roster_construction": {"market_value_total": 240},
                        "outcome_summary": {"record": "4-2-0"},
                    }
                ]
            },
            my_roster_id=2,
            my_team_name="My Team",
        )

        manager_story = next(story for story in issue["stories"] if story["entity_type"] == "manager")
        self.assertEqual(manager_story["eyebrow"], "Manager dossier")
        self.assertIn("history", manager_story["headline"])
        self.assertIn("Outcome record", {claim["label"] for claim in manager_story["claims"]})

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

    def test_issue_reports_mixed_writer_mode_truthfully(self) -> None:
        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            {
                "dailyGmBriefMode": "deterministic_template",
                "teamReportMode": "automatic_llm",
                "marketWatchMode": "automatic_llm",
            },
            league_id="mixed-league",
            my_roster_id=2,
            my_team_name="Mixed Team",
        )

        self.assertEqual(issue["writer_mode"], "Mixed edition")
        self.assertEqual(issue["article_modes"]["team_report"], "automatic_llm")
        self.assertEqual(issue["article_modes"]["daily_brief"], "deterministic_template")

    def test_issue_publishes_article_body_with_receipt_instead_of_only_counting_it(self) -> None:
        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            {
                "teamReport": "---\nmodel_mode: automatic_llm\n---\n# Your Team Report\n\n## Cornerstones\nA real report.",
                "teamReportMode": "automatic_llm",
                "articleReceipts": {
                    "team_report": {
                        "mode": "automatic_llm",
                        "reporter_name": "Topline Tony",
                        "evidence_fingerprint": "evidence-123",
                        "content_hash": "content-123",
                        "structured": {
                            "headline": "Your Team Report",
                            "thesis": "The roster has a decision-relevant edge.",
                            "what_changed": "The current evidence packet was reviewed.",
                            "action": "Inspect the evidence before acting.",
                            "evidence_ids": ["player:1:1"],
                            "source_ids": ["player_dossiers"],
                        },
                    }
                },
            },
            league_id="publication-league",
            my_roster_id=2,
            my_team_name="Publication Team",
        )

        self.assertEqual(len(issue["publication_articles"]), 1)
        self.assertIn("A real report", issue["publication_articles"][0]["body"])
        self.assertEqual(issue["publication_articles"][0]["reporter_name"], "Topline Tony")
        self.assertEqual(issue["publication_articles"][0]["evidence_fingerprint"], "evidence-123")

    def test_persisted_llm_hold_stays_off_the_printed_facade(self) -> None:
        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            {
                "teamReport": "# Your Team Report\n\n## Cornerstones\nA draft that needs repair.",
                "teamReportMode": "automatic_llm",
                "articleReceipts": {
                    "team_report": {
                        "mode": "automatic_llm",
                        "reporter_name": "Topline Tony",
                        "structured": {
                            "headline": "A draft",
                            "thesis": "The packet supports a read.",
                            "what_changed": "The packet changed.",
                            "action": "Inspect the receipt.",
                            "evidence_ids": ["player:1:1"],
                            "source_ids": ["source:stats"],
                        },
                        "editorial_review": {
                            "mode": "llm",
                            "model": "gpt-5.6-luna",
                            "status": "held",
                            "decision": "hold",
                            "errors": ["The current availability caveat is missing."],
                            "note": "Held for an availability repair.",
                        },
                    }
                },
            },
            league_id="editor-league",
            my_roster_id=2,
            my_team_name="Editor Team",
        )

        publication = issue["publication_articles"][0]
        self.assertEqual(publication["publication_status"], "held")
        self.assertEqual(publication["body"], "")
        self.assertEqual(publication["editorial_review"]["mode"], "llm")
        self.assertIn("availability repair", publication["editorial_review"]["note"])

    def test_publication_articles_use_desk_templates_and_semantic_content_blocks(self) -> None:
        article_receipts = {
            key: {
                "structured": {
                    "headline": key.replace("_", " ").title(),
                    "thesis": "The evidence packet contains a supported read.",
                    "what_changed": "The current edition was assembled from validated rows.",
                    "action": "Open the evidence receipt before acting.",
                    "evidence_ids": [f"{key}:1:1"],
                    "source_ids": [f"{key}_source"],
                }
            }
            for key in ("daily_brief", "team_report", "market_watch", "horizon_watch", "trade_desk", "manager_intel")
        }
        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            {
                "dailyGmBrief": "---\nmodel_mode: deterministic_template\n---\n# Daily GM Brief\n\n## Target Theses\nA connected read.\n\n- Watch the market.",
                "teamReport": "# Team Report\n\n## Cornerstones\nBuild around the core.",
                "marketWatch": "# Market Watch\n\n## Buy-Low Targets\nFind the disagreement.",
                "horizonWatch": "# Four-Window Market Read\n\n## This Week\nKeep the windows separate.",
                "tradeDeskRead": "# Trade Desk\n\n## Best Fits\nStart with evidence.",
                "managerIntel": "# Manager Intel\n\n## Contenders\nStudy the history.",
                "articleReceipts": article_receipts,
            },
            league_id="template-league",
            my_roster_id=2,
            my_team_name="Template Team",
        )

        articles = {article["key"]: article for article in issue["publication_articles"]}
        self.assertEqual(articles["daily_brief"]["template_id"], "morning-ledger")
        self.assertEqual(articles["daily_brief"]["template"]["list_preview_items"], 3)
        self.assertEqual(articles["team_report"]["template"]["layout"], "wide")
        self.assertEqual(
            [block["type"] for block in articles["daily_brief"]["content_blocks"]],
            ["heading", "paragraph", "list"],
        )
        self.assertEqual(
            {article["template_id"] for article in articles.values()},
            {"morning-ledger", "team-notebook", "market-ticker", "four-window-ledger", "trade-desk", "manager-dossier"},
        )

    def test_fallback_publication_receipts_use_the_assigned_newsroom_reporter(self) -> None:
        """Encodes docs/front_office_principles.md's analyst-lens contract at the reader seam."""
        analysis = {
            "dailyGmBrief": "Daily fallback",
            "teamReport": "Team fallback",
            "marketWatch": "Market fallback",
            "tradeDeskRead": "Trade fallback",
            "managerIntel": "Manager fallback",
            "articleReceipts": {
                key: {"mode": "deterministic_template", "reporter_id": "front_office"}
                for key in ("daily_brief", "team_report", "market_watch", "trade_desk", "manager_intel")
            },
        }

        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            analysis,
            league_id="reporter-contract-league",
            my_roster_id=2,
            my_team_name="Reporter Contract Team",
        )

        expected = {
            "daily_brief": "look_ahead_lonnie",
            "team_report": "topline_tony",
            "market_watch": "waiver_wire_waverly",
            "trade_desk": "trade_desk_talia",
            "manager_intel": "dossier_dana",
        }
        for article in issue["publication_articles"]:
            reporter_id = expected[article["key"]]
            self.assertEqual(article["reporter_id"], reporter_id)
            self.assertEqual(article["reporter_persona"]["persona_id"], reporter_id)
            self.assertEqual(article["reporter_name"], article["reporter_persona"]["name"])

    def test_deterministic_publication_is_labeled_fallback_not_editor_approved(self) -> None:
        """Design source: AGENTS.md; fallback content must not imply a paid editor review."""
        receipt = {
            "mode": "deterministic_template",
            "structured": {
                "headline": "Evidence-led read",
                "thesis": "The packet supports a bounded read.",
                "what_changed": "The current refresh updated the packet.",
                "action": "Open the source receipt before acting.",
                "evidence_ids": ["player:11:1"],
                "source_ids": ["source:stats"],
            },
        }
        issue = build_editorial_issue(
            {"refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}]},
            {
                "teamReport": "# Your Team Report\n\nA deterministic evidence-led report.",
                "teamReportMode": "deterministic_template",
                "articleReceipts": {"team_report": receipt},
            },
            league_id="fallback-review-league",
            my_roster_id=2,
            my_team_name="Fallback Team",
        )

        publication = issue["publication_articles"][0]
        self.assertEqual(publication["publication_status"], "fallback")
        self.assertEqual(publication["editorial_review"]["decision"], "keep_fallback")
        self.assertIn("deterministic evidence-led fallback", publication["editorial_review"]["note"])
        self.assertTrue(publication["body"])

    def test_private_manager_profile_changes_evidence_led_edition(self) -> None:
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "manager_behavior_signals": [
                    {
                        "roster_id": "9",
                        "team_name": "Rival Team",
                        "trade_activity_score": "80",
                        "plain_language_label": "pick buyer",
                        "evidence": "future_1sts_in=4",
                        "confidence": "high",
                    }
                ],
            },
            league_id="profile-league",
            my_roster_id=2,
            my_team_name="My Team",
            config={
                "manager_trade_profiles": [
                    {
                        "roster_id": "9",
                        "manager_name": "Rival Team",
                        "trade_style": "patient pick accumulator",
                        "preferred_assets": "future firsts",
                        "protected_assets": "young running backs",
                        "editor_note": "Start with picks; do not lead with veterans.",
                    }
                ]
            },
        )

        profile_story = next(story for story in issue["stories"] if story["story_id"] == "manager:note:9")
        self.assertEqual(profile_story["eyebrow"], "Personalized manager lens")
        self.assertIn("Start with picks", profile_story["dek"])
        self.assertIn("not source evidence", profile_story["evidence"])
        self.assertEqual(issue["signal_summary"]["custom_manager_profiles"], 1)

    def test_front_page_market_panel_connects_news_and_manager_rows_without_inventing_certainty(self) -> None:
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "roster_players": [
                    {"season": "2026", "roster_id": "2", "player_id": "11", "roster_status": "starter", "injury_status": "Questionable"},
                ],
                "player_dossiers": [
                    {"roster_id": "2", "player_id": "11", "player_name": "My Player", "market_value": "22", "projected_ppg": "14.2", "signal_label": "buy_or_watch"},
                ],
                "player_signal_scores": [
                    {"roster_id": "2", "player_id": "11", "player_name": "My Player", "position": "WR", "team_name": "My Team", "market_value": "22", "projected_ppg": "14.2", "market_gap_score": "35", "confidence": "high", "availability_note": "Questionable (knee); baseline projection does not adjust for availability", "source_trace": "market;projection"},
                ],
                "league_news_impact": [
                    {"event_id": "news-1", "source": "rotowire_rss", "published_at": "2026-08-01T01:00:00+00:00", "player_id": "11", "player_name": "My Player", "roster_id": "2", "impact_type": "injury_risk", "evidence": "My Player left practice.", "confidence": "medium", "risk": "medium", "source_trace": "news-source"},
                ],
                "manager_behavior_signals": [
                    {"roster_id": "9", "team_name": "Rival Team", "trade_activity_score": "80", "plain_language_label": "pick buyer", "confidence": "medium", "evidence": "trades=12"},
                ],
            },
            my_roster_id=2,
            my_team_name="My Team",
        )

        panels = {panel["key"]: panel for panel in issue["front_page_panels"]}
        self.assertIn("conditional baseline PPG if active 14.2", panels["news_watch"]["items"][0]["summary"])
        self.assertNotIn("Model context:;", panels["news_watch"]["items"][0]["summary"])
        self.assertIn("Questionable", panels["market_watch"]["items"][0]["summary"])
        self.assertIn("not a projection", panels["news_watch"]["uncertainty"])
        self.assertEqual(panels["manager_watch"]["items"][0]["title"], "Rival Team")

    def test_front_page_news_filter_handles_numeric_league_ids_without_cross_league_leakage(self) -> None:
        """Encodes the data-contract rule that league IDs scope private news rows."""
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "roster_players": [
                    {"season": "2026", "roster_id": 2.0, "player_id": "11", "roster_status": "starter"},
                ],
                "player_dossiers": [
                    {"roster_id": 2.0, "player_id": "11", "player_name": "My Player", "market_value": "22", "projected_ppg": "14.2"},
                ],
                "league_news_impact": [
                    {
                        "event_id": "current-league-news",
                        "published_at": "2026-08-01T01:00:00+00:00",
                        "player_id": "11",
                        "player_name": "My Player",
                        "league_id": 1.313490073630548e18,
                        "season": "2026",
                        "roster_id": 2.0,
                        "team_name": "My Team",
                        "impact_type": "role_or_value_change",
                        "evidence": "Current league signal.",
                        "confidence": "high",
                        "risk": "medium",
                        "source_trace": "news-source-current",
                    },
                    {
                        "event_id": "other-league-news",
                        "published_at": "2026-08-01T02:00:00+00:00",
                        "player_id": "11",
                        "player_name": "My Player",
                        "league_id": 1.1802096767965307e18,
                        "season": "2026",
                        "roster_id": 2.0,
                        "team_name": "Other League Team",
                        "impact_type": "role_or_value_change",
                        "evidence": "Other league signal.",
                        "confidence": "high",
                        "risk": "medium",
                        "source_trace": "news-source-other",
                    },
                ],
            },
            league_id="1313490073630547968",
            my_roster_id=2,
            my_team_name="My Team",
        )

        panels = {panel["key"]: panel for panel in issue["front_page_panels"]}
        self.assertEqual(panels["news_watch"]["facts"][0]["value"], 1)
        self.assertEqual(panels["news_watch"]["facts"][1]["value"], 1)
        self.assertIn("Current league signal", panels["news_watch"]["items"][0]["summary"])
        self.assertNotIn("Other league signal", panels["news_watch"]["items"][0]["summary"])

    def test_front_page_does_not_promote_wrong_manager_when_roster_join_is_missing(self) -> None:
        """Design source: AGENTS.md; a personalized manager read needs an exact roster ID."""
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "manager_behavior_signals": [
                    {"roster_id": "8", "team_name": "Moose Caboose", "trade_activity_score": "100", "evidence": "wrong roster"},
                ],
            },
            my_roster_id=2,
            my_team_name="Lulu's Potatoes",
        )

        panel = next(panel for panel in issue["front_page_panels"] if panel["key"] == "manager_watch")
        self.assertEqual(panel["facts"][0]["value"], 1)
        # The manager-watch rail is intentionally a rival-study surface, so
        # another roster may appear there. The selected edition's own story
        # must remain quiet when its exact manager row is absent.
        self.assertFalse(any(story.get("entity_type") == "manager" for story in issue["stories"]))

    def test_front_page_market_filter_keeps_repeated_roster_ids_inside_league(self) -> None:
        """Design source: docs/data_contract.md; horizon rows are league-scoped before display."""
        issue = build_editorial_issue(
            {
                "refresh_metadata": [{"generated_at": "2026-08-01T00:00:00+00:00", "current_season": "2026"}],
                "player_horizon_market_scores": [
                    {
                        "league_id": "league-a", "season": "2026", "roster_id": "2", "player_id": "a",
                        "player_name": "League A Asset", "position": "WR", "value_lane": "contender_edge",
                        "next_game_market_score": "80", "rest_of_season_market_score": "75", "dynasty_market_score": "60", "career_projection_score": "55",
                        "market_value": "30", "market_percentile": "70", "rebuilder_contender_spread": "-10", "confidence": "high",
                        "source_trace": "league-a",
                    },
                    {
                        "league_id": "league-b", "season": "2026", "roster_id": "2", "player_id": "b",
                        "player_name": "League B Asset", "position": "WR", "value_lane": "rebuilder_edge",
                        "next_game_market_score": "90", "rest_of_season_market_score": "85", "dynasty_market_score": "80", "career_projection_score": "75",
                        "market_value": "40", "market_percentile": "80", "rebuilder_contender_spread": "15", "confidence": "high",
                        "source_trace": "league-b",
                    },
                ],
            },
            league_id="league-a",
            my_roster_id=2,
            my_team_name="League A Team",
        )

        panel = next(panel for panel in issue["front_page_panels"] if panel["key"] == "market_watch")
        rendered = str(panel)
        self.assertIn("League A Asset", rendered)
        self.assertNotIn("League B Asset", rendered)


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
        self.assertIn("return rows.map(row =>", rendered)
        self.assertNotIn("rows.slice(0, 5)", rendered)
        self.assertIn("Today's Board", rendered)
        self.assertIn("Front page desk", rendered)
        self.assertIn("frontPagePanelMarkup", rendered)
        self.assertIn('data-testid="front-page-desk"', rendered)
        self.assertIn("Desk reports", rendered)
        self.assertIn("publicationArticleMarkup", rendered)
        self.assertIn("publicationContentBlocksMarkup", rendered)
        self.assertIn("publicationListItemMarkup", rendered)
        self.assertIn("Show ${items.length - previewLimit} more evidence-backed calls", rendered)
        self.assertIn("publication-layout-feature", rendered)
        self.assertIn("data-content-block-schema=\"publication_blocks_v1\"", rendered)
        self.assertNotIn("        story.team_name,\n", rendered)
        self.assertIn("function priorityCards(rows)", rendered)


if __name__ == "__main__":
    unittest.main()
