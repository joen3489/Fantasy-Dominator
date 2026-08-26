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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .availability import baseline_ppg_text
from .horizons import HORIZON_SCORE_BASIS
from .utils import PROCESSED_DIR, PROJECT_ROOT, load_config

PROMPTS_DIR = PROJECT_ROOT / "prompts"


@dataclass
class ArticleContext:
    """Everything a scope function may need to select its evidence."""

    analysis_dir: Path
    active_roster_id: int | None
    section_outputs: dict[str, str] = field(default_factory=dict)
    claimed_players: set[str] = field(default_factory=set)
    claimed_player_source_ids: dict[str, list[str]] = field(default_factory=dict)
    processed_dir: Path = PROCESSED_DIR
    user_id: str | None = None
    league_id: str = ""
    season: str = ""
    team_name: str = ""
    writer_preferences: dict[str, Any] = field(default_factory=dict)


def apply_entity_dedup(ctx: ArticleContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-article player dedup (the Sprint 14 Today's Board philosophy applied to articles):
    the first section article to scope a player claims it; later articles drop that player's
    evidence and instead receive one 'covered elsewhere' context item so the writer knows the
    name exists but should spend its words on players not yet covered. The daily brief is exempt
    by the caller -- it synthesizes the sections by design."""
    fresh: list[dict[str, Any]] = []
    covered: list[str] = []
    covered_source_ids: list[str] = []
    for row in rows:
        if str(row.get("entity_type", "")) == "player":
            key = _normalize_name(row.get("name"))
            raw_sources = (
                row.get("source_ids")
                or row.get("source_trace")
                or row.get("source_id")
                or row.get("source")
            )
            source_ids = _source_ids(raw_sources)
            if key and key in ctx.claimed_players:
                covered.append(str(row.get("name", "")))
                prior_source_ids = ctx.claimed_player_source_ids.get(key, [])
                for source_id in source_ids or prior_source_ids:
                    if source_id not in covered_source_ids:
                        covered_source_ids.append(source_id)
                continue
            if key:
                ctx.claimed_players.add(key)
                ctx.claimed_player_source_ids[key] = source_ids
        fresh.append(row)
    if covered:
        unique_covered = ", ".join(dict.fromkeys(name for name in covered if name))
        fresh.append(
            _evidence(
                "context",
                "covered_elsewhere",
                len(fresh) + 1,
                "Covered elsewhere",
                (
                    f"Already profiled in an earlier section this run: {unique_covered}. "
                    "A passing reference is fine; do not re-profile them -- spend the words on names not yet covered."
                ),
                source_ids=covered_source_ids,
                calculation="Preserved source receipt from the earlier player evidence; this context row is not a new player claim.",
            )
        )
    return fresh


@dataclass
class Article:
    key: str
    title: str
    prompt_filename: str
    headers: tuple[str, ...]
    scope: Callable[[ArticleContext], list[dict[str, Any]]]
    section: str
    is_summary: bool = False
    reporter_id: str = "front_office"

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

def _load_processed_csv(filename: str, processed_dir: Path = PROCESSED_DIR) -> list[dict[str, Any]]:
    path = processed_dir / filename
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
    """Build the canonical evidence packet passed to every writer.

    The packet deliberately keeps the human-readable text, but also records
    what the writer is allowed to interpret: source identity, freshness,
    calculation boundaries, related entity scope, and an explicit quality
    label when the claim rests on one source or no source receipt.
    """

    source_ids = _source_ids(
        extra.get("source_ids")
        or extra.get("source_trace")
        or extra.get("source_id")
        or extra.get("source")
    )
    source_count = extra.get("source_count")
    try:
        source_count = int(source_count) if source_count not in (None, "") else len(source_ids)
    except (TypeError, ValueError):
        source_count = len(source_ids)
    freshness = str(
        extra.get("freshness")
        or extra.get("checked_at")
        or extra.get("generated_at")
        or "unknown"
    )
    confidence = str(extra.get("confidence") or "unknown")
    quality = "multi_source" if source_count > 1 else ("single_source" if source_count == 1 else "unattributed")
    packet = {
        "evidence_id": f"{entity_type}:{entity_id}:{index}",
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "name": name,
        "text": text,
        "claim_candidates": [str(text)] if str(text).strip() else [],
        "supporting_rows": [{
            "row_id": f"{entity_type}:{entity_id}:{index}",
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "name": name,
        }],
        "source_ids": source_ids,
        "source_count": max(0, source_count),
        "source_quality": quality,
        "freshness": freshness,
        "confidence_basis": f"{confidence}; {quality.replace('_', ' ')} evidence",
        "calculation": str(extra.get("calculation") or "Deterministic source row or analysis artifact; no hidden calculation."),
        "permitted_interpretation": [
            "Describe the observed signal and its uncertainty.",
            "Do not infer motive, completed action, or certain future performance.",
        ],
        **{key: value for key, value in extra.items() if value not in (None, "") and key not in {"source_id", "source_ids", "source_trace", "source", "source_count", "freshness", "checked_at", "generated_at"}},
    }
    packet["source_receipt"] = {
        "source_ids": source_ids,
        "source_count": max(0, source_count),
        "freshness": freshness,
        "quality": quality,
    }
    return packet


def _source_ids(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[;,|]", str(value))
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _compact_manager_value(value: Any, depth: int = 0) -> Any:
    """Keep dossier evidence rich enough to reason over without shipping raw history blobs.

    The durable manager dossier remains complete in the data room. The writer packet is a
    bounded editorial context: it carries the manager's aggregates, recent history, and leading
    fits while avoiding a 100k-token repeat of every transaction and counterparty row.
    """
    if isinstance(value, str):
        return value if len(value) <= 300 else value[:297].rstrip() + "..."
    if depth >= 2:
        if isinstance(value, dict):
            return {str(key): _compact_manager_value(item, depth + 1) for key, item in list(value.items())[:6]}
        if isinstance(value, list):
            return [_compact_manager_value(item, depth + 1) for item in value[:3]]
        return value
    if isinstance(value, dict):
        return {str(key): _compact_manager_value(item, depth + 1) for key, item in list(value.items())[:10]}
    if isinstance(value, list):
        return [_compact_manager_value(item, depth + 1) for item in value[:4]]
    return value


# --- scope functions --------------------------------------------------------------------

def _scope_team_report(ctx: ArticleContext) -> list[dict[str, Any]]:
    # The player_dossiers.json artifact is only the top ~120 players by team name, which usually
    # excludes the user's own roster -- so a team report reads the full player_dossiers.csv and
    # filters to the active roster, the one place an article needs the complete per-team data.
    players = _load_processed_csv("player_dossiers.csv", ctx.processed_dir)
    if ctx.active_roster_id is not None:
        roster_rows = _load_processed_csv("roster_players.csv", ctx.processed_dir)
        scoped_roster = _scope_rows(roster_rows, ctx)
        if scoped_roster:
            scoped_player_ids = {
                str(row.get("player_id") or "").strip()
                for row in scoped_roster
                if _as_int(row.get("roster_id")) == ctx.active_roster_id and str(row.get("player_id") or "").strip()
            }
            players = [
                row for row in players
                if scoped_player_ids
                and _as_int(row.get("roster_id")) == ctx.active_roster_id
                and str(row.get("player_id") or "").strip() in scoped_player_ids
            ]
        else:
            # A missing exact roster scope is unavailable. Never substitute a
            # different roster merely because its dossier rows are present.
            players = [
                row for row in players
                if _as_int(row.get("roster_id")) == ctx.active_roster_id
            ] if not roster_rows else []
    players.sort(key=lambda row: _as_float(row.get("market_value")), reverse=True)
    horizon_rows = _load_processed_csv("player_horizon_market_scores.csv", ctx.processed_dir)
    horizon_by_player = {
        (
            str(row.get("player_id")),
            str(row.get("roster_id")),
            str(row.get("league_id") or "").strip(),
        ): row
        for row in horizon_rows
        if str(row.get("player_id") or "")
        and (not ctx.season or not str(row.get("season", "")).strip() or _same_id(row.get("season"), ctx.season))
        and (not ctx.league_id or not str(row.get("league_id") or "").strip() or _same_id(row.get("league_id"), ctx.league_id))
    }
    rows: list[dict[str, Any]] = []
    player_ids = {str(row.get("player_id", "")) for row in players if str(row.get("player_id", ""))}
    for index, player in enumerate(players[:25], start=1):
        horizon = horizon_by_player.get(
            (
                str(player.get("player_id")),
                str(player.get("roster_id")),
                str(ctx.league_id or "").strip(),
            ),
            horizon_by_player.get(
                (str(player.get("player_id")), str(player.get("roster_id")), ""),
                horizon_by_player.get((str(player.get("player_id")), "", ""), {}),
            ),
        )
        text = (
            f"{player.get('player_name', 'Unknown')} ({player.get('position', '')}): "
            f"market {player.get('market_value', 'n/a')}, {baseline_ppg_text(horizon or player, player.get('projected_ppg', 'n/a'))}; "
            "rest-of-season baseline is not recovery-adjusted, and no recovery timeline is modeled beyond the next-game lane; "
            f"availability {player.get('availability_note', 'not recorded')}, "
            f"signal {player.get('signal_label', 'none')}, news {player.get('news_impact', 'none') or 'none'}. "
            f"Four-window model {horizon.get('horizon_model_version', 'unversioned')}: next game {horizon.get('next_game_market_score', 'n/a')} vs {horizon.get('next_game_opponent', 'opponent unavailable')} "
            f"(matchup holdout {horizon.get('next_game_matchup_validation_status', 'unavailable')}; adjustment {horizon.get('next_game_matchup_adjustment_status', 'unavailable')}), "
            f"rest of season {horizon.get('rest_of_season_market_score', 'n/a')}, "
            f"dynasty market {horizon.get('dynasty_market_score', 'n/a')}, five-year career window {horizon.get('career_projection_score', 'n/a')}; "
            f"contender fit {horizon.get('contender_fit_score', 'n/a')}, rebuilder fit {horizon.get('rebuilder_fit_score', 'n/a')}. "
            f"Score basis: {horizon.get('horizon_score_basis') or HORIZON_SCORE_BASIS}. "
            f"Cross-position price anchor: market value {horizon.get('market_value', 'n/a')}."
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
                next_game_market_score=horizon.get("next_game_market_score", ""),
                next_game_baseline_points=horizon.get("next_game_baseline_points", ""),
                next_game_expected_points=horizon.get("next_game_expected_points", ""),
                next_game_opponent=horizon.get("next_game_opponent", ""),
                next_game_matchup_factor=horizon.get("next_game_matchup_factor", ""),
                next_game_matchup_validation_status=horizon.get("next_game_matchup_validation_status", ""),
                next_game_matchup_validation_games=horizon.get("next_game_matchup_validation_games", ""),
                next_game_matchup_validation_mae_delta=horizon.get("next_game_matchup_validation_mae_delta", ""),
                next_game_matchup_adjustment_status=horizon.get("next_game_matchup_adjustment_status", ""),
                rest_of_season_market_score=horizon.get("rest_of_season_market_score", ""),
                rest_of_season_games=horizon.get("rest_of_season_games", ""),
                rest_of_season_bye_weeks=horizon.get("rest_of_season_bye_weeks", ""),
                rest_of_season_baseline_points=horizon.get("rest_of_season_baseline_points", ""),
                rest_of_season_ppg=horizon.get("rest_of_season_ppg", ""),
                rest_of_season_basis=horizon.get("rest_of_season_basis", ""),
                dynasty_market_score=horizon.get("dynasty_market_score", ""),
                career_projection_score=horizon.get("career_projection_score", ""),
                career_projection_status=horizon.get("career_projection_status", ""),
                contender_fit_score=horizon.get("contender_fit_score", ""),
                rebuilder_fit_score=horizon.get("rebuilder_fit_score", ""),
                horizon_model_version=horizon.get("horizon_model_version", ""),
                horizon_score_basis=horizon.get("horizon_score_basis", ""),
                horizon_market_value=horizon.get("market_value", ""),
                horizon_market_percentile=horizon.get("market_percentile", ""),
                fit_basis=horizon.get("fit_basis", ""),
                value_lane=horizon.get("value_lane", ""),
                horizon_status=horizon.get("next_game_status", ""),
                injury_status=horizon.get("injury_status", ""),
                availability_note=horizon.get("availability_note", ""),
                horizon_risk=horizon.get("risk", ""),
                source_trace=player.get("source_trace", ""),
                checked_at=player.get("checked_at", ""),
            )
        )
    # Topline Tony is a league beat reporter, not just a roster valuation formatter. Keep the
    # evidence in this existing article seam so the team-report contract does not fork, while
    # giving the writer the actual news, matchup, and move context behind the read.
    next_index = len(rows) + 1
    news = _load_processed_csv("league_news_impact.csv", ctx.processed_dir)
    if ctx.league_id:
        scoped_news = [row for row in news if _same_id(row.get("league_id"), ctx.league_id)]
        news = scoped_news or [row for row in news if not str(row.get("league_id", "")).strip()]
    news = [
        row for row in news
        if not str(row.get("season", "")).strip() or _same_season(row.get("season"), ctx.season, news)
    ]
    team_news = [row for row in news if str(row.get("player_id", "")) in player_ids]
    league_news = [row for row in news if row not in team_news]
    for scope, news_rows in (("selected_roster", team_news[:8]), ("league_context", league_news[:4])):
        for row in news_rows:
            event_id = str(row.get("event_id") or f"news-{next_index}")
            headline = str(row.get("evidence") or row.get("player_name") or "League news")
            text = (
                f"{headline} Impact={row.get('impact_type', 'unclassified')}; "
                f"risk={row.get('risk', 'not recorded')}; confidence={row.get('confidence', 'not recorded')}."
            )
            rows.append(
                _evidence(
                    "news",
                    event_id,
                    next_index,
                    str(row.get("player_name") or headline),
                    text,
                    scope=scope,
                    league_id=row.get("league_id", ctx.league_id),
                    season=row.get("season", ctx.season),
                    impact_type=row.get("impact_type", ""),
                    related_player_id=row.get("player_id", ""),
                    risk=row.get("risk", ""),
                    confidence=row.get("confidence", ""),
                    source_trace=row.get("source_trace", ""),
                    checked_at=row.get("published_at", ""),
                )
            )
            next_index += 1

    matchups = _load_processed_csv("matchups.csv", ctx.processed_dir)
    matchup_rows = [
        row for row in matchups
        if _as_int(row.get("roster_id")) == ctx.active_roster_id
        and _same_optional_league(row.get("league_id"), ctx.league_id)
        and _same_season(row.get("season"), ctx.season, matchups)
    ]
    for row in sorted(matchup_rows, key=lambda item: (_as_int(item.get("week")) or 0), reverse=True)[:3]:
        result = str(row.get("result") or "not recorded")
        points = f"{row.get('points_for', 'n/a')} for / {row.get('points_against', 'n/a')} against"
        text = (
            f"Week {row.get('week', 'n/a')} vs {row.get('opponent_team_name', 'opponent')}: "
            f"status={result}; {points}; margin={row.get('margin', 'n/a')}."
        )
        rows.append(
            _evidence(
                "matchup",
                f"{row.get('season', '')}:{row.get('week', '')}:{row.get('matchup_id', next_index)}",
                next_index,
                f"Week {row.get('week', 'n/a')} vs {row.get('opponent_team_name', 'opponent')}",
                text,
                opponent_roster_id=row.get("opponent_roster_id", ""),
                league_id=row.get("league_id", ctx.league_id),
                season=row.get("season", ctx.season),
                result=result,
                source_trace=row.get("source_trace", ""),
                checked_at=row.get("season", ""),
            )
        )
        next_index += 1

    # A beat reporter should see what actually moved, but never receive another league's
    # transactions. Trades and waivers remain separate evidence rows so the writer can say
    # "the room moved" without collapsing different event types into a fabricated narrative.
    move_rows: list[tuple[int, str, dict[str, Any]]] = []
    trades = _load_processed_csv("trades.csv", ctx.processed_dir)
    for row in trades:
        if not _same_season(row.get("season"), ctx.season, trades):
            continue
        if not _same_optional_league(row.get("league_id"), ctx.league_id):
            continue
        if _as_int(row.get("team_a_roster_id")) != ctx.active_roster_id and _as_int(row.get("team_b_roster_id")) != ctx.active_roster_id:
            continue
        move_rows.append((_as_int(row.get("week")) or 0, "trade", row))
    waivers = _load_processed_csv("waivers.csv", ctx.processed_dir)
    for row in waivers:
        if not _same_season(row.get("season"), ctx.season, waivers) or _as_int(row.get("roster_id")) != ctx.active_roster_id:
            continue
        if not _same_optional_league(row.get("league_id"), ctx.league_id):
            continue
        move_rows.append((_as_int(row.get("week")) or 0, "waiver", row))
    for _, event_type, row in sorted(move_rows, key=lambda item: item[0], reverse=True)[:6]:
        if event_type == "trade":
            is_a = _as_int(row.get("team_a_roster_id")) == ctx.active_roster_id
            own_prefix, other_prefix = (("team_a", "team_b") if is_a else ("team_b", "team_a"))
            text = (
                f"Trade week {row.get('week', 'n/a')} with {row.get(f'{other_prefix}_name', 'counterparty')}: "
                f"received {row.get(f'{own_prefix}_players_received', '') or 'no players'}; "
                f"picks/FAAB received {row.get(f'{own_prefix}_picks_received', '') or row.get(f'{own_prefix}_faab_received', '') or 'none'}."
            )
            name = f"Trade with {row.get(f'{other_prefix}_name', 'counterparty')}"
        else:
            text = (
                f"Waiver week {row.get('week', 'n/a')}: added {row.get('player_added', '') or 'none'}; "
                f"dropped {row.get('player_dropped', '') or 'none'}; bid={row.get('waiver_bid', 'n/a')}."
            )
            name = f"Waiver week {row.get('week', 'n/a')}"
        rows.append(
            _evidence(
                "transaction",
                row.get("transaction_id", next_index),
                next_index,
                name,
                text,
                event_type=event_type,
                league_id=row.get("league_id", ctx.league_id),
                season=row.get("season", ctx.season),
                source_trace="sleeper:trades" if event_type == "trade" else "sleeper:waivers",
                checked_at=row.get("created_datetime", ""),
            )
        )
        next_index += 1
    return rows


def _same_season(value: Any, requested: Any, rows: list[dict[str, Any]]) -> bool:
    """Keep article evidence in one season, using the freshest available season by default."""

    if requested not in (None, ""):
        return str(value) == str(requested)
    seasons = [str(row.get("season", "")) for row in rows if str(row.get("season", ""))]
    return not seasons or str(value) == max(seasons)


def _scope_rows(rows: list[dict[str, Any]], ctx: ArticleContext) -> list[dict[str, Any]]:
    """Keep article evidence inside the requested league and season.

    Unscoped legacy rows are allowed only when the table has no identified
    rows for that boundary. An identified mismatch is an unavailable join, not
    a license to use another league's or season's content.
    """

    scoped = list(rows)
    for field, requested in (("league_id", ctx.league_id), ("season", ctx.season)):
        if not requested:
            continue
        identified = [row for row in scoped if str(row.get(field) or "").strip()]
        if identified:
            scoped = [
                row for row in identified
                if _same_id(row.get(field), requested)
            ]
        else:
            scoped = [row for row in scoped if not str(row.get(field) or "").strip()]
    return scoped


def _same_id(left: Any, right: Any) -> bool:
    """Compare source IDs safely when CSV round-trips long Sleeper IDs as floats."""

    if left in (None, "") or right in (None, ""):
        return False
    left_text = str(left).strip()
    right_text = str(right).strip()
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except (TypeError, ValueError):
        return False


def _same_optional_league(value: Any, requested: Any) -> bool:
    """Keep legacy/global rows, but reject an explicitly different league."""

    if not requested or not str(value or "").strip():
        return True
    return _same_id(value, requested)


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
                    source_trace=item.get("source_trace", ""),
                    checked_at=item.get("checked_at", ""),
                )
            )
            index += 1
    # A news-market edge is a deterministic bridge between the catalyst and the
    # market lane. It gives the writer a named dislocation to explain without
    # asking the model to invent why a price may be lagging.
    edges = _load_processed_csv("news_market_edges.csv", ctx.processed_dir)
    edges = [
        row for row in edges
        if _same_optional_league(row.get("league_id"), ctx.league_id)
        and (not ctx.season or not str(row.get("season", "")).strip() or _same_id(row.get("season"), ctx.season))
    ]
    edges.sort(key=lambda row: _as_float(row.get("news_market_edge_score")), reverse=True)
    for row in edges[:10]:
        edge_type = str(row.get("edge_type") or "news-market review").replace("_", " ")
        rows.append(
            _evidence(
                "player",
                row.get("player_id", index),
                index,
                str(row.get("player_name", "")),
                (
                    f"{row.get('player_name', 'This player')}: {edge_type}; news={row.get('news_impact', 'unclassified')} "
                    f"across {row.get('news_event_count', 0)} event(s), market={row.get('market_value', 'n/a')}, "
                    f"{baseline_ppg_text(row, row.get('projected_ppg', 'n/a'))}, market gap={row.get('market_gap_score', 0)}, "
                    f"sell score={row.get('sell_score', 0)}. {row.get('evidence', '')}"
                ),
                side=edge_type,
                position=row.get("position", ""),
                news_direction=row.get("news_direction", ""),
                news_impact=row.get("news_impact", ""),
                news_event_count=row.get("news_event_count", ""),
                market_value=row.get("market_value", ""),
                projected_ppg=row.get("projected_ppg", ""),
                risk=row.get("risk", ""),
                confidence=row.get("confidence", ""),
                evidence=row.get("evidence", ""),
                source_trace=row.get("source_trace", ""),
            )
        )
        index += 1
    # Waverly's waiver/market lane is allowed to see only the availability
    # research table, never an unscoped market list.  The table is built by
    # deterministic code, but the writer seam still fails closed: a stale or
    # hand-edited row must not turn another league's rostered player into a
    # waiver suggestion.
    available_rows = _scope_available_market_rows(ctx)
    for row in available_rows:
        lane = str(row.get("value_lane") or "balanced_window").replace("_", " ")
        rows.append(
            _evidence(
                "player",
                row.get("player_id", index),
                index,
                str(row.get("player_name", "")),
                _available_market_text(row, lane),
                availability_scope="available_market_research",
                availability_status=row.get("availability_status", ""),
                identity_status=row.get("identity_status", ""),
                horizon_lane=lane,
                next_game_score=row.get("next_game_market_score", ""),
                next_game_minus_market_delta=row.get("next_game_minus_market_delta", ""),
                rest_of_season_score=row.get("rest_of_season_market_score", ""),
                rest_of_season_minus_market_delta=row.get("rest_of_season_minus_market_delta", ""),
                rest_of_season_minus_next_game_delta=row.get("rest_of_season_minus_next_game_delta", ""),
                dynasty_score=row.get("dynasty_market_score", ""),
                dynasty_minus_market_delta=row.get("dynasty_minus_market_delta", ""),
                dynasty_minus_rest_of_season_delta=row.get("dynasty_minus_rest_of_season_delta", ""),
                career_projection_score=row.get("career_projection_score", ""),
                career_minus_market_delta=row.get("career_minus_market_delta", ""),
                career_minus_dynasty_delta=row.get("career_minus_dynasty_delta", ""),
                career_history_status=row.get("career_history_status", ""),
                career_history_source_player_id=row.get("career_history_source_player_id", ""),
                career_history_join_method=row.get("career_history_join_method", ""),
                career_history_seasons=row.get("career_history_seasons", ""),
                career_history_games=row.get("career_history_games", ""),
                career_history_ppg=row.get("career_history_ppg", ""),
                contender_fit_score=row.get("contender_fit_score", ""),
                rebuilder_fit_score=row.get("rebuilder_fit_score", ""),
                rebuilder_contender_spread=row.get("rebuilder_contender_spread", ""),
                fit_coverage=row.get("fit_coverage", ""),
                horizon_model_version=row.get("horizon_model_version", ""),
                horizon_score_basis=row.get("horizon_score_basis", ""),
                market_value=row.get("market_value", ""),
                market_percentile=row.get("market_percentile", ""),
                market_rank=row.get("market_rank", ""),
                market_source_count=row.get("market_source_count", ""),
                market_source_confidence=row.get("market_source_confidence", ""),
                next_game_opponent=row.get("next_game_opponent", ""),
                next_game_matchup_validation_status=row.get("next_game_matchup_validation_status", ""),
                next_game_matchup_adjustment_status=row.get("next_game_matchup_adjustment_status", ""),
                availability_note=row.get("availability_note", ""),
                risk=row.get("risk", ""),
                confidence=row.get("confidence", ""),
                evidence=row.get("evidence", ""),
                source_trace=row.get("source_trace", ""),
            )
        )
        index += 1
    # The horizon market is deterministic evidence for a writer, not a prompt
    # asking the model to invent a contender/rebuilder split. Keep all four
    # decision windows in one packet so a prose read cannot silently substitute
    # dynasty value for this-week utility.
    horizon_rows = _load_processed_csv("player_horizon_market_scores.csv", ctx.processed_dir)
    horizon_rows = [
        row for row in horizon_rows
        if (not ctx.season or not str(row.get("season", "")).strip() or _same_id(row.get("season"), ctx.season))
    ]
    def market_disagreement_magnitude(row: dict[str, Any]) -> float:
        deltas = [
            _as_float(row.get(field))
            for field in (
                "next_game_minus_market_delta",
                "rest_of_season_minus_market_delta",
                "dynasty_minus_market_delta",
                "career_minus_market_delta",
            )
            if str(row.get(field) or "").strip()
        ]
        return max((abs(value) for value in deltas), default=0.0)

    market_ranked = sorted(
        horizon_rows,
        key=lambda row: (market_disagreement_magnitude(row), _as_float(row.get("market_value"))),
        reverse=True,
    )
    fit_ranked = sorted(
        horizon_rows,
        key=lambda row: abs(_as_float(row.get("rebuilder_contender_spread"))),
        reverse=True,
    )
    selected_horizon_rows: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for candidate in [*market_ranked[:8], *fit_ranked[:8], *market_ranked]:
        candidate_id = str(candidate.get("player_id") or candidate.get("player_name") or "")
        if candidate_id in selected_ids:
            continue
        selected_ids.add(candidate_id)
        selected_horizon_rows.append(candidate)
        if len(selected_horizon_rows) >= 12:
            break
    for row in selected_horizon_rows:
        lane = str(row.get("value_lane") or "balanced_window").replace("_", " ")
        rows.append(
            _evidence(
                "player",
                row.get("player_id", index),
                index,
                str(row.get("player_name", "")),
                (
                    f"Four-window model={row.get('horizon_model_version', 'unversioned')}; lane={lane}; next game score={row.get('next_game_market_score', 'n/a')} "
                    f"(clock-minus-market={row.get('next_game_minus_market_delta', 'n/a')}) "
                    f"with expected points={row.get('next_game_expected_points', 'n/a')} from baseline={row.get('next_game_baseline_points', 'n/a')} vs {row.get('next_game_opponent', 'opponent unavailable')} "
                    f"(matchup holdout={row.get('next_game_matchup_validation_status', 'unavailable')}; adjustment={row.get('next_game_matchup_adjustment_status', 'unavailable')}) "
                    f"and status={row.get('next_game_status', 'n/a')}; availability_scope={row.get('availability_scope') or 'not_recorded'}; availability={row.get('availability_note', row.get('injury_status', 'not recorded'))}; "
                     f"rest of season score={row.get('rest_of_season_market_score', 'n/a')} (clock-minus-market={row.get('rest_of_season_minus_market_delta', 'n/a')}) {_rest_of_season_context(row)} with {baseline_ppg_text(row, row.get('rest_of_season_ppg', 'n/a'))}; "
                     f"rest-of-season minus next-game delta={row.get('rest_of_season_minus_next_game_delta', 'n/a')}; "
                     f"rest-of-season basis={row.get('rest_of_season_basis', 'not recorded')}; dynasty market score={row.get('dynasty_market_score', 'n/a')} "
                     f"(clock-minus-market={row.get('dynasty_minus_market_delta', 'n/a')}; "
                     f"dynasty minus rest-of-season delta={row.get('dynasty_minus_rest_of_season_delta', 'n/a')}) "
                    f"with status={row.get('dynasty_status', 'n/a')}; five-year career-window score={row.get('career_projection_score', 'n/a')} "
                    f"(clock-minus-market={row.get('career_minus_market_delta', 'n/a')}; career minus dynasty delta={row.get('career_minus_dynasty_delta', 'n/a')}) "
                    f"with status={row.get('career_projection_status', 'n/a')}; career history={row.get('career_history_status') or 'unavailable'} "
                    f"({row.get('career_history_games') or 0} games / {row.get('career_history_seasons') or 0} seasons; "
                    f"historical PPG={row.get('career_history_ppg') or 'n/a'}; source player id={row.get('career_history_source_player_id') or 'unavailable'}); contender fit={row.get('contender_fit_score', 'n/a')}; "
                    f"rebuilder fit={row.get('rebuilder_fit_score', 'n/a')}; spread={row.get('rebuilder_contender_spread', 'n/a')}; "
                    f"score basis={row.get('horizon_score_basis') or HORIZON_SCORE_BASIS}; "
                    f"cross-position price anchor market value={row.get('market_value', 'n/a')}; "
                    f"market percentile (position)={row.get('market_percentile', 'n/a')}."
                ),
                horizon_lane=lane,
                next_game_score=row.get("next_game_market_score", ""),
                next_game_minus_market_delta=row.get("next_game_minus_market_delta", ""),
                next_game_matchup_validation_status=row.get("next_game_matchup_validation_status", ""),
                next_game_matchup_validation_games=row.get("next_game_matchup_validation_games", ""),
                next_game_matchup_validation_mae_delta=row.get("next_game_matchup_validation_mae_delta", ""),
                next_game_matchup_adjustment_status=row.get("next_game_matchup_adjustment_status", ""),
                rest_of_season_score=row.get("rest_of_season_market_score", ""),
                rest_of_season_minus_market_delta=row.get("rest_of_season_minus_market_delta", ""),
                rest_of_season_minus_next_game_delta=row.get("rest_of_season_minus_next_game_delta", ""),
                rest_of_season_baseline_points=row.get("rest_of_season_baseline_points", ""),
                rest_of_season_ppg=row.get("rest_of_season_ppg", ""),
                rest_of_season_basis=row.get("rest_of_season_basis", ""),
                dynasty_score=row.get("dynasty_market_score", ""),
                dynasty_minus_market_delta=row.get("dynasty_minus_market_delta", ""),
                dynasty_minus_rest_of_season_delta=row.get("dynasty_minus_rest_of_season_delta", ""),
                career_projection_score=row.get("career_projection_score", ""),
                career_minus_market_delta=row.get("career_minus_market_delta", ""),
                career_minus_dynasty_delta=row.get("career_minus_dynasty_delta", ""),
                career_projection_status=row.get("career_projection_status", ""),
                career_history_join_method=row.get("career_history_join_method", ""),
                career_history_source_player_id=row.get("career_history_source_player_id", ""),
                career_history_status=row.get("career_history_status", ""),
                career_history_seasons=row.get("career_history_seasons", ""),
                career_history_games=row.get("career_history_games", ""),
                career_history_ppg=row.get("career_history_ppg", ""),
                career_history_latest_season=row.get("career_history_latest_season", ""),
                contender_fit_score=row.get("contender_fit_score", ""),
                rebuilder_fit_score=row.get("rebuilder_fit_score", ""),
                fit_coverage=row.get("fit_coverage", ""),
                horizon_model_version=row.get("horizon_model_version", ""),
                horizon_score_basis=row.get("horizon_score_basis", ""),
                market_value=row.get("market_value", ""),
                market_percentile=row.get("market_percentile", ""),
                fit_basis=row.get("fit_basis", ""),
                injury_status=row.get("injury_status", ""),
                availability_scope=row.get("availability_scope", ""),
                availability_note=row.get("availability_note", ""),
                risk=row.get("risk", ""),
                confidence=row.get("confidence", ""),
                source_trace=row.get("source_trace", ""),
            )
        )
        index += 1
    # Opportunity-vs-output evidence (Sprint 18): the players whose usage is outrunning their
    # points are the sharpest buy-lows -- give the writer the numbers to say so in plain English.
    opp = _load_processed_csv("player_opportunity_scores.csv", ctx.processed_dir)
    buy_low = sorted(opp, key=lambda row: _as_float(row.get("xfp_regression_score")), reverse=True)
    for row in buy_low[:8]:
        if _as_float(row.get("xfp_regression_score")) < 55 or _as_float(row.get("opportunity_score")) < 50:
            continue
        rows.append(
            _evidence(
                "player",
                row.get("player_id", index),
                index,
                str(row.get("player_name", "")),
                (
                    f"{row.get('player_name', 'This player')} ({row.get('position', '')}): opportunity "
                    f"{row.get('opportunity_score')} but production {row.get('production_score')} -- usage is "
                    f"outrunning the box score (xfp_regression {row.get('xfp_regression_score')}). {row.get('opportunity_evidence', '')}"
                ),
                side="opportunity_buy_low",
                opportunity_score=row.get("opportunity_score", ""),
                production_score=row.get("production_score", ""),
                xfp_regression_score=row.get("xfp_regression_score", ""),
                source_trace=row.get("source_trace", ""),
                checked_at=row.get("checked_at", ""),
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
                assets_to_pursue=item.get("assets_to_pursue", []),
                assets_we_can_offer=item.get("assets_we_can_offer", []),
                assets_target_may_value=item.get("assets_target_may_value", []),
                counterparty_interest_status=item.get("counterparty_interest_status", "none_supported"),
                offer_candidates=item.get("offer_candidates", []),
                plausible_offer_range=item.get("plausible_offer_range", {}),
                minimum_acceptable_return=item.get("minimum_acceptable_return", {}),
                why_manager_might_care=item.get("why_manager_might_care", ""),
                historical_evidence=item.get("historical_evidence", {}),
                target_team_lens=item.get("target_team_lens", ""),
                target_horizon_fit_score=item.get("target_horizon_fit_score", ""),
                active_horizon_fit_score=item.get("active_horizon_fit_score", ""),
                horizon_fit_edge=item.get("horizon_fit_edge", ""),
                horizon_fit_read=item.get("horizon_fit_read", ""),
                horizon_fit_basis=item.get("horizon_fit_basis", ""),
                horizon_model_version=item.get("horizon_model_version", ""),
                horizon_market_percentile=item.get("horizon_market_percentile", ""),
                next_game_market_score=item.get("next_game_market_score", ""),
                rest_of_season_market_score=item.get("rest_of_season_market_score", ""),
                dynasty_market_score=item.get("dynasty_market_score", ""),
                career_projection_score=item.get("career_projection_score", ""),
                next_game_minus_market_delta=item.get("next_game_minus_market_delta", ""),
                rest_of_season_minus_market_delta=item.get("rest_of_season_minus_market_delta", ""),
                dynasty_minus_market_delta=item.get("dynasty_minus_market_delta", ""),
                career_minus_market_delta=item.get("career_minus_market_delta", ""),
                rest_of_season_minus_next_game_delta=item.get("rest_of_season_minus_next_game_delta", ""),
                dynasty_minus_rest_of_season_delta=item.get("dynasty_minus_rest_of_season_delta", ""),
                career_minus_dynasty_delta=item.get("career_minus_dynasty_delta", ""),
                horizon_market_disagreement_window=item.get("horizon_market_disagreement_window", ""),
                horizon_market_disagreement_delta=item.get("horizon_market_disagreement_delta", ""),
                horizon_market_disagreement_magnitude=item.get("horizon_market_disagreement_magnitude", ""),
                horizon_market_disagreement_read=item.get("horizon_market_disagreement_read", ""),
                risk_of_waiting=item.get("risk_of_waiting", ""),
                risk_of_acting=item.get("risk_of_acting", ""),
                alternative_counterparties=item.get("alternative_counterparties", []),
                do_not_chase_conditions=item.get("do_not_chase_conditions", []),
                manager_signal=item.get("manager_signal", ""),
                risk=item.get("risk", ""),
                confidence=item.get("confidence", ""),
                evidence=item.get("evidence", ""),
                source_trace=item.get("source_trace", ""),
                checked_at=item.get("checked_at", ""),
            )
        )
    return rows


def _scope_manager_intel(ctx: ArticleContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_load_items(ctx.analysis_dir, "manager_dossiers.json")[:14], start=1):
        manager_context = {
            key: _compact_manager_value(item.get(key))
            for key in (
                "historical_aliases",
                "outcome_summary",
                "sample_size",
                "roster_construction",
                "season_history",
                "trajectory",
                "repeated_behavior",
                "behavior_observations",
                "trade_fits",
                "trade_fit_evaluation",
                "counterparty_interest",
                "transaction_profile",
                "transaction_timeline",
                "questions_to_ask",
                "unknowns",
            )
            if item.get(key) not in (None, "", [], {})
        }
        rows.append(
            _evidence(
                "manager",
                item.get("roster_id", index),
                index,
                str(item.get("team_name", item.get("manager_name", ""))),
                str(item.get("analysis_text", "")),
                manager_context=manager_context,
                dynasty_cycle=item.get("dynasty_cycle", ""),
                trade_fit_status=item.get("trade_fit_status", "none_supported"),
                trade_fit_summary=item.get("trade_fit_summary", ""),
                confidence=item.get("confidence", ""),
                evidence=item.get("evidence", ""),
                source_trace=item.get("source_trace", ""),
                checked_at=item.get("checked_at", ""),
            )
        )
    return rows


def _scope_available_market_rows(ctx: ArticleContext) -> list[dict[str, Any]]:
    """Return a small, identity- and league-scoped available-market packet."""

    rows = _load_processed_csv("available_player_horizon_scores.csv", ctx.processed_dir)
    if not rows:
        return []
    roster_rows = _load_processed_csv("roster_players.csv", ctx.processed_dir)
    rostered_ids = {
        str(row.get("player_id") or "").strip()
        for row in roster_rows
        if str(row.get("player_id") or "").strip()
        and (not ctx.season or not str(row.get("season") or "").strip() or _same_id(row.get("season"), ctx.season))
        and (not ctx.league_id or not str(row.get("league_id") or "").strip() or _same_id(row.get("league_id"), ctx.league_id))
    }
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not str(row.get("player_name") or "").strip() or not str(row.get("player_id") or "").strip():
            continue
        if ctx.season and str(row.get("season") or "").strip() and not _same_id(row.get("season"), ctx.season):
            continue
        if ctx.league_id and str(row.get("league_id") or "").strip() and not _same_id(row.get("league_id"), ctx.league_id):
            continue
        if str(row.get("availability_status") or "").strip() != "not_rostered_in_selected_league":
            continue
        if str(row.get("identity_status") or "").strip() not in {"sleeper_id", "sleeper_unique_name_match"}:
            continue
        if str(row.get("player_id") or "").strip() in rostered_ids:
            continue
        if not any(str(row.get(field) or "").strip() for field in (
            "next_game_market_score",
            "rest_of_season_market_score",
            "dynasty_market_score",
            "career_projection_score",
        )):
            continue
        valid.append(dict(row))

    # Keep the packet position-aware.  A percentile is not a cross-position
    # ranking, so Waverly gets a few best research leads per position rather
    # than a misleading league-wide top-ten.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in valid:
        grouped.setdefault(str(row.get("position") or "OTHER"), []).append(row)
    selected: list[dict[str, Any]] = []
    for position in sorted(grouped):
        selected.extend(
            sorted(
                grouped[position],
                key=lambda row: (
                    _coverage_count(row),
                    max(
                        _as_float(row.get("next_game_market_score")),
                        _as_float(row.get("rest_of_season_market_score")),
                        _as_float(row.get("dynasty_market_score")),
                        _as_float(row.get("career_projection_score")),
                    ),
                    abs(_as_float(row.get("rebuilder_contender_spread"))),
                    _as_float(row.get("market_value")),
                ),
                reverse=True,
            )[:2]
        )
    return selected[:12]


def _coverage_count(row: dict[str, Any]) -> int:
    try:
        coverage = str(row.get("fit_coverage") or "").split("/", 1)[0]
        return int(float(coverage))
    except (TypeError, ValueError):
        return sum(1 for field in (
            "next_game_market_score",
            "rest_of_season_market_score",
            "dynasty_market_score",
            "career_projection_score",
        ) if str(row.get(field) or "").strip())


def _available_market_text(row: dict[str, Any], lane: str) -> str:
    """Describe an available row without upgrading research availability into waiver fact."""

    return (
        f"Available-market research row; identity={row.get('identity_status', 'unresolved')}; "
        f"lane={lane}; this-week score={row.get('next_game_market_score') or 'n/a'} "
        f"(clock-minus-market={row.get('next_game_minus_market_delta') or 'n/a'}) "
        f"({row.get('next_game_status') or 'status unavailable'}) vs {row.get('next_game_opponent') or 'opponent unavailable'}; "
        f"rest-of-season score={row.get('rest_of_season_market_score') or 'n/a'} "
        f"(clock-minus-market={row.get('rest_of_season_minus_market_delta') or 'n/a'}; delta from this week={row.get('rest_of_season_minus_next_game_delta') or 'n/a'}); "
        f"dynasty score={row.get('dynasty_market_score') or 'n/a'} "
        f"(clock-minus-market={row.get('dynasty_minus_market_delta') or 'n/a'}; delta from rest of season={row.get('dynasty_minus_rest_of_season_delta') or 'n/a'}); "
        f"five-year career-window score={row.get('career_projection_score') or 'n/a'} "
        f"(clock-minus-market={row.get('career_minus_market_delta') or 'n/a'}; delta from dynasty={row.get('career_minus_dynasty_delta') or 'n/a'}); "
        f"contender fit={row.get('contender_fit_score') or 'n/a'}, rebuilder fit={row.get('rebuilder_fit_score') or 'n/a'}, "
        f"spread={row.get('rebuilder_contender_spread') or 'n/a'}; fit coverage={row.get('fit_coverage') or 'unavailable'}; "
        f"market value={row.get('market_value') or 'n/a'} and position market percentile={row.get('market_percentile') or 'n/a'}; "
        f"market receipt={row.get('market_source_count') or 'n/a'} source(s), disagreement {row.get('market_disagreement_score') or 'n/a'}, "
        f"confidence {row.get('market_source_confidence') or 'unavailable'}; "
        f"availability={row.get('availability_status') or 'unavailable'}; "
        "this is not a waiver-eligibility or claim receipt."
    )


def _scope_horizon_watch(ctx: ArticleContext) -> list[dict[str, Any]]:
    """Give the horizon desk one comparable, position-aware market packet.

    Horizon percentiles are not cross-position prices. Select a small leader
    set within each position so the writer can explain the clocks without
    receiving a misleading league-wide percentile leaderboard.
    """

    rows = [
        row for row in _load_processed_csv("player_horizon_market_scores.csv", ctx.processed_dir)
        if str(row.get("player_name") or "").strip()
        and (not ctx.season or not str(row.get("season", "")).strip() or _same_id(row.get("season"), ctx.season))
        and _same_optional_league(row.get("league_id"), ctx.league_id)
        and str(row.get("value_lane") or "") != "insufficient_context"
        and any(str(row.get(field) or "").strip() for field in (
            "next_game_market_score",
            "rest_of_season_market_score",
            "dynasty_market_score",
            "career_projection_score",
        ))
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("position") or "OTHER"), []).append(row)
    selected: list[dict[str, Any]] = []
    for position in sorted(grouped):
        position_rows = sorted(
            grouped[position],
            key=lambda row: (
                abs(_as_float(row.get("rebuilder_contender_spread"))),
                max(
                    _as_float(row.get("next_game_market_score")),
                    _as_float(row.get("rest_of_season_market_score")),
                    _as_float(row.get("dynasty_market_score")),
                    _as_float(row.get("career_projection_score")),
                ),
            ),
            reverse=True,
        )
        selected.extend(position_rows[:3])
    selected.sort(
        key=lambda row: (
            str(row.get("position") or "OTHER"),
            -abs(_as_float(row.get("rebuilder_contender_spread"))),
            str(row.get("player_name") or ""),
        )
    )
    output: list[dict[str, Any]] = []
    for index, row in enumerate(selected[:24], start=1):
        position = str(row.get("position") or "asset")
        lane = str(row.get("value_lane") or "balanced_window").replace("_", " ")
        name = str(row.get("player_name") or "Unknown player")
        narrative = (
            f"{name} ({position}) is a {lane}: next-game percentile={row.get('next_game_market_score') or 'n/a'}, "
            f"next-game minus position-market percentile={row.get('next_game_minus_market_delta') or 'n/a'}, "
            f"rest-of-season percentile={row.get('rest_of_season_market_score') or 'n/a'}, "
            f"rest-of-season minus position-market percentile={row.get('rest_of_season_minus_market_delta') or 'n/a'}, "
            f"rest-of-season minus next-game delta={row.get('rest_of_season_minus_next_game_delta') or 'n/a'}, "
            f"dynasty percentile={row.get('dynasty_market_score') or 'n/a'}, "
            f"dynasty minus position-market percentile={row.get('dynasty_minus_market_delta') or 'n/a'}, "
            f"dynasty minus rest-of-season delta={row.get('dynasty_minus_rest_of_season_delta') or 'n/a'}, "
            f"five-year career-window percentile={row.get('career_projection_score') or 'n/a'}; "
            f"career minus position-market percentile={row.get('career_minus_market_delta') or 'n/a'}; "
            f"career minus dynasty delta={row.get('career_minus_dynasty_delta') or 'n/a'}; "
            f"career history={row.get('career_history_status') or 'unavailable'} "
            f"({row.get('career_history_games') or 0} games / {row.get('career_history_seasons') or 0} seasons; "
            f"historical PPG={row.get('career_history_ppg') or 'n/a'}; source player id={row.get('career_history_source_player_id') or 'unavailable'}); "
            f"matchup adjustment={row.get('next_game_matchup_adjustment_status') or 'unavailable'}; "
            f"contender fit={row.get('contender_fit_score') or 'n/a'}, rebuilder fit={row.get('rebuilder_fit_score') or 'n/a'}, "
            f"spread={row.get('rebuilder_contender_spread') or 'n/a'}. "
            f"Cross-position price anchor={row.get('market_value') or 'n/a'} and position market percentile={row.get('market_percentile') or 'n/a'}; "
            f"market receipt={row.get('market_source_count') or 'n/a'} source(s), disagreement {row.get('market_disagreement_score') or 'n/a'}, "
            f"confidence {row.get('market_source_confidence') or 'unavailable'}."
        )
        output.append(
            _evidence(
                "player",
                row.get("player_id", index),
                index,
                name,
                narrative,
                position=position,
                horizon_lane=lane,
                next_game_score=row.get("next_game_market_score", ""),
                next_game_minus_market_delta=row.get("next_game_minus_market_delta", ""),
                rest_of_season_score=row.get("rest_of_season_market_score", ""),
                rest_of_season_minus_market_delta=row.get("rest_of_season_minus_market_delta", ""),
                rest_of_season_minus_next_game_delta=row.get("rest_of_season_minus_next_game_delta", ""),
                dynasty_score=row.get("dynasty_market_score", ""),
                dynasty_minus_market_delta=row.get("dynasty_minus_market_delta", ""),
                dynasty_minus_rest_of_season_delta=row.get("dynasty_minus_rest_of_season_delta", ""),
                career_projection_score=row.get("career_projection_score", ""),
                career_minus_market_delta=row.get("career_minus_market_delta", ""),
                career_minus_dynasty_delta=row.get("career_minus_dynasty_delta", ""),
                career_history_join_method=row.get("career_history_join_method", ""),
                career_history_source_player_id=row.get("career_history_source_player_id", ""),
                career_history_status=row.get("career_history_status", ""),
                career_history_seasons=row.get("career_history_seasons", ""),
                career_history_games=row.get("career_history_games", ""),
                career_history_ppg=row.get("career_history_ppg", ""),
                career_history_latest_season=row.get("career_history_latest_season", ""),
                contender_fit_score=row.get("contender_fit_score", ""),
                rebuilder_fit_score=row.get("rebuilder_fit_score", ""),
                fit_coverage=row.get("fit_coverage", ""),
                rebuilder_contender_spread=row.get("rebuilder_contender_spread", ""),
                market_value=row.get("market_value", ""),
                market_percentile=row.get("market_percentile", ""),
                market_source_count=row.get("market_source_count", ""),
                market_disagreement_score=row.get("market_disagreement_score", ""),
                market_source_confidence=row.get("market_source_confidence", ""),
                next_game_opponent=row.get("next_game_opponent", ""),
                next_game_status=row.get("next_game_status", ""),
                next_game_matchup_adjustment_status=row.get("next_game_matchup_adjustment_status", ""),
                availability_note=row.get("availability_note", ""),
                horizon_model_version=row.get("horizon_model_version", ""),
                horizon_score_basis=row.get("horizon_score_basis", ""),
                fit_basis=row.get("fit_basis", ""),
                risk=row.get("risk", ""),
                confidence=row.get("confidence", ""),
                evidence=row.get("evidence", ""),
                source_trace=row.get("source_trace", ""),
            )
        )
    movement_rows = [
        row for row in _load_processed_csv("horizon_market_movements.csv", ctx.processed_dir)
        if str(row.get("movement_status") or "").strip() == "changed"
        and str(row.get("player_name") or "").strip()
        and (not ctx.season or not str(row.get("season", "")).strip() or _same_id(row.get("season"), ctx.season))
        and _same_optional_league(row.get("league_id"), ctx.league_id)
    ]
    movement_rows.sort(
        key=lambda row: (
            _as_float(row.get("largest_clock_movement_magnitude")),
            str(row.get("player_name") or ""),
        ),
        reverse=True,
    )
    movement_index = len(output) + 1
    for row in movement_rows[:8]:
        player_id = str(row.get("player_id") or row.get("player_name") or movement_index)
        current_week = str(row.get("current_as_of_week") or "unknown")
        prior_week = str(row.get("prior_as_of_week") or "unknown")
        window = str(row.get("largest_clock_movement_window") or "clock")
        delta = str(row.get("largest_clock_movement_delta") or "n/a")
        movement_delta = _as_float(row.get("largest_clock_movement_delta"))
        direction = "rose" if movement_delta > 0 else "fell" if movement_delta < 0 else "held"
        movement_text = (
            f"{row.get('player_name')} has a changed exact-scope horizon receipt: the largest clock movement was "
            f"{window} ({delta} percentile points, {direction}) from week {prior_week} to week {current_week}; "
            f"market value delta={row.get('market_value_delta') or 'n/a'}, "
            f"rebuilder-versus-contender spread delta={row.get('rebuilder_contender_spread_delta') or 'n/a'}, "
            f"lane={row.get('value_lane') or 'unavailable'}. This is observed model movement, not a fifth score or proof of mispricing."
        )
        output.append(
            _evidence(
                "horizon_movement",
                f"{player_id}:{current_week}",
                movement_index,
                str(row.get("player_name") or "Horizon movement"),
                movement_text,
                _article_entity_type="horizon_movement",
                _article_entity_id=f"{player_id}:{current_week}",
                player_id=player_id,
                position=row.get("position", ""),
                league_id=row.get("league_id", ctx.league_id),
                season=row.get("season", ctx.season),
                movement_status=row.get("movement_status", "changed"),
                prior_as_of_week=row.get("prior_as_of_week", ""),
                current_as_of_week=row.get("current_as_of_week", ""),
                largest_clock_movement_window=window,
                largest_clock_movement_delta=row.get("largest_clock_movement_delta", ""),
                largest_clock_movement_magnitude=row.get("largest_clock_movement_magnitude", ""),
                value_lane_change=row.get("value_lane_change", ""),
                source_trace=row.get("source_trace", ""),
                checked_at=row.get("current_snapshot_at", ""),
            )
        )
        movement_index += 1
    return output


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
            rows.append(
                _evidence(
                    entity_type,
                    entity_id,
                    index,
                    str(name),
                    str(item.get("analysis_text", "")),
                    source_trace=item.get("source_trace", ""),
                    checked_at=item.get("checked_at", ""),
                )
            )
        base = len(rows)
    return rows


ARTICLES: list[Article] = [
    Article("team_report", "Your Team Report", "team_report.md", ("## Cornerstones", "## Shop Candidates"), _scope_team_report, "team-report", reporter_id="topline_tony"),
    Article("market_watch", "Market Watch", "market_watch.md", ("## Buy-Low Targets", "## Sell-High Windows"), _scope_market_watch, "market-watch", reporter_id="waiver_wire_waverly"),
    Article("trade_desk", "Trade Desk Read", "trade_desk.md", ("## Best Fits", "## Steer Clear"), _scope_trade_desk, "trade-desk-read", reporter_id="trade_desk_talia"),
    Article("manager_intel", "Manager Intel", "manager_intel.md", ("## Contenders", "## Rebuilders"), _scope_manager_intel, "manager-intel", reporter_id="dossier_dana"),
    Article("daily_brief", "Daily GM Brief", "daily_brief.md", ("## Target Theses", "## Sell Windows", "## Manager Angles"), _scope_daily_brief, "daily-gm-brief", is_summary=True, reporter_id="look_ahead_lonnie"),
    Article("horizon_watch", "Four-Window Market Read", "horizon_watch.md", ("## This Week", "## Rest of Season", "## Dynasty Window", "## Market vs Clock", "## Contender vs Rebuilder"), _scope_horizon_watch, "horizon-market-read", is_summary=True, reporter_id="market_clock_morgan"),
]


def _safe_config() -> dict[str, Any]:
    try:
        return load_config()
    except (OSError, ValueError):
        return {}


def _normalize_name(value: Any) -> str:
    # Matches src/projections.py::_normalize_name -- the shared player-name join/dedup key.
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


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


def _rest_of_season_context(row: dict[str, Any]) -> str:
    """Describe the ROS input without presenting missing schedule coverage as a game count."""

    value = str(row.get("rest_of_season_games") or "").strip()
    if value:
        try:
            return f"across {int(float(value))} scheduled games"
        except ValueError:
            return f"across {value} scheduled games"
    return "from the season projection baseline; scheduled game count unavailable"
