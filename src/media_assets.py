"""Small, explicit contract for generated editorial media.

Images are presentation aids, never evidence.  Keeping their receipt separate
from article prose makes it possible to add portraits, section art, or a hero
illustration without coupling image generation to league facts or blocking a
text edition when a media provider is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


MEDIA_MANIFEST_VERSION = "media_manifest_v1"


def materialize_media_assets(
    output_dir: Path,
    assets: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Copy configured artwork into the generated site and return safe receipts.

    Configuration may point at a repository asset or a durable generated file,
    but the browser must only receive a site-relative path. Missing artwork is
    retained as an explicit unavailable receipt so a decorative failure never
    makes the edition look current by accident or blocks the text publication.
    """

    media_dir = output_dir / "media"
    materialized: list[dict[str, Any]] = []
    for raw in assets or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        source_value = str(item.get("path") or "").strip()
        source = Path(source_value) if source_value else None
        asset_id = _safe_asset_name(item.get("asset_id") or "editorial-asset")
        suffix = source.suffix.lower() if source and source.suffix else ".png"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif"}:
            suffix = ".png"
        target = media_dir / f"{asset_id}{suffix}"
        if source and source.is_file():
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                if source.resolve() != target.resolve():
                    shutil.copyfile(source, target)
                item["path"] = f"media/{target.name}"
                item["_materialized_source"] = str(target)
                item["status"] = item.get("status") or "available"
            except OSError:
                item["path"] = ""
                item["_materialized_source"] = ""
                item["status"] = "unavailable"
        else:
            item["path"] = ""
            item["_materialized_source"] = ""
            item["status"] = item.get("status") or "missing"
        materialized.append(item)
    return materialized


def build_media_manifest(
    assets: Sequence[Mapping[str, Any]] | None = None,
    *,
    user_id: str | int | None = None,
    league_id: str = "",
    bundle_revision: str = "",
) -> dict[str, Any]:
    """Normalize media receipts without making a provider call.

    A missing or failed image remains a valid manifest entry with an explicit
    status.  The browser can therefore fall back to typography and data while
    the operator still sees what was attempted and why.
    """
    normalized: list[dict[str, Any]] = []
    for raw in assets or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        path_value = item.get("_materialized_source") or item.get("path")
        path = Path(str(path_value)) if path_value else None
        content_hash = str(item.get("content_hash") or "")
        if path and path.is_file() and not content_hash:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        prompt = str(item.get("prompt") or "")
        normalized.append(
            {
                "asset_id": str(item.get("asset_id") or ""),
                "asset_type": str(item.get("asset_type") or "illustration"),
                "purpose": str(item.get("purpose") or "editorial decoration"),
                "user_id": str(item.get("user_id") or user_id or ""),
                "league_id": str(item.get("league_id") or league_id or ""),
                "article_key": str(item.get("article_key") or ""),
                "bundle_revision": str(item.get("bundle_revision") or bundle_revision or ""),
                "prompt_hash": str(item.get("prompt_hash") or _hash_text(prompt)),
                "model": str(item.get("model") or ""),
                "quality": str(item.get("quality") or ""),
                "size": str(item.get("size") or ""),
                "format": str(item.get("format") or ""),
                "generated_at": str(item.get("generated_at") or ""),
                "content_hash": content_hash,
                "alt_text": str(item.get("alt_text") or "Decorative Front Office artwork"),
                "credit": str(item.get("credit") or "AI-generated editorial artwork"),
                "moderation_status": str(item.get("moderation_status") or "not_run"),
                "status": str(item.get("status") or "available"),
                "path": str(item.get("path") or ""),
            }
        )
    return {
        "schema_version": MEDIA_MANIFEST_VERSION,
        "user_id": str(user_id or ""),
        "league_id": str(league_id or ""),
        "bundle_revision": str(bundle_revision or ""),
        "assets": normalized,
        "asset_count": len(normalized),
    }


def asset_is_current(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> bool:
    """Return whether a published asset can be reused without regeneration."""
    if not previous or str(previous.get("status") or "") not in {"available", "published"}:
        return False
    return all(
        str(previous.get(field) or "") == str(current.get(field) or "")
        for field in ("asset_id", "prompt_hash", "content_hash", "article_key", "league_id")
    )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _safe_asset_name(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "editorial-asset")).strip(".-")
    return cleaned or "editorial-asset"


def media_manifest_json(manifest: Mapping[str, Any]) -> str:
    return json.dumps(dict(manifest), ensure_ascii=False, indent=2).replace("</", "<\\/")
