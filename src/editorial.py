from __future__ import annotations

"""Build the reader-facing editorial issue from canonical league facts.

The browser surface should not have to infer an editorial hierarchy from a pile of
tables.  This module is the small, deterministic bridge between the data room and
the publication facade.  A future writer can polish these story objects, but it
cannot remove the evidence, source trace, confidence, or risk that came with them.
"""

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .personas import persona_metadata


def build_editorial_issue(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    analysis: Mapping[str, Any] | None = None,
    *,
    league_id: str = "",
    my_roster_id: int | str | None = None,
    my_team_name: str = "",
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile one personalized issue from the current league snapshot.

    The output intentionally contains presentation-ready prose plus structured
    evidence.  It is safe to render as JSON and gives the UI a stable contract
    while the underlying CSV tables continue to evolve.
    """

    analysis = analysis or {}
    config = config or {}
    metadata = _first(tables, "refresh_metadata")
    as_of = _text(metadata.get("generated_at"))
    current_season = _text(metadata.get("current_season")) or _text(config.get("current_season"))
    priority_rows = _sorted_rows(tables, "today_priority_board", "priority_score")
    scoped_priority = _prioritize_team(priority_rows, my_roster_id)
    lead_row = scoped_priority[0] if scoped_priority else None
    writer_preferences = config.get("writer_preferences") or (config.get("context") or {}).get("writer_preferences") or {}
    reporter = persona_metadata(writer_preferences)
    persona_id = reporter["persona_id"]
    lead = _priority_story(lead_row, is_lead=True, persona_id=persona_id) if lead_row else _quiet_story(my_team_name)

    stories: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = {_story_key(lead)}
    for row in scoped_priority[1:]:
        story = _priority_story(row, persona_id=persona_id)
        if _append_unique(stories, seen, story, limit=2):
            continue

    news_rows = _sorted_news(tables, my_roster_id)
    if news_rows:
        _append_unique(stories, seen, _news_story(news_rows[0]), limit=3)

    manager_rows = _sorted_rows(tables, "manager_behavior_signals", "trade_activity_score")
    manager_row = _first_matching(manager_rows, my_roster_id) or (manager_rows[0] if manager_rows else None)
    if manager_row:
        _append_unique(stories, seen, _manager_story(manager_row), limit=4)

    source_health = _source_health(tables)
    source_summary = _source_summary(source_health)
    signal_summary = {
        "priority_reads": len(priority_rows),
        "market_consensus": len(_rows(tables, "market_consensus_values")),
        "news_signals": len(_rows(tables, "league_news_impact")),
        "manager_profiles": len(_rows(tables, "manager_behavior_signals")),
        "source_count": len(source_health),
    }
    article_modes = _article_modes(analysis)
    edition_label = _edition_label(as_of)
    team_label = my_team_name or "Your team"

    return {
        "schema_version": "issue_v1",
        "issue_id": _issue_id(as_of, current_season),
        "league_id": str(league_id or ""),
        "season": current_season,
        "title": "The Front Office",
        "kicker": "Personal league edition",
        "edition_label": edition_label,
        "as_of": as_of,
        "as_of_label": f"As of {edition_label}" if edition_label else "As of the latest refresh",
        "team_name": team_label,
        "headline": lead["headline"],
        "dek": _issue_dek(team_label, lead, signal_summary, persona_id),
        "writer_mode": _writer_mode_label(article_modes),
        "article_modes": article_modes,
        "reporter_persona": reporter,
        "freshness_label": source_summary["label"],
        "lead": lead,
        "stories": stories,
        "signal_summary": signal_summary,
        "source_health": source_health,
        "source_health_summary": source_summary,
    }


def _priority_story(
    row: Mapping[str, Any] | None,
    *,
    is_lead: bool = False,
    persona_id: str = "front_office",
) -> dict[str, Any]:
    row = row or {}
    action = _text(row.get("item_type") or row.get("action_label")).lower()
    label = _text(row.get("item_type_label") or row.get("consumer_label")) or "Model read"
    entity_type = _text(row.get("entity_type")) or "player"
    entity_id = _text(row.get("entity_id") or row.get("player_id"))
    entity_name = _text(row.get("entity_name") or row.get("player_name")) or "Unknown asset"
    team_name = _text(row.get("team_name"))
    kind = _kind_for_action(action)
    headline = _priority_headline(entity_name, kind, persona_id)
    why = _text(row.get("why")) or "The model has a read, but the written rationale is thin."
    evidence = _text(row.get("evidence"))
    risk = _text(row.get("risk")) or "Review the evidence before acting."
    confidence = _confidence(row.get("confidence"))
    claims = _claims_from_row(row)
    sources = _source_links(row.get("source_trace"))
    return {
        "story_id": f"priority:{entity_type}:{entity_id or entity_name}",
        "story_type": kind,
        "eyebrow": label,
        "headline": headline,
        "dek": why,
        "action": _action_line(kind, persona_id),
        "watchout": risk,
        "confidence": confidence,
        "priority_score": _number_or_text(row.get("priority_score")),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "team_name": team_name,
        "anchor": _anchor(entity_type, entity_id),
        "claims": claims,
        "evidence": evidence or why,
        "sources": sources,
        "is_lead": is_lead,
    }


def _news_story(row: Mapping[str, Any]) -> dict[str, Any]:
    player_name = _text(row.get("player_name")) or "A league player"
    impact = _text(row.get("impact_type")) or "league signal"
    impact_label = _human_label(impact)
    confidence = _confidence(row.get("confidence"))
    evidence = _text(row.get("evidence")) or f"{player_name}: {impact_label}."
    return {
        "story_id": f"news:{_text(row.get('event_id')) or player_name}",
        "story_type": "news",
        "eyebrow": "News desk",
        "headline": f"{player_name} is a {impact_label.lower()} for the league",
        "dek": evidence,
        "action": "Move: check the affected roster and price before the next transaction window.",
        "watchout": _text(row.get("risk")) or "News is a prompt for research, not a conclusion.",
        "confidence": confidence,
        "priority_score": "",
        "entity_type": "player",
        "entity_id": _text(row.get("player_id")),
        "entity_name": player_name,
        "team_name": _text(row.get("team_name")),
        "anchor": _anchor("player", _text(row.get("player_id"))),
        "claims": [
            {"label": "Impact", "value": impact_label},
            {"label": "Published", "value": _short_date(row.get("published_at"))},
        ],
        "evidence": evidence,
        "sources": _source_links(row.get("source_trace")),
        "is_lead": False,
    }


def _manager_story(row: Mapping[str, Any]) -> dict[str, Any]:
    team_name = _text(row.get("team_name")) or "A league manager"
    label = _text(row.get("plain_language_label")) or "observed market behavior"
    evidence = _text(row.get("evidence")) or "Observed transaction behavior is sparse."
    claims = [
        {"label": "Read", "value": label},
        {"label": "Trade activity", "value": _number_or_text(row.get("trade_activity_score"))},
        {"label": "Pick posture", "value": _pick_posture(row)},
    ]
    return {
        "story_id": f"manager:{_text(row.get('roster_id')) or team_name}",
        "story_type": "manager",
        "eyebrow": "Manager lens",
        "headline": f"{team_name} is trading like a {label}",
        "dek": "Observed behavior gives the next conversation a shape before the first offer is sent.",
        "action": "Move: frame the offer around what this manager actually acquires and protects.",
        "watchout": "A tendency is not a mind read; keep the evidence visible.",
        "confidence": _confidence(row.get("confidence")),
        "priority_score": "",
        "entity_type": "manager",
        "entity_id": _text(row.get("roster_id")),
        "entity_name": team_name,
        "team_name": team_name,
        "anchor": _anchor("manager", _text(row.get("roster_id"))),
        "claims": claims,
        "evidence": evidence,
        "sources": [],
        "is_lead": False,
    }


def _quiet_story(team_name: str) -> dict[str, Any]:
    team_label = team_name or "Your team"
    return {
        "story_id": "quiet:edition",
        "story_type": "quiet",
        "eyebrow": "Edition note",
        "headline": f"No forced moves for {team_label}",
        "dek": "The current snapshot did not produce a high-confidence priority read. That is useful information, not an empty state to hide.",
        "action": "Move: keep the board open and wait for a signal with a real edge.",
        "watchout": "Quiet means no strong signal was found; it does not mean the league is safe.",
        "confidence": "medium",
        "priority_score": "",
        "entity_type": "edition",
        "entity_id": "quiet",
        "entity_name": team_label,
        "team_name": team_label,
        "anchor": "",
        "claims": [],
        "evidence": "No high-priority rows were available in the current snapshot.",
        "sources": [],
        "is_lead": True,
    }


def _rows(tables: Mapping[str, Sequence[Mapping[str, Any]]], name: str) -> list[dict[str, Any]]:
    rows = tables.get(name, []) or []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _first(tables: Mapping[str, Sequence[Mapping[str, Any]]], name: str) -> dict[str, Any]:
    rows = _rows(tables, name)
    return rows[0] if rows else {}


def _sorted_rows(tables: Mapping[str, Sequence[Mapping[str, Any]]], name: str, score_field: str) -> list[dict[str, Any]]:
    rows = _rows(tables, name)
    return sorted(rows, key=lambda row: _number(row.get(score_field)), reverse=True)


def _sorted_news(tables: Mapping[str, Sequence[Mapping[str, Any]]], my_roster_id: int | str | None) -> list[dict[str, Any]]:
    rows = _rows(tables, "league_news_impact")
    if my_roster_id is not None:
        scoped = [row for row in rows if str(row.get("roster_id", "")) == str(my_roster_id)]
        if scoped:
            rows = scoped
    return sorted(rows, key=lambda row: _text(row.get("published_at")), reverse=True)


def _prioritize_team(rows: list[dict[str, Any]], my_roster_id: int | str | None) -> list[dict[str, Any]]:
    if my_roster_id is None:
        return _dedupe_rows(rows)
    mine = [row for row in rows if str(row.get("roster_id", "")) == str(my_roster_id)]
    others = [row for row in rows if str(row.get("roster_id", "")) != str(my_roster_id)]
    return _dedupe_rows(mine + others)


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (_text(row.get("entity_type")) or "entity", _text(row.get("entity_id") or row.get("player_id") or row.get("entity_name")))
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _first_matching(rows: list[dict[str, Any]], roster_id: int | str | None) -> dict[str, Any] | None:
    if roster_id is None:
        return None
    return next((row for row in rows if str(row.get("roster_id", "")) == str(roster_id)), None)


def _append_unique(stories: list[dict[str, Any]], seen: set[tuple[str, str]], story: dict[str, Any], *, limit: int) -> bool:
    if len(stories) >= limit:
        return False
    key = _story_key(story)
    if key in seen:
        return False
    seen.add(key)
    stories.append(story)
    return True


def _story_key(story: Mapping[str, Any]) -> tuple[str, str]:
    return (_text(story.get("entity_type")) or _text(story.get("story_type")), _text(story.get("entity_id") or story.get("entity_name")))


def _kind_for_action(action: str) -> str:
    if "buy" in action or "breakout" in action:
        return "market"
    if "sell" in action:
        return "sell"
    if "hold" in action:
        return "hold"
    if "price" in action:
        return "price"
    return "signal"


def _priority_headline(entity_name: str, kind: str, persona_id: str = "front_office") -> str:
    if persona_id == "scout":
        return {
            "market": f"{entity_name}: the role signal is ahead of the price",
            "sell": f"{entity_name}: the timeline requires a role check",
            "hold": f"{entity_name}: the role supports a patient hold",
            "price": f"{entity_name}: verify the role before you price the asset",
        }.get(kind, f"{entity_name}: the next condition matters")
    if persona_id == "commissioner":
        return {
            "market": f"{entity_name} is becoming everybody's problem",
            "sell": f"{entity_name} is the league's next awkward conversation",
            "hold": f"{entity_name} is not leaving the office without a serious offer",
            "price": f"{entity_name} has entered the league-wide price debate",
        }.get(kind, f"The league has a new angle on {entity_name}")
    if persona_id == "quant":
        return {
            "market": f"{entity_name}: the gap is measurable",
            "sell": f"{entity_name}: the risk-adjusted sell window is open",
            "hold": f"{entity_name}: the numbers support a hold",
            "price": f"{entity_name}: price discovery required",
        }.get(kind, f"{entity_name}: model signal detected")
    if kind == "market":
        return f"{entity_name} is where the market is lagging"
    if kind == "sell":
        return f"The sell window is open on {entity_name}"
    if kind == "hold":
        return f"{entity_name} is a pillar to protect"
    if kind == "price":
        return f"{entity_name} deserves a price check, not a panic"
    return f"The board has a read on {entity_name}"


def _action_line(kind: str, persona_id: str = "front_office") -> str:
    if persona_id == "scout":
        if kind == "market":
            return "Move: confirm the role signal, then price the asset against the timeline."
        if kind == "sell":
            return "Move: test the market while the current role still supports the thesis."
        if kind == "hold":
            return "Move: hold unless the return changes the roster timeline."
    if persona_id == "commissioner":
        if kind == "market":
            return "Move: start the league conversation before someone else notices the angle."
        if kind == "sell":
            return "Move: let the league argue itself into paying for the current story."
        if kind == "hold":
            return "Move: keep the asset unless the return gives the group something to talk about."
    if persona_id == "quant":
        if kind == "market":
            return "Move: compare the market gap with projection confidence before acting."
        if kind == "sell":
            return "Move: price the downside, then test whether the market still clears the threshold."
        if kind == "hold":
            return "Move: hold while the measured edge remains positive."
    if kind == "market":
        return "Move: start price discovery before turning the signal into an offer."
    if kind == "sell":
        return "Move: shop the asset while the market still pays for the current role."
    if kind == "hold":
        return "Move: hold unless the return clears the roster-pillar premium."
    if kind == "price":
        return "Move: price the asset against the market before accepting the first offer."
    return "Move: open the evidence before acting."


def _claims_from_row(row: Mapping[str, Any]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    labels = {
        "ppg": "Projected PPG",
        "points": "Projected points",
        "projection": "Projection confidence",
        "market": "Market value",
        "team_shape": "Team shape",
        "manager": "Manager read",
        "news": "News context",
    }
    for part in _text(row.get("evidence")).split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value:
            claims.append({"label": labels.get(key, _human_label(key)), "value": value})
    if not claims and _text(row.get("why")):
        claims.append({"label": "Analyst read", "value": _text(row.get("why"))})
    return claims[:6]


def _source_health(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    names = {
        "source_freshness": "Market and usage",
        "news_source_freshness": "News desk",
        "projection_source_freshness": "Projection desk",
    }
    output: list[dict[str, Any]] = []
    for table_name, label in names.items():
        for row in _rows(tables, table_name):
            status = _text(row.get("status")) or "unknown"
            source = _text(row.get("source"))
            dataset = _text(row.get("dataset"))
            # A stale cache retained after a failed refetch is useful evidence,
            # but it must not be presented as current source material.
            healthy = status in {"cached", "refreshed", "complete", "available"}
            output.append(
                {
                    "label": _source_health_label(source, dataset, label),
                    "source": source or "internal",
                    "dataset": dataset or label,
                    "status": status,
                    "status_label": "Current" if healthy else "Limited",
                    "healthy": healthy,
                    "checked_at": _text(row.get("checked_at")),
                    "row_count": _number_or_text(row.get("row_count")),
                    "source_url": _text(row.get("source_url")),
                }
            )
    return output


def _source_health_label(source: str, dataset: str, fallback: str) -> str:
    """Give the reader a compact, human-readable source receipt label."""

    source_names = {
        "rotowire_rss": "RotoWire",
        "sleeper_trending": "Sleeper trending",
        "dynastyprocess": "DynastyProcess",
        "nflverse": "nflverse",
        "fantasy_nerds": "Fantasy Nerds",
    }
    dataset_names = {
        "nfl_player_news": "NFL player news",
        "trending_add": "Trending adds",
        "trending_drop": "Trending drops",
        "player_stats": "Player stats",
        "market_values": "Market values",
        "pick_values": "Pick values",
    }
    source_label = source_names.get(source, _human_label(source)) if source else ""
    dataset_label = dataset_names.get(dataset, _human_label(dataset)) if dataset else ""
    if source_label and dataset_label:
        return f"{source_label} · {dataset_label}"
    return source_label or dataset_label or fallback


def _source_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    healthy = sum(1 for row in rows if row.get("healthy"))
    total = len(rows)
    if not total:
        label = "Freshness unavailable"
    elif healthy == total:
        label = f"{healthy}/{total} sources current"
    else:
        label = f"{healthy}/{total} sources current · read the limits"
    return {"healthy": healthy, "total": total, "label": label}


def _issue_dek(team_name: str, lead: Mapping[str, Any], summary: Mapping[str, Any], persona_id: str = "front_office") -> str:
    if lead.get("story_type") == "quiet":
        return f"{team_name} has no forced move in this edition. The board is quiet because no high-confidence edge cleared the threshold."
    if persona_id == "scout":
        return (
            f"{team_name} edition: the role and timeline put {lead.get('entity_name', 'the lead asset')} at the center. "
            f"The board holds {summary.get('priority_reads', 0)} ranked signals to test against what must be true next."
        )
    if persona_id == "commissioner":
        return (
            f"{team_name} edition: {lead.get('entity_name', 'the lead asset')} is the day's most interesting league problem. "
            f"There are {summary.get('priority_reads', 0)} ranked signals beneath the group-chat drama."
        )
    if persona_id == "quant":
        return (
            f"{team_name} edition: {lead.get('entity_name', 'the lead asset')} is the top measured read. "
            f"The board contains {summary.get('priority_reads', 0)} ranked signals across market, news, and manager behavior."
        )
    return (
        f"{team_name} edition: {lead.get('entity_name', 'the lead asset')} leads the read. "
        f"The board holds {summary.get('priority_reads', 0)} ranked signals across market, news, and manager behavior."
    )


def _article_modes(analysis: Mapping[str, Any]) -> dict[str, str]:
    fields = {
        "daily_brief": "dailyGmBriefMode",
        "team_report": "teamReportMode",
        "market_watch": "marketWatchMode",
        "trade_desk": "tradeDeskReadMode",
        "manager_intel": "managerIntelMode",
    }
    return {
        key: _text(analysis.get(field)) or "deterministic_template"
        for key, field in fields.items()
    }


def _writer_mode_label(article_modes: Mapping[str, str]) -> str:
    modes = set(article_modes.values())
    has_llm = "automatic_llm" in modes
    has_template = "deterministic_template" in modes
    if has_llm and has_template:
        return "Mixed edition"
    if has_llm:
        return "Analyst-written"
    return "Evidence-led template"


def _issue_id(as_of: str, season: str) -> str:
    date_part = as_of[:10] if len(as_of) >= 10 else "latest"
    return f"{season or 'season'}-{date_part}"


def _edition_label(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    return parsed.strftime("%b %-d, %Y") if not _is_windows() else parsed.strftime("%b %#d, %Y")


def _short_date(value: Any) -> str:
    parsed = _parse_datetime(_text(value))
    return parsed.strftime("%b %-d") if parsed is not None and not _is_windows() else (parsed.strftime("%b %#d") if parsed is not None else _text(value))


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_windows() -> bool:
    # The production runtime is Windows today, while the formatter remains easy
    # to exercise on Unix CI without importing platform-specific dependencies.
    return __import__("os").name == "nt"


def _anchor(entity_type: str, entity_id: str) -> str:
    if not entity_id:
        return ""
    if entity_type == "manager":
        return f"team-{entity_id}"
    if entity_type == "player":
        return f"player-{entity_id}"
    return ""


def _source_links(value: Any) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for raw in _text(value).split(";"):
        url = raw.strip()
        if not url.startswith(("http://", "https://")):
            continue
        output.append({"label": _source_label(url), "url": url})
    return output[:5]


def _source_label(url: str) -> str:
    lowered = url.lower()
    if "nflverse" in lowered:
        return "nflverse"
    if "dynastyprocess" in lowered:
        return "DynastyProcess"
    if "rotowire" in lowered:
        return "RotoWire"
    if "sleeper" in lowered:
        return "Sleeper"
    return url.split("/")[2] if len(url.split("/")) > 2 else "source"


def _pick_posture(row: Mapping[str, Any]) -> str:
    buyer = _number(row.get("pick_buyer_score"))
    seller = _number(row.get("pick_seller_score"))
    if buyer > seller:
        return "pick buyer"
    if seller > buyer:
        return "pick seller"
    return "balanced picks"


def _human_label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _confidence(value: Any) -> str:
    value = _text(value).lower()
    return value if value in {"high", "medium", "low"} else "medium"


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _number_or_text(value: Any) -> str | float:
    text = _text(value)
    if not text:
        return ""
    numeric = _number(text)
    return int(numeric) if numeric.is_integer() else numeric


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
