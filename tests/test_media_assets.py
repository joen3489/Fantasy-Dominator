from __future__ import annotations

import unittest
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from src.browser_site import build_browser_site, rebuild_browser_shell
from src.media_assets import asset_is_current, build_media_manifest, materialize_media_assets


class MediaAssetContractTests(unittest.TestCase):
    def test_manifest_scopes_assets_and_is_explicit_about_provenance(self) -> None:
        """Encodes docs/front_office_realization_epic.md Workstream 8 and AGENTS.md media rules."""
        manifest = build_media_manifest(
            [
                {
                    "asset_id": "masthead-v1",
                    "asset_type": "masthead",
                    "purpose": "Front Office identity",
                    "article_key": "daily_brief",
                    "prompt": "abstract football war room, no text",
                    "alt_text": "Abstract green and gold football war room illustration",
                    "status": "published",
                }
            ],
            user_id=17,
            league_id="league-1",
            bundle_revision="rev-1",
        )

        asset = manifest["assets"][0]
        self.assertEqual(manifest["schema_version"], "media_manifest_v1")
        self.assertEqual(asset["user_id"], "17")
        self.assertEqual(asset["league_id"], "league-1")
        self.assertTrue(asset["prompt_hash"])
        self.assertIn("no text", "abstract football war room, no text")
        self.assertTrue(asset["alt_text"])
        self.assertEqual(asset["variants"], [])

    def test_unchanged_asset_can_be_reused_but_scope_or_prompt_change_cannot(self) -> None:
        """Encodes the epic's cost-control rule: unchanged scoped art is reusable."""
        current = build_media_manifest(
            [{"asset_id": "section-v1", "article_key": "trade_desk", "prompt": "market illustration", "status": "published"}],
            user_id=17,
            league_id="league-1",
        )["assets"][0]
        self.assertTrue(asset_is_current(current, current))
        changed = dict(current, prompt_hash="changed")
        self.assertFalse(asset_is_current(current, changed))
        other_league = dict(current, league_id="league-2")
        self.assertFalse(asset_is_current(current, other_league))
        changed_variant = dict(current, variants=[{"key": "mobile", "media": "(max-width: 620px)", "content_hash": "new"}])
        self.assertFalse(asset_is_current(current, changed_variant))

    def test_variants_are_materialized_and_remain_site_relative(self) -> None:
        """Encodes Workstream 8 responsive variants and the no-source-path bundle rule."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop.png"
            mobile = root / "mobile.png"
            desktop.write_bytes(b"desktop-image")
            mobile.write_bytes(b"mobile-image")
            site = root / "site"
            items = materialize_media_assets(
                site,
                [{
                    "asset_id": "masthead",
                    "path": str(desktop),
                    "status": "published",
                    "variants": [{"key": "mobile", "media": "(max-width: 620px)", "path": str(mobile), "status": "published"}],
                }],
            )
            manifest = build_media_manifest(items, league_id="league-1")
            asset = manifest["assets"][0]
            variant = asset["variants"][0]
            self.assertTrue((site / asset["path"]).is_file())
            self.assertTrue((site / variant["path"]).is_file())
            self.assertEqual(variant["key"], "mobile")
            self.assertEqual(variant["media"], "(max-width: 620px)")
            self.assertNotIn(str(root), variant["path"])
            self.assertTrue(variant["content_hash"])

    def test_materialization_exposes_only_a_site_relative_asset_path(self) -> None:
        """Encodes the media rule: source paths never enter a browser bundle."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            source.write_bytes(b"test-image")
            site = root / "site"
            items = materialize_media_assets(
                site,
                [{"asset_id": "masthead v1", "path": str(source), "status": "published"}],
            )
            manifest = build_media_manifest(items, league_id="league-1")
            self.assertTrue((site / items[0]["path"]).is_file())
            self.assertNotIn(str(root), manifest["assets"][0]["path"])
            self.assertTrue(manifest["assets"][0]["content_hash"])

    def test_generated_browser_javascript_parses_as_javascript(self) -> None:
        """Encodes the anti-recursive audit's requirement for a real browser-bundle gate."""
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not installed in this verification environment")
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "release-test"}, clear=False):
                html = build_browser_site(
                    site,
                    repo / "data" / "processed",
                    repo / "data" / "analysis",
                ).read_text(encoding="utf-8")
            manifest = json.loads((site / "data" / "media_manifest.json").read_text(encoding="utf-8"))
            root_manifest = json.loads((site / "data" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(root_manifest["sourceRevision"], "release-test")
            masthead = next((item for item in manifest["assets"] if item["asset_type"] == "masthead"), None)
            self.assertIsNotNone(masthead)
            self.assertTrue((site / masthead["path"]).is_file())
            self.assertNotIn(str(repo), masthead["path"])
            self.assertEqual(masthead["variants"][0]["key"], "mobile")
            self.assertTrue((site / masthead["variants"][0]["path"]).is_file())
            scripts = [body for body in re.findall(r"<script(?:[^>]*)>([\s\S]*?)</script>", html) if "function render" in body]
            self.assertTrue(scripts, "The generated browser bundle must contain the app script")
            self.assertIn("Question-led data room", html)
            self.assertIn('data-data-question="mispriced"', html)
            self.assertIn("renderDataRoomQuestions", html)
            self.assertIn("renderEditorialMedia", html)
            self.assertIn("<picture", html)
            self.assertIn("fetchpriority", html)
            self.assertIn("responsive variant", html)
            self.assertIn("media-ledger", html)
            self.assertIn("data-outcome-select", html)
            self.assertIn("explicit_article_outcome", html)
            self.assertIn("Decision ledger", html)
            self.assertIn("learning-summary", html)
            self.assertIn("Since the last edition", html)
            self.assertIn("edition-changes", html)
            self.assertIn("Evidence IDs:", html)
            self.assertIn("Open the Data Room", html)
            self.assertIn("deterministic fallback publication", html)
            self.assertIn("cost receipt available", html)
            self.assertEqual(html.count('id="issue-publication"'), 1)
            self.assertIn('id="issue-publication-receipt"', html)
            duplicate_ids = [key for key, count in Counter(re.findall(r'id="([^"]+)"', html)).items() if count > 1]
            self.assertEqual(duplicate_ids, [], f"generated browser ids must be unique: {duplicate_ids}")
            script_path = Path(tmp) / "bundle.js"
            script_path.write_text("\n".join(scripts), encoding="utf-8")
            checked = subprocess.run([node, "--check", str(script_path)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_preserved_bundle_can_rebuild_shell_without_processed_csvs(self) -> None:
        """Encodes the deployment artifact lesson: source fixes do not require a costly data refresh."""
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            data = site / "data"
            data.mkdir(parents=True)
            (data / "manifest.json").write_text(
                json.dumps({"appName": "The Front Office", "sourceRevision": "old-release"}),
                encoding="utf-8",
            )
            (data / "app_bundle.json").write_text(
                json.dumps({
                    "myTeamName": "Lulu's Potatoes",
                    "identityReceipt": {"team_name": "Lulu's Potatoes"},
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "new-release"}, clear=False):
                shell = rebuild_browser_shell(site)

            self.assertEqual(json.loads((data / "manifest.json").read_text(encoding="utf-8"))["sourceRevision"], "new-release")
            html = shell.read_text(encoding="utf-8")
            self.assertEqual(html.count('id="issue-publication"'), 1)
            self.assertIn('id="issue-publication-receipt"', html)
            rebuilt_manifest = json.loads((data / "media_manifest.json").read_text(encoding="utf-8"))
            rebuilt_masthead = next(item for item in rebuilt_manifest["assets"] if item["asset_type"] == "masthead")
            self.assertEqual(rebuilt_masthead["variants"][0]["key"], "mobile")
            self.assertTrue((site / rebuilt_masthead["variants"][0]["path"]).is_file())

    def test_shell_rebuild_migrates_legacy_fallback_receipts(self) -> None:
        """Encodes docs/decision_log.md's rule that fallback receipts survive shell-only deploys."""
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "new-release"}, clear=False):
                build_browser_site(
                    site,
                    repo / "data" / "processed",
                    repo / "data" / "analysis",
                )

            app_path = site / "data" / "app_bundle.json"
            manifest_path = site / "data" / "manifest.json"
            app_payload = json.loads(app_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            fields = {
                "daily_brief": ("dailyGmBrief", "daily_gm_brief.md"),
                "team_report": ("teamReport", "team_report.md"),
                "market_watch": ("marketWatch", "market_watch.md"),
                "trade_desk": ("tradeDeskRead", "trade_desk.md"),
                "manager_intel": ("managerIntel", "manager_intel.md"),
            }
            for key, (body_field, _filename) in fields.items():
                body = str(app_payload["analysis"][body_field])
                app_payload["analysis"][body_field] = "\n".join(
                    line
                    for line in body.splitlines()
                    if not any(line.startswith(f"{field}:") for field in (
                        "reporter_name",
                        "evidence_fingerprint",
                        "fallback_reason",
                        "article_payload_json",
                        "source_receipt_json",
                    ))
                ) + "\n"
                app_payload["analysis"]["articleReceipts"][key] = {
                    "mode": "deterministic_template",
                    "reporter_id": manifest["articleReceipts"][key]["reporter_id"],
                    "structured": {},
                }
            manifest["sourceRevision"] = "old-release"
            app_path.write_text(json.dumps(app_payload), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "new-release"}, clear=False):
                rebuild_browser_shell(site)

            rebuilt_app = json.loads(app_path.read_text(encoding="utf-8"))
            rebuilt_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rebuilt_editorial = json.loads((site / "data" / "editorial_issue.json").read_text(encoding="utf-8"))
            for key in fields:
                receipt = rebuilt_manifest["articleReceipts"][key]
                self.assertTrue(receipt["evidence_fingerprint"])
                self.assertTrue(receipt["fallback_reason"])
                self.assertTrue(receipt["structured"])
                self.assertTrue(receipt["source_receipt"])
            self.assertEqual(rebuilt_manifest["sourceRevision"], "new-release")
            self.assertEqual(len(rebuilt_editorial["publication_articles"]), 5)
            self.assertTrue(all(article["fallback_reason"] for article in rebuilt_editorial["publication_articles"]))
            first_bundle_revision = rebuilt_manifest["bundleRevision"]
            with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "new-release"}, clear=False):
                rebuild_browser_shell(site)
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["bundleRevision"],
                first_bundle_revision,
            )


if __name__ == "__main__":
    unittest.main()
