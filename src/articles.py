"""Per-section article registry for the LLM content workflow (Sprint 17).

Each article is one focused LLM call: its own editable prompt file (prompts/{key}.md),
its own scoped evidence (only the data that article needs, drawn from the deterministic
analysis artifacts already written by refresh), and its own output markdown file
(analysis/{key}.md). One article failing never touches the others, and each falls back to
its deterministic version. This replaces the single "generate 10-20 cards in one call"
approach that kept truncating and failing all-or-nothing.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .utils import PROCESSED_DIR, PROJECT_ROOT, load_config

PROMPTS_DIR = PROJECT_ROOT / "prompts"


@dataclass
class ArticleContext:
    """Everything a scope function may need to select its evidence."""

    analysis_dir: Path
    active_roster_id: int | None
    section_outputs: dict[str, str] = field(default_factory=dict)


@dataclass
class Article:
    key: str
    title: str
    prompt_filename: str
    headers: tuple[str, ...]
    scope: Callable[[ArticleContext], list[dict[str, Any]]]
    section: str
    is_summary: bool = False

    @property
    def output_filename(self) -> str:
        # The daily brief keeps its long-standing filename so it stays byte-compatible with the
        # existing deterministic builder, browser bundle field, and Sprint 16 badge wiring.
        return "daily_gm_brief.md" if self.key == "daily_brief" else f"{self.key}.md"


def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8").strip()


def resolve_active_roster_id(config: dict[str, Any] | None = None) -> int | None:
    config = config if config is not None else _safe_config()
    current = config.get("current_team") or {}
    roster_id = current.get("roster_id")
    try:
        return int(roster_id) if roster_id is not None else None
    except (TypeError, ValueError):
        return None


# --- evidence helpers -------------------------------------------------------------------

def _load_processed_csv(filename: str) -> list[dict[str, Any]]:
    path = PROCESSED_DIR / filename
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _load_items(analysis_dir: Path, filename: str) -> list[dict[str, Any]]:
    path = analysis_dir / filename
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _evidence(entity_type: str, entity_id: Any, index: int, name: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "evidence_id": f"{entity_type}:{entity_id}:{index}",
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "name": name,
        "text": text,
        **{key: value for key, value in extra.items() if value not in (None, "")},
    }


# --- scope functions --------------------------------------------------------------------

def _scope_team_report(ctx: ArticleContext) -> list[dict[str, Any]]:
    # The player_dossiers.json artifact is only the top ~120 players by team name, which usually
    # excludes the user's own roster -- so a team report reads the full player_dossiers.csv and
    # filters to the active roster, the one place an article needs the complete per-team data.
    players = _load_processed_csv("player_dossiers.csv")
    if ctx.active_roster_id is not None:
        mine = [row for row in players if _as_int(row.get("roster_id")) == ctx.active_roster_id]
        players = mine or players
    players.sort(key=lambda row: _as_float(row.get("market_value")), reverse=True)
    rows: list[dict[str, Any]] = []
    for index, player in enumerate(players[:25], start=1):
        text = (
            f"{player.get('player_name', 'Unknown')} ({player.get('position', '')}): "
            f"market {player.get('market_value', 'n/a')}, {player.get('projected_ppg', 'n/a')} projected PPG, "
            f"signal {player.get('signal_label', 'none')}, news {player.get('news_impact', 'none') or 'none'}."
        )
        rows.append(
            _evidence(
                "player",
                player.get("player_id", index),
                index,
                str(player.get("player_name", "")),
                text,
                position=player.get("position", ""),
                market_value=player.get("market_value", ""),
                projected_ppg=player.get("projected_ppg", ""),
                signal_label=player.get("signal_label", ""),
            )
        )
    return rows


def _scope_market_watch(ctx: ArticleContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 1
    for filename, side in (("target_theses.json", "buy_low"), ("sell_theses.json", "sell_high")):
        for item in _load_items(ctx.analysis_dir, filename)[:12]:
            rows.append(
                _evidence(
                    "player",
                    item.get("player_id", index),
                    index,
                    str(item.get("player_name", "")),
                    str(item.get("analysis_text", "")),
                    side=side,
                    position=item.get("position", ""),
                    risk=item.get("risk", ""),
                    confidence=item.get("confidence", ""),
                    evidence=item.get("evidence", ""),
                )
            )
            index += 1
    return rows


def _scope_trade_desk(ctx: ArticleContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_load_items(ctx.analysis_dir, "trade_theses.json")[:12], start=1):
        rows.append(
            _evidence(
                "manager",
                item.get("target_manager_roster_id", index),
                index,
                str(item.get("target_manager_name", "")),
                str(item.get("analysis_text", "")),
                approach=item.get("approach_type", ""),
                assets=item.get("assets_to_discuss", ""),
                manager_signal=item.get("manager_signal", ""),
                risk=item.get("risk", ""),
                confidence=item.get("confidence", ""),
                evidence=item.get("evidence", ""),
            )
        )
    return rows


def _scope_manager_intel(ctx: ArticleContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_load_items(ctx.analysis_dir, "manager_dossiers.json")[:14], start=1):
        rows.append(
            _evidence(
                "manager",
                item.get("roster_id", index),
                index,
                str(item.get("team_name", item.get("manager_name", ""))),
                str(item.get("analysis_text", "")),
                dynasty_cycle=item.get("dynasty_cycle", ""),
                confidence=item.get("confidence", ""),
                evidence=item.get("evidence", ""),
            )
        )
    return rows


def _scope_daily_brief(ctx: ArticleContext) -> list[dict[str, Any]]:
    # The daily brief summarizes the section reports, so its evidence is those reports' text
    # (generated moments earlier) plus a thin slice of the top decision items for grounding.
    rows: list[dict[str, Any]] = []
    for index, (key, text) in enumerate(ctx.section_outputs.items(), start=1):
        if text.strip():
            rows.append(_evidence("section", key, index, key.replace("_", " ").title(), text.strip()))
    base = len(rows)
    for filename, entity_type in (("target_theses.json", "player"), ("sell_theses.json", "player"), ("trade_theses.json", "manager")):
        for offset, item in enumerate(_load_items(ctx.analysis_dir, filename)[:5], start=1):
            index = base + offset
            name = item.get("player_name") or item.get("target_manager_name") or ""
            entity_id = item.get("player_id") or item.get("target_manager_roster_id") or index
            rows.append(_evidence(entity_type, entity_id, index, str(name), str(item.get("analysis_text", ""))))
        base = len(rows)
    return rows


ARTICLES: list[Article] = [
    Article("team_report", "Your Team Report", "team_report.md", ("## Cornerstones", "## Shop Candidates"), _scope_team_report, "team-report"),
    Article("market_watch", "Market Watch", "market_watch.md", ("## Buy-Low Targets", "## Sell-High Windows"), _scope_market_watch, "market-watch"),
    Article("trade_desk", "Trade Desk Read", "trade_desk.md", ("## Best Fits", "## Steer Clear"), _scope_trade_desk, "trade-desk-read"),
    Article("manager_intel", "Manager Intel", "manager_intel.md", ("## Contenders", "## Rebuilders"), _scope_manager_intel, "manager-intel"),
    Article("daily_brief", "Daily GM Brief", "daily_brief.md", ("## Target Theses", "## Sell Windows", "## Manager Angles"), _scope_daily_brief, "daily-gm-brief", is_summary=True),
]


def _safe_config() -> dict[str, Any]:
    try:
        return load_config()
    except (OSError, ValueError):
        return {}


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
