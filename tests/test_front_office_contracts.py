from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import articles, operator
from src.context import FantasyContext
from src.llm import call_structured_tool, configured_llm, llm_timeout_seconds
from src.personas import persona_prompt_block, reporter_lineup
from src.editorial import _newsroom_conversation, _newsroom_edges, review_publication_article


class FrontOfficeContractsTests(unittest.TestCase):
    def test_legacy_edition_job_store_receives_the_client_request_id_migration(self) -> None:
        """Design source: AGENTS.md; additive migrations must protect existing durable stores."""

        from app import db

        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "app.db"
            with patch.object(db, "DB_PATH", database):
                db.init_db()
                conn = sqlite3.connect(database)
                try:
                    conn.execute("ALTER TABLE edition_jobs RENAME TO edition_jobs_legacy")
                    conn.execute(
                        """
                        CREATE TABLE edition_jobs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id TEXT NOT NULL,
                            article_key TEXT NOT NULL,
                            phase TEXT NOT NULL DEFAULT 'writer',
                            state TEXT NOT NULL DEFAULT 'queued',
                            attempt INTEGER NOT NULL DEFAULT 0,
                            started_at TEXT,
                            updated_at TEXT NOT NULL,
                            completed_at TEXT,
                            evidence_fingerprint TEXT NOT NULL DEFAULT '',
                            prompt_version TEXT NOT NULL DEFAULT '',
                            lease_until TEXT,
                            worker_id TEXT NOT NULL DEFAULT '',
                            provider TEXT NOT NULL DEFAULT '',
                            model TEXT NOT NULL DEFAULT '',
                            reasoning_effort TEXT NOT NULL DEFAULT '',
                            provider_request_id TEXT NOT NULL DEFAULT '',
                            usage_json TEXT NOT NULL DEFAULT '{}',
                            metadata_json TEXT NOT NULL DEFAULT '{}',
                            error_class TEXT NOT NULL DEFAULT '',
                            error_message TEXT NOT NULL DEFAULT '',
                            UNIQUE(run_id, article_key, phase),
                            FOREIGN KEY(run_id) REFERENCES edition_runs(run_id)
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO edition_jobs(
                            id, run_id, article_key, phase, state, attempt,
                            started_at, updated_at, completed_at, evidence_fingerprint,
                            prompt_version, lease_until, worker_id, provider, model,
                            reasoning_effort, provider_request_id, usage_json,
                            metadata_json, error_class, error_message
                        )
                        SELECT id, run_id, article_key, phase, state, attempt,
                            started_at, updated_at, completed_at, evidence_fingerprint,
                            prompt_version, lease_until, worker_id, provider, model,
                            reasoning_effort, provider_request_id, usage_json,
                            metadata_json, error_class, error_message
                        FROM edition_jobs_legacy
                        """
                    )
                    conn.execute("DROP TABLE edition_jobs_legacy")
                    conn.commit()
                finally:
                    conn.close()

                db.init_db()
                conn = sqlite3.connect(database)
                try:
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(edition_jobs)")}
                finally:
                    conn.close()

                self.assertIn("client_request_id", columns)

    def test_edition_packet_freezes_inputs_and_holds_when_the_workspace_changes(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; a resumed edition cannot mix evidence snapshots."""

        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            analysis = Path(tmp) / "analysis"
            processed.mkdir()
            analysis.mkdir()
            (processed / "refresh_metadata.csv").write_text(
                "generated_at,current_season,refresh_mode\n2026-08-27T12:00:00+00:00,2026,full\n",
                encoding="utf-8",
            )
            context = FantasyContext(
                user_id="clerk-17",
                league_id="league-17",
                season="2026",
                roster_id=2,
                team_name="Lulu's Potatoes",
            )
            with patch.object(operator, "PROCESSED_DIR", processed), patch.object(operator, "ANALYSIS_DIR", analysis):
                packet = operator._freeze_edition_packet(
                    context,
                    "run-17",
                    ["team_report", "daily_brief"],
                    {"schema_version": "reality_check_v1", "status": "pass", "fingerprint": "reality-17"},
                )
                self.assertEqual(packet["schema_version"], operator.EDITION_PACKET_SCHEMA_VERSION)
                self.assertEqual(packet["scope"]["roster_id"], 2)
                self.assertEqual(packet["requested_article_keys"], ["daily_brief", "team_report"])
                self.assertTrue(packet["edition_fingerprint"])
                self.assertTrue((analysis / "edition_runs" / "run-17.json").is_file())
                self.assertTrue(operator._edition_packet_matches_current(packet))

                (processed / "roster_players.csv").write_text(
                    "league_id,season,roster_id,player_id\nleague-17,2026,2,99\n",
                    encoding="utf-8",
                )
                with self.assertRaises(operator.EditionInputChanged):
                    operator._freeze_edition_packet(
                        context,
                        "run-17",
                        ["team_report", "daily_brief"],
                        {"schema_version": "reality_check_v1", "status": "pass", "fingerprint": "reality-17"},
                    )

    def test_edition_cancellation_seam_calls_the_durable_ledger(self) -> None:
        """Design source: AGENTS.md; worker cancellation must remain fail-closed at the ledger seam."""

        with patch("app.db.edition_run_cancel_requested", return_value=True) as cancelled:
            self.assertTrue(operator._edition_run_cancelled("run-17"))
            cancelled.assert_called_once_with("run-17")

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

    def test_running_status_from_live_worker_is_not_marked_interrupted(self) -> None:
        """Design source: AGENTS.md; a shared receipt must not be mistaken for a dead job."""

        with tempfile.TemporaryDirectory() as tmp:
            status_dir = Path(tmp) / "operator" / "status"
            status_path = status_dir / "operator_status.json"
            status_dir.mkdir(parents=True)
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "job": "generate-insights",
                        "message": "The reporters are writing.",
                        "owner_pid": 987654,
                        "updated_at": "2026-08-26T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(operator, "STATUS_PATH", status_path), patch.object(
                operator, "OPERATOR_STATUS_DIR", status_dir
            ), patch.object(operator, "_ACTIVE_JOB", False), patch.object(
                operator, "_owner_process_is_alive", return_value=True
            ) as owner_alive:
                observed = operator.status()

            self.assertEqual(observed["state"], "running")
            self.assertNotIn("recovered_from_restart", observed)
            owner_alive.assert_called_once_with(987654)
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "running")

    def test_running_status_from_dead_worker_is_recovered(self) -> None:
        """Design source: AGENTS.md; orphaned paid work must fail closed with a retryable receipt."""

        with tempfile.TemporaryDirectory() as tmp:
            status_dir = Path(tmp) / "operator" / "status"
            status_path = status_dir / "operator_status.json"
            status_dir.mkdir(parents=True)
            status_path.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "job": "generate-insights",
                        "message": "The reporters are writing.",
                        "owner_pid": 987654,
                        "updated_at": "2026-08-26T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(operator, "STATUS_PATH", status_path), patch.object(
                operator, "OPERATOR_STATUS_DIR", status_dir
            ), patch.object(operator, "_ACTIVE_JOB", False), patch.object(
                operator, "_owner_process_is_alive", return_value=False
            ) as owner_alive:
                recovered = operator.status()

            self.assertEqual(recovered["state"], "failed")
            self.assertTrue(recovered["recovered_from_restart"])
            owner_alive.assert_called_once_with(987654)
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "failed")

    def test_restart_recovery_marks_the_durable_edition_interrupted(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; a daemon restart cannot leave a paid run looking alive."""

        from app import db

        with tempfile.TemporaryDirectory() as tmp:
            status_dir = Path(tmp) / "operator" / "status"
            status_path = status_dir / "operator_status.json"
            status_dir.mkdir(parents=True)
            database_path = Path(tmp) / "app.db"
            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                user = db.get_or_create_user("clerk-restart")
                run = db.start_edition_run(int(user["id"]), "league-restart", "2026", roster_id=2)
                db.start_edition_job(run["run_id"], "team_report", phase="writer")
                status_path.write_text(
                    json.dumps(
                        {
                            "state": "running",
                            "job": "generate-insights",
                            "run_id": "operator-run-1",
                            "edition_run_id": run["run_id"],
                            "message": "The reporters are writing.",
                            "owner_pid": 987654,
                            "updated_at": "2026-08-26T12:00:00+00:00",
                        }
                    ),
                    encoding="utf-8",
                )
                with patch.object(operator, "STATUS_PATH", status_path), patch.object(
                    operator, "OPERATOR_STATUS_DIR", status_dir
                ), patch.object(operator, "_ACTIVE_JOB", False), patch.object(
                    operator, "_owner_process_is_alive", return_value=False
                ):
                    recovered = operator.status()
                durable = db.get_edition_run(run["run_id"])

            self.assertTrue(recovered["recovered_from_restart"])
            self.assertEqual(durable["state"], "interrupted")
            self.assertEqual(durable["stage"], "interrupted")
            self.assertEqual(durable["failure_class"], "worker_restart")
            self.assertEqual(durable["jobs"][0]["state"], "interrupted")

    def test_worker_claims_are_exclusive_and_expired_leases_can_resume(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; retries cannot double-spend a desk call."""

        from app import db

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(db, "DB_PATH", Path(tmp) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("clerk-worker")
                run = db.start_edition_run(
                    int(user["id"]),
                    "league-worker",
                    "2026",
                    roster_id=2,
                    article_keys=["market_watch"],
                    initial_state="queued",
                    initial_stage="queued",
                )
                claimed = db.claim_edition_run(run["run_id"], "worker-a", lease_seconds=60)
                self.assertEqual(claimed["state"], "running")
                self.assertEqual(claimed["worker_id"], "worker-a")
                self.assertIsNone(db.claim_edition_run(run["run_id"], "worker-b", lease_seconds=60))
                job = db.claim_edition_job(
                    run["run_id"],
                    "market_watch",
                    "worker-a",
                    evidence_fingerprint="evidence-1",
                    model="gpt-5.6-luna",
                    client_request_id="fdjob:stable-desk",
                )
                self.assertEqual(job["attempt"], 1)
                self.assertEqual(job["client_request_id"], "fdjob:stable-desk")
                self.assertIsNone(db.claim_edition_job(run["run_id"], "market_watch", "worker-b"))

                conn = db._connect()
                try:
                    conn.execute(
                        "UPDATE edition_runs SET lease_until = ? WHERE run_id = ?",
                        ("2020-01-01T00:00:00+00:00", run["run_id"]),
                    )
                    conn.execute(
                        "UPDATE edition_jobs SET lease_until = ? WHERE run_id = ? AND article_key = ? AND phase = 'writer'",
                        ("2020-01-01T00:00:00+00:00", run["run_id"], "market_watch"),
                    )
                    conn.commit()
                finally:
                    conn.close()

                self.assertIsNone(db.heartbeat_edition_run(run["run_id"], "worker-a", lease_seconds=60))
                reclaimed = db.claim_edition_run(run["run_id"], "worker-b", lease_seconds=60)
                self.assertEqual(reclaimed["worker_id"], "worker-b")
                resumed_job = db.claim_edition_job(run["run_id"], "market_watch", "worker-b")
                self.assertEqual(resumed_job["attempt"], 2)
                self.assertEqual(resumed_job["client_request_id"], "fdjob:stable-desk")
                self.assertIsNone(
                    db.finish_edition_job(
                        run["run_id"],
                        "market_watch",
                        state="published",
                        worker_id="worker-a",
                    )
                )
                finished = db.finish_edition_job(run["run_id"], "market_watch", state="published", worker_id="worker-b")
                self.assertEqual(finished["lease_until"], None)
                self.assertEqual(finished["worker_id"], "")

    def test_worker_queue_supports_cooperative_cancel_and_dead_letter_budget(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; cancellation and retry exhaustion stay explicit."""

        from app import db

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(db, "DB_PATH", Path(tmp) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("clerk-queue-controls")
                queued = db.start_edition_run(
                    int(user["id"]),
                    "league-queue-controls",
                    "2026",
                    roster_id=2,
                    article_keys=["market_watch"],
                    initial_state="queued",
                    initial_stage="queued",
                    max_attempts=1,
                )
                claimed = db.claim_next_edition_run("worker-controls", lease_seconds=60)
                self.assertEqual(claimed["run_id"], queued["run_id"])
                requested = db.request_edition_cancellation(queued["run_id"])
                self.assertEqual(requested["state"], "cancel_requested")
                self.assertIsNone(db.claim_next_edition_run("worker-race", lease_seconds=60))
                self.assertIsNone(db.claim_edition_run(queued["run_id"], "worker-race", lease_seconds=60))
                self.assertEqual(db.heartbeat_edition_run(queued["run_id"], "worker-controls", lease_seconds=60)["state"], "cancel_requested")
                cancelled = db.cancel_edition_run(queued["run_id"], worker_id="worker-controls")
                self.assertEqual(cancelled["state"], "cancelled")

                dead = db.start_edition_run(
                    int(user["id"]),
                    "league-dead-letter",
                    "2026",
                    roster_id=2,
                    article_keys=["market_watch"],
                    initial_state="queued",
                    initial_stage="queued",
                    max_attempts=1,
                )
                db.claim_edition_run(dead["run_id"], "worker-dead", lease_seconds=60)
                db.claim_edition_job(dead["run_id"], "market_watch", "worker-dead")
                db.finish_edition_job(dead["run_id"], "market_watch", state="failed", worker_id="worker-dead")
                conn = db._connect()
                try:
                    conn.execute(
                        "UPDATE edition_runs SET lease_until = ? WHERE run_id = ?",
                        ("2020-01-01T00:00:00+00:00", dead["run_id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
                db.claim_edition_run(dead["run_id"], "worker-dead-2", lease_seconds=60)
                exhausted = db.claim_edition_job(dead["run_id"], "market_watch", "worker-dead-2")
                self.assertEqual(exhausted["state"], "dead_letter")
                self.assertIn("Retry budget exhausted", exhausted["error_message"])

                stale = db.start_edition_run(
                    int(user["id"]),
                    "league-stale-worker",
                    "2026",
                    roster_id=2,
                    article_keys=["market_watch"],
                    initial_state="queued",
                    initial_stage="queued",
                )
                db.claim_edition_run(stale["run_id"], "worker-old", lease_seconds=60)
                conn = db._connect()
                try:
                    conn.execute(
                        "UPDATE edition_runs SET lease_until = ? WHERE run_id = ?",
                        ("2020-01-01T00:00:00+00:00", stale["run_id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
                db.claim_edition_run(stale["run_id"], "worker-new", lease_seconds=60)
                preserved = db.interrupt_edition_run(stale["run_id"], worker_id="worker-old")
                self.assertEqual(preserved["state"], "running")
                self.assertEqual(preserved["worker_id"], "worker-new")

                terminal = db.start_edition_run(
                    int(user["id"]),
                    "league-terminal-seam",
                    "2026",
                    roster_id=2,
                )
                db.update_edition_run(terminal["run_id"], state="complete", stage="complete", complete=True)
                refused = db.start_edition_job(terminal["run_id"], "market_watch")
                self.assertEqual(refused["state"], "complete")

    def test_bounded_writer_fanout_limits_provider_concurrency(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; fan-out is bounded and per-desk."""

        import time

        prepared = [
            {
                "article": MagicMock(key=f"desk_{index}"),
                "evidence": [{"evidence_id": f"evidence:{index}"}],
                "system_prompt": "prompt",
                "editorial_context": [],
                "evidence_fingerprint": f"fingerprint:{index}",
            }
            for index in range(4)
        ]
        active = 0
        maximum = 0

        def fake_writer(*args, **kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(0.03)
            active -= 1
            return {"headline": "Desk result"}

        with patch.object(operator, "writer_concurrency", return_value=2), patch.object(
            operator, "_edition_job_start", return_value={"state": "running"}
        ), patch.object(operator, "generate_article_via_llm", side_effect=fake_writer):
            results = operator._fanout_writer_drafts(
                prepared,
                api_key="test-key",
                model="gpt-5.6-luna",
                provider="openai",
                reasoning_effort="max",
            )

        self.assertEqual(set(results), {f"desk_{index}" for index in range(4)})
        self.assertEqual(maximum, 2)
        self.assertTrue(all(result.get("output") for result in results.values()))

    def test_full_run_seeds_prior_specialist_articles_as_non_evidence_room_context(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; writer continuity must survive specialist fan-out."""

        with tempfile.TemporaryDirectory() as tmp:
            analysis_dir = Path(tmp)
            (analysis_dir / "team_report.md").write_text(
                "---\n"
                "article_payload_json: {\"headline\": \"Last week's stakes\", \"claim_positions\": []}\n"
                "---\n\n# Last week's stakes\n\nThe prior desk saw pressure at quarterback.\n",
                encoding="utf-8",
            )
            ctx = articles.ArticleContext(
                analysis_dir=analysis_dir,
                active_roster_id=2,
                writer_preferences={},
            )

            operator._seed_prior_specialist_context(ctx, {"market_watch"})

            self.assertEqual(set(ctx.section_outputs), set())
            self.assertEqual(set(ctx.prior_section_outputs), {"team_report"})
            room = operator._editorial_room_context(
                ctx,
                next(article for article in articles.ARTICLES if article.key == "market_watch"),
                analysis_dir / "market_watch.md",
            )
            self.assertEqual(room[0]["kind"], "previous_peer_edition")
            self.assertEqual(room[0]["desk"], "team_report")
            self.assertEqual(room[0]["structured"]["editorial_only"], True)
            self.assertIn("prior desk", room[0]["excerpt"])

    def test_newsroom_worker_claims_a_queue_run_and_passes_its_lease_identity(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; the worker owns the real generation seam."""

        from app import db
        from scripts import newsroom_worker

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(db, "DB_PATH", Path(tmp) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("clerk-worker-entrypoint")
                league = db.upsert_user_league(
                    int(user["id"]),
                    {
                        "league_id": "league-worker-entrypoint",
                        "season": "2026",
                        "league_type": "dynasty",
                        "name": "Worker League",
                        "roster_id": 2,
                    },
                )
                run = db.start_edition_run(
                    int(user["id"]),
                    league["league_id"],
                    "2026",
                    roster_id=2,
                    article_keys=["market_watch"],
                    initial_state="queued",
                    initial_stage="queued",
                )

                def fake_generation(league_row, user_id, **kwargs):
                    self.assertEqual(league_row["league_id"], "league-worker-entrypoint")
                    self.assertEqual(user_id, int(user["id"]))
                    self.assertEqual(kwargs["worker_id"], "worker-entrypoint")
                    self.assertEqual(kwargs["edition_run_id_override"], run["run_id"])
                    self.assertEqual(kwargs["article_keys"], {"market_watch"})
                    db.update_edition_run(
                        run["run_id"],
                        state="complete",
                        stage="complete",
                        completed_count=1,
                        total_count=1,
                        complete=True,
                        worker_id="worker-entrypoint",
                    )
                    return {"state": "complete", "message": "worker test complete"}

                with patch.object(newsroom_worker, "_generate_insights_job", side_effect=fake_generation):
                    result = newsroom_worker.run_once("worker-entrypoint")

                self.assertEqual(result["state"], "complete")
                self.assertEqual(db.get_edition_run(run["run_id"])["state"], "complete")
                self.assertTrue(db.newsroom_worker_health()["active"])
                self.assertEqual(db.newsroom_worker_health()["active_worker_count"], 1)

    def test_held_writer_draft_is_rehydrated_for_editor_retry(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; editor repair must not regenerate unchanged prose."""

        article = articles.ARTICLES[0]
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / article.output_filename
            output_path.write_text(
                operator._render_article_markdown(
                    article,
                    "## Cornerstones\nThe unchanged writer draft.",
                    "2026-08-27T12:00:00+00:00",
                    output_path,
                    article_key=article.key,
                    evidence_fingerprint="evidence-1",
                    model="gpt-5.6-luna",
                    structured={"headline": "Unchanged draft", "evidence_ids": ["evidence:1"]},
                    source_receipt={"scope": "validated_article_evidence"},
                    editorial_review={"status": "held", "decision": "hold"},
                    editor_mode="llm",
                ),
                encoding="utf-8",
            )
            reporter = operator.persona_metadata({}, article.key)
            previous = {
                "status": "held",
                "evidence_fingerprint": "evidence-1",
                "content_hash": operator._content_hash(output_path),
                "reporter_id": reporter["persona_id"],
                "writer_mode": "automatic_llm",
                "model": "gpt-5.6-luna",
                "source": {"editor_mode": "llm"},
            }

            self.assertTrue(
                operator._can_reuse_writer_draft(
                    previous,
                    output_path,
                    "evidence-1",
                    reporter,
                    "gpt-5.6-luna",
                    "llm",
                )
            )
            candidate = operator._existing_article_writer_output(output_path)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["headline"], "Unchanged draft")
        self.assertEqual(candidate["cited_evidence_ids"], ["evidence:1"])
        self.assertIn("unchanged writer draft", candidate["narrative_markdown"])

    def test_reasoning_effort_change_invalidates_article_reuse(self) -> None:
        """Design source: AGENTS.md; provider configuration changes cannot silently reuse a paid draft."""

        article = articles.ARTICLES[0]
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / article.output_filename
            output_path.write_text("# Existing article\n\nA grounded draft.\n", encoding="utf-8")
            reporter = operator.persona_metadata({}, article.key)
            previous = {
                "status": "generated",
                "evidence_fingerprint": "evidence-1",
                "content_hash": operator._content_hash(output_path),
                "reporter_id": reporter["persona_id"],
                "writer_mode": "automatic_llm",
                "model": "gpt-5.6-luna",
                "source": {
                    "editor_mode": "deterministic",
                    "llm": {"reasoning_effort": "max"},
                },
            }

            self.assertTrue(
                operator._can_reuse_article(
                    previous, output_path, "evidence-1", reporter, "gpt-5.6-luna", "deterministic", "max"
                )
            )
            self.assertFalse(
                operator._can_reuse_article(
                    previous, output_path, "evidence-1", reporter, "gpt-5.6-luna", "deterministic", "low"
                )
            )

    def test_article_reasoning_effort_override_is_scoped_and_bounded(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; desks may tune cost/latency without changing the global Luna default."""

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(operator.article_reasoning_effort("market_watch"), "max")
        with patch.dict(
            os.environ,
            {"FRONT_OFFICE_LLM_REASONING_EFFORT_MARKET_WATCH": "low"},
            clear=True,
        ):
            self.assertEqual(operator.article_reasoning_effort("market_watch"), "low")
        with patch.dict(
            os.environ,
            {"FRONT_OFFICE_LLM_REASONING_EFFORT_MARKET_WATCH": "not-a-real-effort"},
            clear=True,
        ):
            self.assertEqual(operator.article_reasoning_effort("market_watch", "medium"), "medium")

    def test_generation_plan_exposes_the_selected_desk_effort(self) -> None:
        """Design source: AGENTS.md; the cost gate must expose the same desk settings used by generation."""

        article = articles.Article(
            key="market_watch",
            title="Market Watch",
            prompt_filename="market_watch.md",
            headers=("## Buy-Low Targets",),
            scope=lambda _ctx: [{"evidence_id": "player:p1:1", "source_trace": "source:p1"}],
            section="Market",
        )
        with tempfile.TemporaryDirectory() as tmp, patch.object(operator, "ANALYSIS_DIR", Path(tmp)), patch.object(
            articles, "ARTICLES", (article,)
        ), patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "configured-for-plan-only",
                "FRONT_OFFICE_LLM_REASONING_EFFORT": "max",
                "FRONT_OFFICE_LLM_REASONING_EFFORT_MARKET_WATCH": "low",
            },
            clear=True,
        ):
            plan = operator.plan_articles_workflow()

        self.assertEqual(plan["state"], "ready")
        self.assertEqual(plan["articles"]["market_watch"]["reasoning_effort"], "low")
        self.assertEqual(plan["articles"]["market_watch"]["decision"], "generate")

    def test_edition_execution_receipt_persists_job_timing_without_prompt_payload(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; execution telemetry is separate from the frozen evidence packet."""
        from app import db

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "front-office.db"
            analysis = root / "analysis"
            analysis.mkdir()
            with patch.object(db, "DB_PATH", database_path), patch.object(operator, "ANALYSIS_DIR", analysis):
                db.init_db()
                user = db.get_or_create_user("execution-receipt-user")
                run = db.start_edition_run(
                    int(user["id"]),
                    "receipt-league",
                    "2026",
                    roster_id=2,
                    article_keys=["team_report"],
                )
                db.start_edition_job(
                    run["run_id"],
                    "team_report",
                    provider="openai",
                    model="gpt-5.6-luna",
                    reasoning_effort="max",
                    evidence_fingerprint="packet-1",
                )
                db.finish_edition_job(
                    run["run_id"],
                    "team_report",
                    state="published",
                    provider_request_id="req-safe-1",
                    usage={"total_tokens": 123},
                    metadata={
                        "elapsed_ms": 456,
                        "processing_ms": 321,
                        "cached_tokens": 8,
                        "prompt_cache_key": "fd:cache-bucket",
                    },
                )
                receipt = operator.write_edition_execution_receipt(run["run_id"])

            self.assertEqual(receipt["schema_version"], operator.EDITION_EXECUTION_RECEIPT_SCHEMA_VERSION)
            self.assertEqual(receipt["jobs"][0]["duration_ms"], 456)
            self.assertEqual(receipt["jobs"][0]["cached_tokens"], 8)
            self.assertTrue(receipt["jobs"][0]["prompt_cache_key_present"])
            self.assertEqual(receipt["jobs"][0]["usage"]["total_tokens"], 123)
            receipt_text = json.dumps(receipt).lower()
            self.assertNotIn("system_prompt", receipt_text)
            self.assertNotIn("prompt_text", receipt_text)
            self.assertTrue((analysis / "edition_receipt.json").is_file())

    def test_start_job_returns_the_durable_run_receipt(self) -> None:
        """Design source: AGENTS.md; an accepted paid action must be bound to a persisted receipt."""

        with tempfile.TemporaryDirectory() as tmp:
            status_dir = Path(tmp) / "operator" / "status"
            status_path = status_dir / "operator_status.json"

            class InlineThread:
                def __init__(self, target: object, args: tuple[object, ...], daemon: bool) -> None:
                    del daemon
                    self.target = target
                    self.args = args

                def start(self) -> None:
                    self.target(*self.args)

            with patch.object(operator, "STATUS_PATH", status_path), patch.object(
                operator, "OPERATOR_STATUS_DIR", status_dir
            ), patch.object(operator, "_ACTIVE_JOB", False), patch.object(
                operator.threading, "Thread", InlineThread
            ):
                response = operator.start_job(
                    "generate-insights",
                    lambda: {"state": "complete", "message": "Writer complete."},
                )
                receipt = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertTrue(response["accepted"])
            self.assertTrue(response["run_id"])
            self.assertEqual(response["run_id"], receipt["run_id"])
            self.assertEqual(receipt["state"], "complete")

    def test_edition_ledger_preserves_attempts_and_safe_provider_telemetry(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; a paid desk run must be inspectable after interruption or retry."""

        from app import db

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(db, "DB_PATH", Path(tmp) / "app.db"):
                db.init_db()
                user = db.get_or_create_user("clerk-newsroom")
                run = db.start_edition_run(
                    int(user["id"]),
                    "league-1",
                    "2026",
                    roster_id=4,
                    operator_run_id="operator-1",
                    article_keys=["market_watch"],
                )
                db.start_edition_job(
                    run["run_id"],
                    "market_watch",
                    phase="writer",
                    provider="openai",
                    model="gpt-5.6-luna",
                    reasoning_effort="max",
                    evidence_fingerprint="evidence-1",
                )
                retry = db.start_edition_job(
                    run["run_id"],
                    "market_watch",
                    phase="writer",
                    provider="openai",
                    model="gpt-5.6-luna",
                    reasoning_effort="max",
                    evidence_fingerprint="evidence-1",
                )
                db.finish_edition_job(
                    run["run_id"],
                    "market_watch",
                    state="published",
                    provider_request_id="req_123",
                    usage={"input_tokens": 12, "output_tokens": 8},
                    metadata={"attempts": 2, "elapsed_ms": 431},
                )
                db.update_edition_run(
                    run["run_id"],
                    stage="complete",
                    state="complete",
                    completed_count=1,
                    total_count=1,
                    complete=True,
                )
                db.replace_publication_edges(
                    run["run_id"],
                    [{
                        "source_article_key": "team_report",
                        "target_article_key": "market_watch",
                        "relationship": "disputes",
                        "summary": "The price desk tests the roster read.",
                        "source_evidence_ids": ["player:1:1"],
                    }],
                )
                receipt = db.latest_edition_run(int(user["id"]), "league-1")

            self.assertEqual(receipt["state"], "complete")
            self.assertEqual(receipt["roster_id"], 4)
            self.assertEqual(receipt["jobs"][0]["state"], "published")
            self.assertEqual(retry["attempt"], 2)
            self.assertEqual(receipt["jobs"][0]["provider_request_id"], "req_123")
            self.assertEqual(receipt["jobs"][0]["usage"]["output_tokens"], 8)
            self.assertEqual(receipt["jobs"][0]["metadata"]["attempts"], 2)
            self.assertEqual(receipt["publication_edges"][0]["relationship"], "disputes")
            self.assertEqual(receipt["publication_edges"][0]["source_evidence_ids"], ["player:1:1"])

    def test_newsroom_conversation_orders_distinct_lenses_without_merging_claims(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; the page is a conversation of lenses, not six copies of one article."""

        conversation = _newsroom_conversation(
            [
                {
                    "key": "daily_brief",
                    "title": "Daily GM Brief",
                    "body": "brief",
                    "reporter_name": "Look-Ahead Lonnie",
                    "conversation_order": 6,
                    "conversation_relation": "closes the loop",
                    "conversation_caption": "the flagship synthesis",
                    "structured": {"headline": "The late read", "thesis": "Connect the desks."},
                },
                {
                    "key": "team_report",
                    "title": "Your Team Report",
                    "body": "team",
                    "reporter_name": "Topline Tony",
                    "conversation_order": 1,
                    "conversation_relation": "opens the room",
                    "conversation_caption": "what changed around your roster",
                    "structured": {"headline": "Pressure point", "thesis": "Start with the roster."},
                },
            ]
        )

        self.assertEqual([item["article_key"] for item in conversation], ["team_report", "daily_brief"])
        self.assertEqual(conversation[0]["relation"], "opens the room")
        self.assertEqual(conversation[1]["previous_article_key"], "team_report")
        self.assertEqual(conversation[1]["thesis"], "Connect the desks.")

        edges = _newsroom_edges(conversation)
        self.assertEqual(edges[0]["source_article_key"], "team_report")
        self.assertEqual(edges[0]["target_article_key"], "daily_brief")
        self.assertEqual(edges[0]["relationship"], "extends")

    def test_newsroom_edges_reject_a_reply_to_a_future_or_unknown_desk(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; editorial edges cannot fabricate a conversation target."""
        edges = _newsroom_edges(
            [
                {
                    "article_key": "team_report",
                    "reporter_name": "Topline Tony",
                    "reply_to": "trade_desk",
                    "room_move": "disputes",
                    "publication_status": "approved",
                    "evidence_ids": ["player:1:1"],
                },
                {
                    "article_key": "trade_desk",
                    "reporter_name": "Trade Desk Talia",
                    "reply_to": "team_report",
                    "room_move": "asks",
                    "publication_status": "approved",
                    "evidence_ids": ["manager:2:1"],
                },
            ]
        )
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source_article_key"], "team_report")
        self.assertEqual(edges[0]["target_article_key"], "trade_desk")
        self.assertEqual(edges[0]["relationship"], "asks")

    def test_resume_selects_only_unfinished_desks_from_the_durable_ledger(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; a resume must not re-spend completed desk calls."""

        run = {
            "requested_article_keys": ["team_report", "market_watch", "daily_brief"],
            "jobs": [
                {"article_key": "team_report", "phase": "writer", "state": "published"},
                {"article_key": "market_watch", "phase": "writer", "state": "interrupted"},
                {"article_key": "daily_brief", "phase": "writer", "state": "failed"},
            ],
        }

        self.assertEqual(
            operator.edition_resume_article_keys(run),
            {"market_watch", "daily_brief"},
        )

    def test_long_view_runs_before_the_front_page_synthesis(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; synthesis must receive the long-view desk's evidence."""

        ordered_keys = [
            article.key
            for article in sorted(articles.ARTICLES, key=operator._article_execution_sort_key)
        ]

        self.assertLess(ordered_keys.index("horizon_watch"), ordered_keys.index("daily_brief"))

    def test_outer_job_failure_preserves_the_last_writer_checkpoint(self) -> None:
        """Design source: AGENTS.md; a wrapper failure must not erase per-desk progress."""

        with tempfile.TemporaryDirectory() as tmp:
            status_dir = Path(tmp) / "operator" / "status"
            status_path = status_dir / "operator_status.json"

            with patch.object(operator, "STATUS_PATH", status_path), patch.object(
                operator, "OPERATOR_STATUS_DIR", status_dir
            ), patch.object(operator, "_ACTIVE_JOB", True):
                operator._write_writer_progress(
                    {"team_report": {"state": "complete", "message": "Team Report written."}},
                    current_article=articles.ARTICLES[1],
                    completed_count=1,
                    total_count=6,
                    model="gpt-5.6-luna",
                    reasoning_effort="max",
                    editor_mode="deterministic",
                )

                def fail_after_checkpoint() -> dict[str, object]:
                    raise RuntimeError("bundle rebuild unavailable")

                operator._run_job("generate-insights", fail_after_checkpoint)
                receipt = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertEqual(receipt["state"], "failed")
            self.assertEqual(receipt["stage"], "failed")
            self.assertEqual(receipt["last_stage"], "writing")
            self.assertEqual(receipt["completed_count"], 1)
            self.assertEqual(receipt["total_count"], 6)
            self.assertIn("team_report", receipt["articles"])
            self.assertEqual(receipt["error_type"], "RuntimeError")

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

    def test_article_boundary_review_distinguishes_clear_and_limited_availability(self) -> None:
        """Design source: docs/data_contract.md; a healthy marker is not an injury observation."""
        healthy = articles._evidence(
            "player",
            "healthy-1",
            1,
            "Healthy Player",
            "Current production context.",
            source_trace="source:stats",
            injury_status="Active",
            availability_note="No current Sleeper injury flag; baseline projection",
        )
        questionable = articles._evidence(
            "player",
            "questionable-1",
            2,
            "Questionable Player",
            "Current production context.",
            source_trace="source:stats",
            injury_status="Questionable (knee)",
            availability_note="Questionable (knee); baseline projection does not adjust for availability",
        )
        healthy_check = operator._review_evidence_boundaries(
            "## Read\nHealthy Player's rest-of-season projection is 16 PPG.",
            [healthy],
        )
        questionable_check = operator._review_evidence_boundaries(
            "## Read\nQuestionable Player's rest-of-season projection is 16 PPG.",
            [questionable],
        )

        self.assertEqual(healthy_check["injury_baseline_warnings"], 0)
        self.assertEqual(questionable_check["injury_baseline_warnings"], 1)

    def test_reality_check_holds_actionable_high_risk_market_claim(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; no-team signals cannot print as actions."""
        evidence = [
            {
                "evidence_id": "player:hill:1",
                "entity_id": "hill",
                "player_name": "Tyreek Hill",
                "source_ids": ["market:values"],
            }
        ]
        packet = {
            "schema_version": "reality_check_v2",
            "checks": [
                {
                    "check_id": "availability.no_current_nfl_team",
                    "severity": "high",
                    "entity_id": "hill",
                    "entity_name": "Tyreek Hill",
                    "title": "No current NFL team",
                    "detail": "Current-role claims are unavailable until a team and role are confirmed.",
                    "scope": "league_actionable_player_universe",
                    "evidence_ids": ["reality:market:hill"],
                }
            ],
        }
        bad = operator.validate_article_output(
            {
                "narrative_markdown": "## Read\nTyreek Hill is a buy target projected for 15 PPG.",
                "action": "Target him now.",
                "cited_evidence_ids": ["player:hill:1"],
            },
            {"player:hill:1"},
            ("## Read",),
            evidence,
            reality_check_packet=packet,
            article_key="market_watch",
        )
        self.assertFalse(bad["valid"])
        self.assertEqual(bad["reality_check"]["publication_gate"], "hold")
        self.assertTrue(any("Reality Check" in error for error in bad["errors"]))

        safe = operator.validate_article_output(
            {
                "narrative_markdown": "## Read\nTyreek Hill has no current NFL team; the historical 15 PPG baseline is conditional if signed, so this is not a current buy signal.",
                "cited_evidence_ids": ["player:hill:1"],
            },
            {"player:hill:1"},
            ("## Read",),
            evidence,
            reality_check_packet=packet,
            article_key="market_watch",
        )
        self.assertTrue(safe["valid"], safe["errors"])
        self.assertEqual(safe["reality_check"]["publication_gate"], "warning")
        self.assertEqual(len(safe["reality_check"]["matched_checks"]), 1)

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

    def test_claim_register_fails_closed_when_a_position_cites_uncited_evidence(self) -> None:
        """Design source: AGENTS.md; structured positions cannot outrun the article evidence receipt."""
        result = operator.validate_article_output(
            {
                "narrative_markdown": "## Cornerstones\nA grounded read.",
                "cited_evidence_ids": ["player:p1:1"],
                "claim_positions": [{
                    "subject_key": "p1",
                    "subject_label": "Player One",
                    "decision_window": "dynasty",
                    "stance": "positive",
                    "summary": "The long view is supported.",
                    "evidence_ids": ["player:p1:2"],
                }],
            },
            {"player:p1:1", "player:p1:2"},
            ("## Cornerstones",),
            [{"evidence_id": "player:p1:1", "player_id": "p1", "player_name": "Player One"},
             {"evidence_id": "player:p1:2", "player_id": "p1", "player_name": "Player One"}],
        )
        self.assertFalse(result["valid"])
        self.assertFalse(result["claim_position_checks"]["valid"])
        self.assertTrue(any("not included in cited_evidence_ids" in error for error in result["errors"]))
    def test_default_writer_is_luna(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = configured_llm()

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model, "gpt-5.6-luna")
        self.assertEqual(config.reasoning_effort, "max")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")

    def test_writer_timeout_is_visible_and_bounded(self) -> None:
        """Design source: production_runbook.md; slow Luna calls need a bounded explicit timeout."""

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 120)
        with patch.dict(os.environ, {"FRONT_OFFICE_LLM_TIMEOUT_SECONDS": "15"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 30)
        with patch.dict(os.environ, {"FRONT_OFFICE_LLM_TIMEOUT_SECONDS": "999"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 300)
        with patch.dict(os.environ, {"FRONT_OFFICE_LLM_TIMEOUT_SECONDS": "not-a-number"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 120)

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
            ],
            "usage": {
                "input_tokens": 20,
                "input_tokens_details": {"cached_tokens": 8},
                "output_tokens": 5,
            },
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
                reasoning_effort="low",
                prompt_cache_key="fd:cache-bucket",
                safety_identifier="fd:safety-bucket",
                request_post=post,
            )

        self.assertEqual(result["narrative_markdown"], "ok")
        self.assertEqual(result["_provider_receipt"]["reasoning_effort"], "low")
        self.assertEqual(result["_provider_receipt"]["cached_tokens"], 8)
        self.assertEqual(result["_provider_receipt"]["prompt_cache_key"], "fd:cache-bucket")
        request = post.call_args.kwargs
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(request["json"]["reasoning"], {"effort": "low"})
        self.assertEqual(request["json"]["prompt_cache_key"], "fd:cache-bucket")
        self.assertEqual(request["json"]["prompt_cache_options"], {"mode": "implicit", "ttl": "30m"})
        self.assertEqual(request["json"]["safety_identifier"], "fd:safety-bucket")
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
        self.assertIn("Information contract", persona_prompt_block({}, "trade_desk"))
        self.assertIn("Primary question", persona_prompt_block({}, "trade_desk"))
        self.assertIn("counterparty needs", persona_prompt_block({}, "trade_desk"))
        self.assertIn("Required counter-signal", persona_prompt_block({}, "manager_intel"))

    def test_active_reporters_have_distinct_information_contracts(self) -> None:
        """Design source: docs/durable_newsroom_epic.md; a new byline must own a different question and evidence slice."""
        lineup = reporter_lineup({})
        self.assertEqual(len({item["question"] for item in lineup}), len(lineup))
        self.assertEqual(len({item["primary_evidence"] for item in lineup}), len(lineup))
        self.assertTrue(all(item["excluded_evidence"] and item["required_disagreement"] for item in lineup))


if __name__ == "__main__":
    unittest.main()
