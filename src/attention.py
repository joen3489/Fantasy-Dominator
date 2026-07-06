from __future__ import annotations

"""Deterministic cross-league attention queue for the home screen."""

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .league_paths import LeaguePaths
from .utils import DATA_DIR, dump_json, load_json


ATTENTION_QUEUE_PATH = DATA_DIR / "attention_queue.json"


@dataclass
class AttentionItem:
    league_id: str
    league_name: str
    league_type: str
    item_type: str
    severity: int
    headline: str
    detail: str
    deep_link: str
    evidence: str
    generated_at: str


def deadline_items(
    entry: dict[str, Any],
    paths: LeaguePaths,
    league_settings: dict[str, Any],
    transactions: list[dict[str, str]],
    now: datetime | None = None,
) -> list[AttentionItem]:
    """Surface deadlines only from explicit league settings or pending rows."""
    generated_at = _now(now).isoformat()
    league_id = str(entry.get("league_id") or paths.league_id)
    league_name = _league_name(entry)
    league_type = str(entry.get("league_type") or "redraft")
    items: list[AttentionItem] = []

    waiver_day = _int_or_none(league_settings.get("waiver_day_of_week"))
    if waiver_day is not None:
        current = _now(now)
        today_sleeper = (current.weekday() + 1) % 7
        tomorrow_sleeper = ((current + timedelta(days=1)).weekday() + 1) % 7
        if waiver_day == today_sleeper:
            items.append(
                AttentionItem(
                    league_id=league_id,
                    league_name=league_name,
                    league_type=league_type,
                    item_type="deadline",
                    severity=80,
                    headline="Waivers process today",
                    detail="This league is configured to process waivers today, so claims and roster churn need a same-day check.",
                    deep_link=f"/league/{league_id}/#view-today",
                    evidence=_evidence([f"waiver_day_of_week={waiver_day}", f"waiver_type={league_settings.get('waiver_type', '')}", f"daily_waivers={league_settings.get('daily_waivers', '')}"]),
                    generated_at=generated_at,
                )
            )
        elif waiver_day == tomorrow_sleeper:
            items.append(
                AttentionItem(
                    league_id=league_id,
                    league_name=league_name,
                    league_type=league_type,
                    item_type="deadline",
                    severity=60,
                    headline="Waivers process tomorrow",
                    detail="This league's waiver day is tomorrow, so claims can be staged before the window closes.",
                    deep_link=f"/league/{league_id}/#view-today",
                    evidence=_evidence([f"waiver_day_of_week={waiver_day}", f"waiver_type={league_settings.get('waiver_type', '')}", f"daily_waivers={league_settings.get('daily_waivers', '')}"]),
                    generated_at=generated_at,
                )
            )

    # Only genuinely PENDING transactions demand attention. "failed" and "complete" are
    # history -- surfacing weeks-old failed waiver claims as severity-85 deadlines was the
    # first thing flagged in review of the initial implementation.
    seen_transactions: set[str] = set()
    for row in transactions:
        if not _row_matches_entry(row, entry):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status != "pending":
            continue
        transaction_id = str(row.get("transaction_id") or "")
        if transaction_id and transaction_id in seen_transactions:
            continue
        if transaction_id:
            seen_transactions.add(transaction_id)
        asset = _transaction_asset(row)
        headline = f"{asset}: pending {row.get('type', 'transaction')}" if asset else f"Pending {row.get('type', 'transaction')} awaiting action"
        items.append(
            AttentionItem(
                league_id=league_id,
                league_name=league_name,
                league_type=league_type,
                item_type="deadline",
                severity=85,
                headline=headline,
                detail="An open transaction is awaiting action in this league.",
                deep_link=f"/league/{league_id}/#view-today",
                evidence=_evidence([f"transaction_id={row.get('transaction_id', '')}", f"type={row.get('type', '')}", f"status={row.get('status', '')}"]),
                generated_at=generated_at,
            )
        )

    return items


def roster_health_items(
    entry: dict[str, Any],
    paths: LeaguePaths,
    roster_players: list[dict[str, str]],
    players: list[dict[str, str]],
    league_news_impact: list[dict[str, str]],
    player_dossiers: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> list[AttentionItem]:
    """Prefer player-level dedupe because multiple sources can report one injury."""
    generated_at = _now(now).isoformat()
    league_id = str(entry.get("league_id") or paths.league_id)
    league_name = _league_name(entry)
    league_type = str(entry.get("league_type") or "redraft")
    roster_id = str(entry.get("roster_id") or "")
    owned_rows = [row for row in roster_players if _row_matches_entry(row, entry) and str(row.get("roster_id") or "") == roster_id]
    owned_ids = {str(row.get("player_id") or "") for row in owned_rows if row.get("player_id")}
    names_by_id = {str(row.get("player_id") or ""): str(row.get("player_name") or "") for row in owned_rows}
    statuses = {str(row.get("player_id") or ""): str(row.get("status") or "") for row in players}
    dossiers = {str(row.get("player_id") or ""): row for row in (player_dossiers or []) if _row_matches_entry(row, entry)}
    by_player: dict[str, AttentionItem] = {}

    for player_id in owned_ids:
        status = statuses.get(player_id, "").strip()
        if not status or status.lower() == "active":
            continue
        name = names_by_id.get(player_id) or _player_name(players, player_id) or f"Player {player_id}"
        market_value = _float_or_none(dossiers.get(player_id, {}).get("market_value"))
        severity = 70 if market_value is not None and market_value >= 20 else 50
        by_player[player_id] = AttentionItem(
            league_id=league_id,
            league_name=league_name,
            league_type=league_type,
            item_type="roster_health",
            severity=severity,
            headline=f"{name} is {status}",
            detail="An owned player is not listed as Active, so lineup and trade assumptions need a fresh read.",
            deep_link=f"/league/{league_id}/#player-{player_id}",
            evidence=_evidence([f"player_id={player_id}", f"status={status}", f"market_value={market_value if market_value is not None else ''}"]),
            generated_at=generated_at,
        )

    for row in league_news_impact:
        if not _row_matches_entry(row, entry):
            continue
        player_id = str(row.get("player_id") or "")
        if player_id not in owned_ids:
            continue
        if "injury" not in str(row.get("impact_type") or "").lower():
            continue
        name = names_by_id.get(player_id) or row.get("player_name") or f"Player {player_id}"
        item = AttentionItem(
            league_id=league_id,
            league_name=league_name,
            league_type=league_type,
            item_type="roster_health",
            severity=65,
            headline=f"{name}: injury news",
            detail="Recent league news flags an injury-related impact for an owned player.",
            deep_link=f"/league/{league_id}/#player-{player_id}",
            evidence=_evidence([f"event_id={row.get('event_id', '')}", f"impact_type={row.get('impact_type', '')}", row.get("evidence", "")]),
            generated_at=generated_at,
        )
        if player_id not in by_player or item.severity > by_player[player_id].severity:
            by_player[player_id] = item

    return sorted(by_player.values(), key=lambda item: (-item.severity, item.headline))


def market_window_items(
    entry: dict[str, Any],
    paths: LeaguePaths,
    roster_players: list[dict[str, str]],
    action_recommendations: list[dict[str, str]],
    now: datetime | None = None,
) -> list[AttentionItem]:
    """Limit each league to the strongest buy/sell windows so the feed stays useful."""
    generated_at = _now(now).isoformat()
    league_id = str(entry.get("league_id") or paths.league_id)
    league_name = _league_name(entry)
    league_type = str(entry.get("league_type") or "redraft")
    roster_id = str(entry.get("roster_id") or "")
    owned_ids = {
        str(row.get("player_id") or "")
        for row in roster_players
        if _row_matches_entry(row, entry) and str(row.get("roster_id") or "") == roster_id and row.get("player_id")
    }
    sell_items: list[AttentionItem] = []
    buy_items: list[AttentionItem] = []

    for row in action_recommendations:
        if not _row_matches_entry(row, entry):
            continue
        player_id = str(row.get("player_id") or "")
        label = str(row.get("action_label") or "")
        score = _float_or_none(row.get("action_score")) or 0.0
        name = str(row.get("player_name") or f"Player {player_id}")
        row_roster_id = str(row.get("roster_id") or "")
        owned = player_id in owned_ids or (roster_id and row_roster_id == roster_id)
        if label == "sell_window" and owned:
            severity = min(75, int(40 + score / 4))
            sell_items.append(
                AttentionItem(
                    league_id=league_id,
                    league_name=league_name,
                    league_type=league_type,
                    item_type="market_window",
                    severity=severity,
                    headline=f"Sell window: {name}",
                    detail="The recommendation model sees a sell window for a player on your roster.",
                    deep_link=f"/league/{league_id}/#player-{player_id}",
                    evidence=_evidence([f"action_label={label}", f"action_score={row.get('action_score', '')}", row.get("evidence", "")]),
                    generated_at=generated_at,
                )
            )
        elif label == "true_buy_low" and not owned:
            severity = min(65, int(30 + score / 4))
            buy_items.append(
                AttentionItem(
                    league_id=league_id,
                    league_name=league_name,
                    league_type=league_type,
                    item_type="market_window",
                    severity=severity,
                    headline=f"Buy-low target: {name}",
                    detail="The recommendation model sees a buy-low window on another roster.",
                    deep_link=f"/league/{league_id}/#player-{player_id}",
                    evidence=_evidence([f"action_label={label}", f"action_score={row.get('action_score', '')}", f"roster_id={row.get('roster_id', '')}", row.get("evidence", "")]),
                    generated_at=generated_at,
                )
            )

    sell_items.sort(key=lambda item: (-item.severity, item.headline))
    buy_items.sort(key=lambda item: (-item.severity, item.headline))
    return sell_items[:3] + buy_items[:3]


def quiet_item(entry: dict[str, Any], paths: LeaguePaths, refresh_metadata: list[dict[str, str]], now: datetime | None = None) -> AttentionItem:
    """Make a quiet league visible without pretending there is urgent work."""
    generated_at = _now(now).isoformat()
    league_id = str(entry.get("league_id") or paths.league_id)
    league_name = _league_name(entry)
    refreshed = _last_refreshed(refresh_metadata)
    detail = f"Latest processed data was refreshed at {refreshed}." if refreshed else "No refresh timestamp was found in processed metadata."
    return AttentionItem(
        league_id=league_id,
        league_name=league_name,
        league_type=str(entry.get("league_type") or "redraft"),
        item_type="quiet",
        severity=5,
        headline=f"Nothing needs you in {league_name}",
        detail=detail,
        deep_link="",
        evidence=_evidence([f"refresh_generated_at={refreshed}"]),
        generated_at=generated_at,
    )


def build_league_attention(entry: dict[str, Any], paths: LeaguePaths, now: datetime | None = None) -> list[AttentionItem]:
    """Load one league defensively; absent optional artifacts just remove signals."""
    roster_players = _read_csv(paths.processed_dir / "roster_players.csv")
    players = _read_csv(paths.processed_dir / "players.csv")
    news = _read_csv(paths.processed_dir / "league_news_impact.csv")
    metadata = _read_csv(paths.processed_dir / "refresh_metadata.csv")
    league_type = str(entry.get("league_type") or "redraft")

    items = roster_health_items(
        entry,
        paths,
        roster_players,
        players,
        news,
        _read_csv(paths.processed_dir / "player_dossiers.csv"),
        now,
    )
    if league_type == "best_ball":
        items = [_with_severity(item, max(5, item.severity - 20)) for item in items]
    else:
        settings = _league_settings(entry, paths)
        items.extend(
            deadline_items(
                entry,
                paths,
                settings,
                _read_csv(paths.processed_dir / "transactions_normalized.csv"),
                now,
            )
        )
        items.extend(market_window_items(entry, paths, roster_players, _read_csv(paths.processed_dir / "action_recommendations.csv"), now))

    if not any(item.severity >= 40 for item in items):
        return [quiet_item(entry, paths, metadata, now)]
    return sorted(items, key=lambda item: (-item.severity, item.league_name, item.headline))


def build_user_attention(registry_entries: list[dict[str, Any]], now: datetime | None = None) -> list[AttentionItem]:
    """Merge leagues while making broken league state loud but non-fatal."""
    generated_at = _now(now).isoformat()
    items: list[AttentionItem] = []
    for entry in registry_entries:
        league_id = str(entry.get("league_id") or "")
        league_name = _league_name(entry)
        league_type = str(entry.get("league_type") or "redraft")
        try:
            paths = LeaguePaths.for_league(league_id)
            if not paths.root.exists():
                raise FileNotFoundError(f"missing league root: {paths.root}")
            items.extend(build_league_attention(entry, paths, now))
        except Exception as exc:
            items.append(
                AttentionItem(
                    league_id=league_id,
                    league_name=league_name,
                    league_type=league_type,
                    item_type="deadline",
                    severity=90,
                    headline=f"League {league_name}: data problem",
                    detail="Attention data could not be built for this league; refresh or inspect the league cache before trusting the home screen.",
                    deep_link=f"/league/{league_id}/#view-today" if league_id else "",
                    evidence=f"error={type(exc).__name__}: {exc}",
                    generated_at=generated_at,
                )
            )
    return sorted(items, key=lambda item: (-item.severity, item.league_name, item.headline))


def save_attention(items: list[AttentionItem], path: Path = ATTENTION_QUEUE_PATH) -> None:
    generated_at = items[0].generated_at if items else datetime.now(timezone.utc).isoformat()
    dump_json(path, {"generated_at": generated_at, "items": [asdict(item) for item in items]})


def load_attention(path: Path = ATTENTION_QUEUE_PATH) -> list[AttentionItem]:
    data = load_json(path)
    rows = data.get("items", []) if isinstance(data, dict) else []
    return [AttentionItem(**row) for row in rows if isinstance(row, dict)]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _league_settings(entry: dict[str, Any], paths: LeaguePaths) -> dict[str, Any]:
    season = str(entry.get("season") or "")
    candidates = [paths.raw_dir / season / "league.json"] if season else []
    candidates.append(paths.raw_dir / "league.json")
    for path in candidates:
        if not path.exists():
            continue
        data = load_json(path)
        settings = data.get("settings") if isinstance(data, dict) else None
        return settings if isinstance(settings, dict) else {}
    return {}


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _league_name(entry: dict[str, Any]) -> str:
    return str(entry.get("name") or entry.get("league_id") or "Unknown league")


def _evidence(parts: list[Any]) -> str:
    return "; ".join(str(part) for part in parts if part not in (None, ""))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _transaction_asset(row: dict[str, str]) -> str:
    for key in ("adds", "drops", "draft_picks_moved"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.split(";")[0].split(",")[0].strip()
    return ""


def _player_name(players: list[dict[str, str]], player_id: str) -> str:
    for row in players:
        if str(row.get("player_id") or "") == player_id:
            return str(row.get("full_name") or row.get("player_name") or "")
    return ""


def _last_refreshed(refresh_metadata: list[dict[str, str]]) -> str:
    if not refresh_metadata:
        return ""
    row = refresh_metadata[0]
    return str(row.get("generated_at") or row.get("analysis_generated_at") or "")


def _with_severity(item: AttentionItem, severity: int) -> AttentionItem:
    data = asdict(item)
    data["severity"] = severity
    return AttentionItem(**data)


def _row_matches_entry(row: dict[str, str], entry: dict[str, Any]) -> bool:
    season = str(entry.get("season") or "")
    league_id = str(entry.get("league_id") or "")
    if row.get("season") not in (None, "") and season and str(row.get("season")) != season:
        return False
    if row.get("league_id") not in (None, "") and league_id and str(row.get("league_id")) != league_id:
        return False
    return True
