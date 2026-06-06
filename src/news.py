from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .players import player_field, player_name
from .sleeper_api import SleeperAPI
from .utils import RAW_EXTERNAL_DIR


ROTOWIRE_NFL_RSS_URL = "https://www.rotowire.com/rss/news.php?sport=NFL"


def build_news_tables(
    config: dict[str, Any],
    api: SleeperAPI,
    players: dict[str, dict[str, Any]],
    teams: pd.DataFrame,
    roster_players: pd.DataFrame,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    season = str(config.get("current_season", "global") or "global")
    news_config = config.get("news_sources") or {}
    enabled = news_config.get("enabled") or ["rotowire_rss", "sleeper_trending"]
    rss_url = news_config.get("rotowire_nfl_rss_url") or ROTOWIRE_NFL_RSS_URL

    events: list[dict[str, Any]] = []
    freshness: list[dict[str, Any]] = []

    if "rotowire_rss" in enabled:
        rss_events, row = _load_rotowire_rss(season, rss_url, force)
        events.extend(rss_events)
        freshness.append(row | {"row_count": len(rss_events)})

    if "sleeper_trending" in enabled:
        for trend_type in ("add", "drop"):
            trend_events, row = _load_sleeper_trending(season, trend_type, api, players, force)
            events.extend(trend_events)
            freshness.append(row | {"row_count": len(trend_events)})

    if not freshness:
        freshness.append(_freshness("news_sources", "disabled", "no_news_sources_enabled", "", None))

    news_events = pd.DataFrame(events, columns=_news_event_columns())
    matches = _match_news_events(news_events, players)
    impact = _build_league_news_impact(news_events, matches, teams, roster_players)

    return {
        "news_events": news_events,
        "player_news_matches": matches,
        "league_news_impact": impact,
        "news_source_freshness": pd.DataFrame(freshness, columns=_freshness_columns()),
    }


def _load_rotowire_rss(season: str, url: str, force: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_path = RAW_EXTERNAL_DIR / "news" / season / "rotowire_nfl_rss.xml"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    status = "cached"
    try:
        if force or not cache_path.exists():
            response = requests.get(url, timeout=30, headers={"User-Agent": "Fantasy-Dominator/0.1"})
            response.raise_for_status()
            cache_path.write_bytes(response.content)
            status = "refreshed"
        xml_text = cache_path.read_text(encoding="utf-8", errors="replace")
        return _parse_rotowire_rss(xml_text, url), _freshness("rotowire_rss", "nfl_player_news", status, url, cache_path)
    except Exception as exc:
        return [], _freshness("rotowire_rss", "nfl_player_news", f"unavailable:{type(exc).__name__}", url, cache_path)


def _parse_rotowire_rss(xml_text: str, url: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _text(item, "title")
        link = _text(item, "link")
        summary = _text(item, "description")
        published_at = _parse_datetime(_text(item, "pubDate"))
        player = _infer_player_name(title, summary)
        rows.append(
            {
                "source": "rotowire_rss",
                "event_id": _event_id("rotowire_rss", link or title or summary),
                "event_type": "player_news",
                "published_at": published_at,
                "title": title,
                "summary": _clean_summary(summary),
                "url": link,
                "player_id": "",
                "player_name": player,
                "team": "",
                "position": "",
                "source_trace": url,
            }
        )
    return rows


def _load_sleeper_trending(
    season: str,
    trend_type: str,
    api: SleeperAPI,
    players: dict[str, dict[str, Any]],
    force: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_url = f"{api.BASE_URL}/players/nfl/trending/{trend_type}"
    try:
        trending = api.trending_players(season, trend_type, force=force)
        rows = []
        for item in trending:
            player_id = str(item.get("player_id") or "")
            count = item.get("count", "")
            name = player_name(players, player_id)
            rows.append(
                {
                    "source": "sleeper_trending",
                    "event_id": f"sleeper_trending_{trend_type}_{player_id}",
                    "event_type": f"trending_{trend_type}",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "title": f"Sleeper trending {trend_type}: {name}",
                    "summary": f"{name} is trending as a {trend_type} with count {count}.",
                    "url": source_url,
                    "player_id": player_id,
                    "player_name": name,
                    "team": player_field(players, player_id, "team"),
                    "position": player_field(players, player_id, "position"),
                    "source_trace": source_url,
                }
            )
        return rows, _freshness("sleeper_trending", f"trending_{trend_type}", "refreshed_or_cached", source_url, RAW_EXTERNAL_DIR / "sleeper" / season / f"trending_{trend_type}.json")
    except Exception as exc:
        return [], _freshness("sleeper_trending", f"trending_{trend_type}", f"unavailable:{type(exc).__name__}", source_url, RAW_EXTERNAL_DIR / "sleeper" / season / f"trending_{trend_type}.json")


def _match_news_events(news_events: pd.DataFrame, players: dict[str, dict[str, Any]]) -> pd.DataFrame:
    if news_events.empty:
        return pd.DataFrame([], columns=_match_columns())

    name_index: dict[str, list[str]] = {}
    for player_id, data in players.items():
        full_name = str(data.get("full_name") or "").strip()
        if full_name:
            name_index.setdefault(_normalize_name(full_name), []).append(str(player_id))

    rows: list[dict[str, Any]] = []
    for _, event in news_events.iterrows():
        event_player_id = str(event.get("player_id") or "")
        candidates = [event_player_id] if event_player_id else name_index.get(_normalize_name(event.get("player_name")), [])
        candidates = [candidate for candidate in candidates if candidate in players]
        is_ambiguous = len(set(candidates)) > 1
        matched_id = candidates[0] if candidates and not is_ambiguous else ""
        match_method = "sleeper_id" if event_player_id and matched_id else "normalized_name" if matched_id else "no_match"
        rows.append(
            {
                "event_id": event.get("event_id", ""),
                "source": event.get("source", ""),
                "input_player_name": event.get("player_name", ""),
                "player_id": matched_id,
                "matched_player_name": player_name(players, matched_id) if matched_id else "",
                "match_method": "ambiguous_name" if is_ambiguous else match_method,
                "match_confidence": "high" if match_method == "sleeper_id" else "medium" if matched_id else "low",
                "is_ambiguous": is_ambiguous,
                "source_trace": event.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_match_columns())


def _build_league_news_impact(
    news_events: pd.DataFrame,
    matches: pd.DataFrame,
    teams: pd.DataFrame,
    roster_players: pd.DataFrame,
) -> pd.DataFrame:
    if news_events.empty or matches.empty:
        return pd.DataFrame([], columns=_impact_columns())

    team_names = {
        str(row.get("roster_id")): row.get("team_name") or row.get("display_name") or ""
        for _, row in teams.fillna("").iterrows()
    }
    ownership: dict[str, dict[str, Any]] = {}
    for _, row in roster_players.fillna("").iterrows():
        player_id = str(row.get("player_id") or "")
        if player_id:
            ownership[player_id] = {
                "roster_id": row.get("roster_id", ""),
                "team_name": row.get("team_name", "") or team_names.get(str(row.get("roster_id")), ""),
                "player_name": row.get("player_name", ""),
                "position": row.get("position", ""),
            }

    event_lookup = {str(row.get("event_id")): row for _, row in news_events.fillna("").iterrows()}
    rows: list[dict[str, Any]] = []
    for _, match in matches.fillna("").iterrows():
        if str(match.get("is_ambiguous")).lower() == "true":
            continue
        event = event_lookup.get(str(match.get("event_id")), {})
        player_id = str(match.get("player_id") or "")
        owner = ownership.get(player_id, {})
        event_type = str(event.get("event_type") or "")
        impact_type = _impact_type(event_type, event.get("title", ""), event.get("summary", ""), bool(owner))
        rows.append(
            {
                "event_id": event.get("event_id", ""),
                "source": event.get("source", ""),
                "published_at": event.get("published_at", ""),
                "player_id": player_id,
                "player_name": match.get("matched_player_name") or event.get("player_name", ""),
                "roster_id": owner.get("roster_id", ""),
                "team_name": owner.get("team_name", ""),
                "impact_type": impact_type,
                "evidence": event.get("title", "") or event.get("summary", ""),
                "risk": _impact_risk(impact_type),
                "confidence": match.get("match_confidence", "low"),
                "source_trace": event.get("source_trace", ""),
            }
        )
    return pd.DataFrame(rows, columns=_impact_columns())


def _impact_type(event_type: str, title: Any, summary: Any, is_rostered: bool) -> str:
    text = f"{title} {summary}".lower()
    if event_type == "trending_add":
        return "market_heat" if is_rostered else "waiver_watch"
    if event_type == "trending_drop":
        return "sell_pressure" if is_rostered else "market_cooling"
    if any(word in text for word in ["injury", "injured", "hamstring", "knee", "ankle", "questionable", "ir"]):
        return "injury_risk"
    if any(word in text for word in ["sign", "extension", "contract", "trade", "role", "starter"]):
        return "role_or_value_change"
    return "monitor"


def _impact_risk(impact_type: str) -> str:
    if impact_type in {"injury_risk", "sell_pressure"}:
        return "medium"
    if impact_type in {"waiver_watch", "market_cooling"}:
        return "low"
    return "medium"


def _infer_player_name(title: str, summary: str) -> str:
    text = title.strip()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    match = re.match(r"^([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,2})\b", text)
    if match:
        return match.group(1).strip()
    summary_match = re.search(r"\b([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,2})\b", summary or "")
    return summary_match.group(1).strip() if summary_match else ""


def _clean_summary(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _text(item: ET.Element, tag: str) -> str:
    found = item.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _parse_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return value


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _event_id(source: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{source}_{digest}"


def _freshness(source: str, dataset: str, status: str, url: str, cache_path: Path | None) -> dict[str, Any]:
    return {
        "source": source,
        "dataset": dataset,
        "status": status,
        "source_url": url,
        "cache_path": str(cache_path.as_posix()) if cache_path else "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "row_count": 0,
    }


def _news_event_columns() -> list[str]:
    return ["source", "event_id", "event_type", "published_at", "title", "summary", "url", "player_id", "player_name", "team", "position", "source_trace"]


def _match_columns() -> list[str]:
    return ["event_id", "source", "input_player_name", "player_id", "matched_player_name", "match_method", "match_confidence", "is_ambiguous", "source_trace"]


def _impact_columns() -> list[str]:
    return ["event_id", "source", "published_at", "player_id", "player_name", "roster_id", "team_name", "impact_type", "evidence", "risk", "confidence", "source_trace"]


def _freshness_columns() -> list[str]:
    return ["source", "dataset", "status", "source_url", "cache_path", "checked_at", "row_count"]
