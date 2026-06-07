from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_EXTERNAL_DIR = DATA_DIR / "raw_external"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = DATA_DIR / "reports"
SITE_DIR = DATA_DIR / "site"
ANALYSIS_DIR = DATA_DIR / "analysis"


def ensure_dirs() -> None:
    for path in (RAW_DIR, RAW_EXTERNAL_DIR, PROCESSED_DIR, CACHE_DIR, REPORTS_DIR, SITE_DIR, ANALYSIS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or CONFIG_DIR / "leagues.yml"
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_dumps(data: Any) -> str:
    if data is None:
        return ""
    return json.dumps(data, sort_keys=True)


def epoch_ms_to_datetime(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def safe_get(mapping: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    return mapping.get(key, default)


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def join_items(items: list[Any]) -> str:
    return "; ".join(str(item) for item in items if item not in (None, ""))
