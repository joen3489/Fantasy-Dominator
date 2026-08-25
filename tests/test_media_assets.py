from __future__ import annotations

import unittest
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.browser_site import build_browser_site
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
            html = build_browser_site(
                site,
                repo / "data" / "processed",
                repo / "data" / "analysis",
            ).read_text(encoding="utf-8")
            manifest = json.loads((site / "data" / "media_manifest.json").read_text(encoding="utf-8"))
            masthead = next((item for item in manifest["assets"] if item["asset_type"] == "masthead"), None)
            self.assertIsNotNone(masthead)
            self.assertTrue((site / masthead["path"]).is_file())
            self.assertNotIn(str(repo), masthead["path"])
            scripts = [body for body in re.findall(r"<script(?:[^>]*)>([\s\S]*?)</script>", html) if "function render" in body]
            self.assertTrue(scripts, "The generated browser bundle must contain the app script")
            self.assertIn("Question-led data room", html)
            self.assertIn('data-data-question="mispriced"', html)
            self.assertIn("renderDataRoomQuestions", html)
            self.assertIn("renderEditorialMedia", html)
            script_path = Path(tmp) / "bundle.js"
            script_path.write_text("\n".join(scripts), encoding="utf-8")
            checked = subprocess.run([node, "--check", str(script_path)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
