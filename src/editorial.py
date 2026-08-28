from __future__ import annotations

"""Build the reader-facing editorial issue from canonical league facts.

The browser surface should not have to infer an editorial hierarchy from a pile of
tables.  This module is the small, deterministic bridge between the data room and
the publication facade.  A future writer can polish these story objects, but it
cannot remove the evidence, source trace, confidence, or risk that came with them.
"""

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .availability import availability_note, baseline_ppg_label, current_availability_status
from .personas import front_office_metadata, persona_metadata, reporter_lineup


PUBLICATION_TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "daily_brief": {
        "template_id": "morning-ledger",
        "label": "Morning ledger",
        "layout": "feature",
        "section": "Front page",
        "list_preview_items": 3,
    },
    "team_report": {
        "template_id": "team-notebook",
        "label": "Team notebook",
        "layout": "wide",
        "section": "Your team",
        "list_preview_items": 3,
    },
    "market_watch": {
        "template_id": "market-ticker",
        "label": "Market ticker",
        "layout": "rail",
        "section": "Market",
        "list_preview_items": 3,
    },
    "horizon_watch": {
        "template_id": "four-window-ledger",
        "label": "Four-window ledger",
        "layout": "wide",
        "section": "Market",
        "list_preview_items": 4,
    },
    "trade_desk": {
        "template_id": "trade-desk",
        "label": "Trade desk",
        "layout": "rail",
        "section": "Trades",
        "list_preview_items": 3,
    },
    "manager_intel": {
        "template_id": "manager-dossier",
        "label": "Manager dossier",
        "layout": "wide",
        "section": "League",
        "list_preview_items": 3,
    },
}


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
    reporter = persona_metadata(writer_preferences, "daily_brief")
    persona_id = reporter["persona_id"]
    lead = (
        _priority_story(lead_row, is_lead=True, persona_id=persona_id, writer_preferences=writer_preferences)
        if lead_row
        else _quiet_story(my_team_name, writer_preferences)
    )

    stories: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = {_story_key(lead)}
    for row in scoped_priority[1:]:
        story = _priority_story(row, persona_id=persona_id, writer_preferences=writer_preferences)
        if _append_unique(stories, seen, story, limit=2):
            continue

    league_news_rows = _league_news_rows(tables, league_id)
    news_rows = _sorted_news(tables, my_roster_id, league_id)
    if news_rows:
        _append_unique(stories, seen, _news_story(news_rows[0], writer_preferences), limit=3)
    latest_news_published_at = max(
        (_text(row.get("published_at")) for row in league_news_rows if _text(row.get("published_at"))),
        default="",
    )

    manager_rows = _sorted_rows(tables, "manager_behavior_signals", "trade_activity_score")
    # A personalized edition must never turn a missing roster join into the
    # first manager in the file. The exact roster is the identity boundary;
    # absence is a quiet/unavailable read, not permission to guess.
    manager_row = _first_matching(manager_rows, my_roster_id)
    manager_dossiers = [
        dict(row)
        for row in (analysis.get("managerDossierItems") or analysis.get("manager_dossiers") or [])
        if isinstance(row, Mapping)
    ]
    manager_dossier = _first_matching(manager_dossiers, my_roster_id)
    if manager_dossier:
        _append_unique(stories, seen, _manager_dossier_story(manager_dossier, writer_preferences), limit=4)
    elif manager_row:
        _append_unique(stories, seen, _manager_story(manager_row, writer_preferences), limit=4)
    manager_trade_profiles = _manager_trade_profile_rows(config)
    custom_manager_profile = _select_manager_trade_profile(
        manager_trade_profiles,
        manager_rows,
        my_roster_id,
    )
    if custom_manager_profile:
        _append_unique(stories, seen, _manager_profile_story(custom_manager_profile, writer_preferences), limit=5)

    source_health = _source_health(tables)
    source_summary = _source_summary(source_health)
    signal_summary = {
        "priority_reads": len(priority_rows),
        "market_consensus": len(_rows(tables, "market_consensus_values")),
        "news_signals": len(league_news_rows),
        "manager_profiles": len(_rows(tables, "manager_behavior_signals")),
        "custom_manager_profiles": len(manager_trade_profiles),
        "source_count": len(source_health),
    }
    article_modes = _article_modes(analysis)
    publication_articles = _publication_articles(analysis, writer_preferences)
    newsroom_conversation = _newsroom_conversation(publication_articles)
    newsroom_edges = _newsroom_edges(newsroom_conversation)
    claim_conflicts = _newsroom_claim_conflicts(newsroom_conversation)
    newsroom_summary = _newsroom_summary(
        newsroom_conversation,
        newsroom_edges,
        article_modes,
        claim_conflicts=claim_conflicts,
    )
    primary_publication = next(
        (article for article in publication_articles if article.get("key") == "daily_brief"),
        publication_articles[0] if publication_articles else None,
    )
    issue_reporter = (
        primary_publication.get("reporter_persona")
        if isinstance(primary_publication, Mapping)
        else reporter
    ) or reporter
    assigned_issue_reporter = (
        primary_publication.get("assigned_reporter_persona")
        if isinstance(primary_publication, Mapping)
        else reporter
    ) or reporter
    if primary_publication and isinstance(primary_publication.get("story_fragment"), Mapping):
        lead = _publication_lead_story(primary_publication, lead)
    if primary_publication and primary_publication.get("mode") == "deterministic_template":
        lead = _neutralize_reader_story(lead, issue_reporter, reporter)
        stories = [_neutralize_reader_story(story, issue_reporter, reporter) for story in stories]
    edition_label = _edition_label(as_of)
    team_label = my_team_name or "Your team"
    front_page_panels = _front_page_panels(
        tables,
        analysis,
        league_id=league_id,
        my_roster_id=my_roster_id,
        my_team_name=team_label,
        current_season=current_season,
        writer_preferences=writer_preferences,
        publication_articles=publication_articles,
    )
    question_prompts = [
        {
            "question": "What changed?",
            "answer": f"{signal_summary['news_signals']} news signals and {signal_summary['priority_reads']} ranked reads are in this edition.",
            "route": "#view-news",
        },
        {
            "question": "Why does it matter to my team?",
            "answer": f"The lead read is {lead.get('entity_name', 'the current board')} for {team_label}.",
            "route": "#view-my-team",
        },
        {
            "question": "Who should I study next?",
            "answer": f"{signal_summary['manager_profiles']} manager profiles and {signal_summary['custom_manager_profiles']} private lenses are available.",
            "route": "#view-league",
        },
        {
            "question": "What evidence is weak or stale?",
            "answer": source_summary["label"],
            "route": "#view-data-room",
        },
    ]

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
        "dek": _issue_dek(team_label, lead, signal_summary, issue_reporter.get("persona_id", persona_id)),
        "writer_mode": _writer_mode_label(article_modes),
        "article_modes": article_modes,
        "publication_articles": publication_articles,
        "newsroom_conversation": newsroom_conversation,
        "newsroom_edges": newsroom_edges,
        "claim_conflicts": claim_conflicts,
        "newsroom_summary": newsroom_summary,
        "conversation_schema_version": "publication_edges_v1",
        "publication_receipt": {
            "current_count": sum(1 for article in publication_articles if article.get("mode") == "automatic_llm" and article.get("publication_status") == "approved"),
            "available_count": len(publication_articles),
            "published_count": sum(1 for article in publication_articles if article.get("publication_status") == "approved"),
            "held_count": sum(1 for article in publication_articles if article.get("publication_status") == "held"),
            "expected_count": len(article_modes),
        },
        "editorial_review": {
            "editor": "The Desk Editor",
            "status": "held" if any(article.get("publication_status") == "held" for article in publication_articles) else "approved",
            "approved_count": sum(1 for article in publication_articles if article.get("publication_status") == "approved"),
            "held_count": sum(1 for article in publication_articles if article.get("publication_status") == "held"),
        },
        "front_page_panels": front_page_panels,
        "question_prompts": question_prompts,
        "reporter_label": "Desk" if primary_publication and primary_publication.get("mode") == "deterministic_template" else "Reporter",
        "reporter_persona": issue_reporter,
        "assigned_reporter_persona": assigned_issue_reporter,
        "reporter_lineup": reporter_lineup(writer_preferences),
        "freshness_label": source_summary["label"],
        "latest_news_published_at": latest_news_published_at,
        "latest_news_label": _short_date(latest_news_published_at) if latest_news_published_at else "Not recorded",
        "lead": lead,
        "stories": stories,
        "signal_summary": signal_summary,
        "source_health": source_health,
        "source_health_summary": source_summary,
    }


def _front_page_panels(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    analysis: Mapping[str, Any],
    *,
    league_id: str = "",
    my_roster_id: int | str | None,
    my_team_name: str,
    current_season: str,
    writer_preferences: Mapping[str, Any] | None = None,
    publication_articles: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build the front-page rails that connect a story to a decision surface.

    These are deterministic editorial teasers, not a second analysis engine.
    Each rail keeps its underlying entity anchor, source trace, and uncertainty
    visible so a future Luna article can add interpretation without replacing
    the data-room path.
    """

    panels = [
        _team_pulse_panel(tables, league_id, my_roster_id, my_team_name, current_season),
        _news_watch_panel(tables, league_id, my_roster_id),
        _market_watch_panel(tables, my_roster_id, league_id=league_id, current_season=current_season),
        _manager_watch_panel(tables, analysis, my_roster_id),
        _reality_check_panel(
            tables,
            league_id,
            my_roster_id,
            current_season,
            packet=analysis.get("realityCheckPacket") if isinstance(analysis, Mapping) else None,
        ),
    ]
    # Front-page rails are deterministic teasers, but they still need a
    # visible information owner. This prevents five anonymous panels from
    # feeling like one generic LLM voice and gives the reader a direct bridge
    # into the corresponding desk article.
    panel_assignments = {
        "team_pulse": "team_report",
        "news_watch": "team_report",
        "market_watch": "market_watch",
        "manager_watch": "manager_intel",
        "reality_check": "reality_check",
    }
    preferences = dict(writer_preferences) if isinstance(writer_preferences, Mapping) else {}
    raw_article_reporters = preferences.get("article_reporters")
    article_reporters = dict(raw_article_reporters) if isinstance(raw_article_reporters, Mapping) else {}
    article_reporters.setdefault("reality_check", "reality_check_riley")
    preferences["article_reporters"] = article_reporters
    publication_by_key = {
        _text(article.get("key")): article
        for article in publication_articles
        if isinstance(article, Mapping) and _text(article.get("key"))
    }
    for panel in panels:
        article_key = panel_assignments.get(str(panel.get("key") or ""), "")
        reporter = persona_metadata(preferences, article_key)
        panel["article_key"] = article_key
        panel["reporter_id"] = reporter["persona_id"]
        panel["reporter_name"] = reporter["name"]
        panel["reporter"] = reporter
        panel["decision_question"] = reporter["question"]
        panel["information_contract"] = reporter["evidence_scope"]
        publication = publication_by_key.get(article_key)
        fragment = publication.get("story_fragment") if isinstance(publication, Mapping) else None
        panel["writer_fragment"] = (
            dict(fragment)
            if isinstance(fragment, Mapping)
            else _unpublished_writer_fragment(article_key, reporter)
        )
    return panels


def _reality_check_panel(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    league_id: str,
    my_roster_id: int | str | None,
    current_season: str,
    *,
    packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Expose deterministic limitations before a writer turns a row into a call.

    Riley is a verification desk, not a second ranking model. This rail is
    intentionally small: it surfaces current availability conflicts, missing
    roster joins, and limited source receipts that can invalidate an otherwise
    attractive headline.
    """

    packet = packet if isinstance(packet, Mapping) else {}
    packet_checks = packet.get("checks") if isinstance(packet.get("checks"), list) else []
    if packet_checks:
        flagged = [
            _front_page_item(
                title=_text(check.get("entity_name")) + (f" · {_text(check.get('title'))}" if _text(check.get("title")) else ""),
                summary=_text(check.get("detail")) or "A deterministic limitation needs review before action.",
                meta=f"{_text(check.get('severity')) or 'review'} · {_text(check.get('source_table')) or 'source receipt'}",
                anchor=(
                    _anchor("player", _text(check.get("entity_id")))
                    if _text(check.get("entity_id"))
                    else "view-data-room"
                ),
                evidence=(
                    f"{_text(check.get('source_table')) or 'source receipt'}; "
                    f"{_text(check.get('source_trace')) or 'trace unavailable'}; "
                    f"evidence_ids={','.join(str(value) for value in (check.get('evidence_ids') or []) if str(value).strip())}"
                ),
                tone="news",
            )
            for check in packet_checks
            if isinstance(check, Mapping)
        ]
        roster_count = int(packet.get("roster_rows_checked") or 0)
        source_limited_count = sum(
            1
            for check in packet_checks
            if isinstance(check, Mapping) and str(check.get("check_id") or "").startswith("source.")
        )
        return {
            "key": "reality_check",
            "eyebrow": "Reality Check Riley",
            "title": "What deserves skepticism",
            "dek": _text(packet.get("summary")) or f"{len(flagged)} deterministic limitation(s) flagged for this exact roster.",
            "facts": [
                {"label": "Roster rows checked", "value": roster_count},
                {"label": "Actionable rows", "value": packet.get("actionable_player_rows_checked", "not recorded")},
                {"label": "Flagged", "value": len(flagged)},
                {"label": "Source limits", "value": source_limited_count},
                {"label": "Market quality", "value": (packet.get("market_quality") or {}).get("status", "not recorded")},
            ],
            "items": flagged[:4],
            "route": "#view-data-room",
            "route_label": "Open the proof",
            "uncertainty": "This is a persisted deterministic verification packet spanning the selected roster and actionable league player universe. It can limit a claim and identify a join to inspect; it does not create a new ranking or replace the source receipt.",
            "source_trace": ";".join(str(value) for value in (packet.get("source_tables") or []) if str(value).strip()) or "reality_check",
            "packet_fingerprint": _text(packet.get("fingerprint")),
            "packet_generated_at": _text(packet.get("generated_at")),
            "tone": "news",
        }

    roster = [
        dict(row)
        for row in _scope_rows(_rows(tables, "roster_players"), league_id=league_id, season=current_season)
        if _same_id(row.get("roster_id"), my_roster_id)
    ]
    dossiers = [
        dict(row)
        for row in _scope_rows(_rows(tables, "player_dossiers"), league_id=league_id, season=current_season)
        if _same_id(row.get("roster_id"), my_roster_id)
    ]
    dossier_ids = {_text(row.get("player_id")) for row in dossiers if _text(row.get("player_id"))}
    flagged: list[dict[str, Any]] = []
    for row in roster:
        player_id = _text(row.get("player_id"))
        player_name = _text(row.get("player_name")) or player_id or "Roster player"
        status = current_availability_status(row)
        if status == "no_current_nfl_team":
            flagged.append(
                _front_page_item(
                    title=f"{player_name} · no current NFL team",
                    summary="Historical production may be useful conditionally, but next-game and rest-of-season action should remain unavailable until a team and role are confirmed.",
                    meta="availability boundary · conditional history only",
                    anchor=_anchor("player", player_id),
                    evidence=_front_page_evidence(row, "roster_players"),
                    tone="news",
                )
            )
        elif status.startswith("injury_"):
            flagged.append(
                _front_page_item(
                    title=f"{player_name} · {status.replace('injury_', '')}",
                    summary=f"{availability_note(row)}. Any season baseline remains conditional on availability; recovery timing is not modeled here.",
                    meta="availability boundary · verify before acting",
                    anchor=_anchor("player", player_id),
                    evidence=_front_page_evidence(row, "roster_players"),
                    tone="news",
                )
            )
        if player_id and dossiers and player_id not in dossier_ids:
            flagged.append(
                _front_page_item(
                    title=f"{player_name} · dossier join missing",
                    summary="The roster row is present, but its player dossier is not joined to this exact Sleeper player ID. Do not use a missing dossier as a zero-value signal.",
                    meta="identity boundary · join requires review",
                    anchor=_anchor("player", player_id),
                    evidence=_front_page_evidence(row, "roster_players"),
                    tone="news",
                )
            )
    health = _source_health(tables)
    limited_sources = [row for row in health if not row.get("healthy")]
    if limited_sources and not flagged:
        flagged.append(
            _front_page_item(
                title="A source receipt is limited",
                summary="The edition remains readable, but at least one source is cached, unavailable, or otherwise limited. Treat the affected reads as context until the receipt is current.",
                meta="source health · inspect the Data Room",
                anchor="view-data-room",
                evidence="source_freshness;news_source_freshness;projection_source_freshness",
                tone="news",
            )
        )
    return {
        "key": "reality_check",
        "eyebrow": "Reality Check Riley",
        "title": "What deserves skepticism",
        "dek": f"{len(flagged)} limitation{'s' if len(flagged) != 1 else ''} flagged for this exact roster; a clean rail is a receipt, not a guarantee.",
        "facts": [
            {"label": "Roster rows checked", "value": len(roster)},
            {"label": "Flagged", "value": len(flagged)},
            {"label": "Limited sources", "value": len(limited_sources)},
            {"label": "Market quality", "value": "not recorded"},
        ],
        "items": flagged[:4],
        "route": "#view-data-room",
        "route_label": "Open the proof",
        "uncertainty": "This is a deterministic verification rail. It can limit a claim and identify a join to inspect; it does not create a new ranking or replace the source receipt.",
        "source_trace": "roster_players;player_dossiers;source_freshness;news_source_freshness;projection_source_freshness",
        "tone": "news",
    }


def _team_pulse_panel(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    league_id: str,
    my_roster_id: int | str | None,
    my_team_name: str,
    current_season: str,
) -> dict[str, Any]:
    scoped_roster_rows = _scope_rows(
        _rows(tables, "roster_players"),
        league_id=league_id,
        season=current_season,
    )
    roster = [row for row in scoped_roster_rows if _same_id(row.get("roster_id"), my_roster_id)]
    scoped_dossiers = _scope_rows(
        _rows(tables, "player_dossiers"),
        league_id=league_id,
        season=current_season,
    )
    roster_player_ids = {_text(row.get("player_id")) for row in roster if _text(row.get("player_id"))}
    dossiers = [
        row for row in scoped_dossiers
        if _same_id(row.get("roster_id"), my_roster_id)
        and (not roster_player_ids or _text(row.get("player_id")) in roster_player_ids)
    ] if roster else []
    news = [
        row for row in _league_news_rows(tables, league_id)
        if _same_id(row.get("roster_id"), my_roster_id)
        and (not league_id or not _text(row.get("league_id")) or _same_id(row.get("league_id"), league_id))
    ]
    matchups = [
        row for row in _scope_rows(_rows(tables, "matchups"), league_id=league_id, season=current_season)
        if _same_id(row.get("roster_id"), my_roster_id)
    ]
    matchups.sort(key=lambda row: (_number(row.get("week")), _text(row.get("matchup_id"))), reverse=True)
    injury_count = sum(
        1 for row in roster if current_availability_status(row).startswith("injury_")
    )
    no_current_team_count = sum(
        1 for row in roster if current_availability_status(row) == "no_current_nfl_team"
    )
    starter_count = sum(1 for row in roster if _text(row.get("roster_status")).lower() == "starter")
    market_rows = [row for row in dossiers if _text(row.get("market_value"))]
    roster_by_player = {
        _text(row.get("player_id")): row
        for row in roster
        if _text(row.get("player_id"))
    }
    projected_rows = [
        {**row, **roster_by_player.get(_text(row.get("player_id")), {})}
        for row in dossiers
        if _text(row.get("projected_ppg"))
    ]
    current_role_rows = [
        row
        for row in projected_rows
        if current_availability_status(row) not in {"no_current_nfl_team", "historical_unavailable"}
    ]
    conditional_history_rows = [
        row for row in projected_rows if current_availability_status(row) == "no_current_nfl_team"
    ]
    current_role_ppg = sum(_number(row.get("projected_ppg")) for row in current_role_rows)
    conditional_history_ppg = sum(_number(row.get("projected_ppg")) for row in conditional_history_rows)
    dossier_by_player = {str(row.get("player_id")): row for row in dossiers if _text(row.get("player_id"))}
    items: list[dict[str, Any]] = []
    matchup = matchups[0] if matchups else {}
    lineup_receipt = _matchup_lineup_receipt(
        tables,
        league_id=league_id,
        season=current_season,
        roster_id=my_roster_id,
        matchup=matchup,
    )
    if matchup:
        opponent = _text(matchup.get("opponent_team_name")) or f"Roster {_text(matchup.get('opponent_roster_id')) or 'unknown'}"
        result = _text(matchup.get("result")) or "not recorded"
        points_for = _number_or_text(matchup.get("points_for"))
        points_against = _number_or_text(matchup.get("points_against"))
        margin = _number_or_text(matchup.get("margin"))
        items.append(
            _front_page_item(
                title=f"Week {_text(matchup.get('week')) or 'current'} · {my_team_name or 'Your team'} vs {opponent}",
                summary=(
                    f"Topline Tony's matchup read: {result}, {points_for} for and {points_against} against "
                    f"(margin {margin}). This is the observed Sleeper matchup receipt; lineup and next-game "
                    "interpretation belongs in the Team Report, not in the score row."
                ),
                meta="weekly matchup · exact Sleeper receipt",
                anchor=_anchor("team", my_roster_id),
                evidence=_front_page_evidence(matchup, "matchups"),
                tone="team",
            )
        )
        if lineup_receipt.get("status") in {"reconciled", "partial"}:
            contributors = lineup_receipt.get("top_contributors") or []
            contributor_text = ", ".join(
                f"{_text(row.get('player_name')) or 'Unknown player'} {_number_or_text(row.get('player_points'))}"
                for row in contributors[:3]
            ) or "no named contributors"
            reconciliation = _text(lineup_receipt.get("reconciliation_label"))
            items.append(
                _front_page_item(
                    title=f"Week {_text(matchup.get('week')) or 'current'} · who supplied the points",
                    summary=(
                        f"Topline Tony's lineup receipt: {contributor_text}. Starters supplied "
                        f"{_number_or_text(lineup_receipt.get('starter_points'))} points and non-starters "
                        f"{_number_or_text(lineup_receipt.get('bench_points'))}; {reconciliation}."
                    ),
                    meta="exact Sleeper player-point receipt · attribution before interpretation",
                    anchor=_anchor("team", my_roster_id),
                    evidence=(
                        "matchup_player_points; "
                        f"matchup_id={_text(matchup.get('matchup_id'))}; "
                        f"rows={_text(lineup_receipt.get('row_count'))}; "
                        f"known_points={_text(lineup_receipt.get('known_points'))}"
                    ),
                    tone="team",
                )
            )
    for row in sorted(news, key=lambda item: _text(item.get("published_at")), reverse=True)[:2]:
        player_name = _text(row.get("player_name")) or "Rostered player"
        dossier = dossier_by_player.get(str(row.get("player_id")), {})
        context = _player_market_context(dossier)
        items.append(
            _front_page_item(
                title=f"{player_name} · {_human_label(_text(row.get('impact_type')) or 'league signal')}",
                summary=f"{_text(row.get('evidence')) or 'A roster-linked news item needs a closer read.'}{context}",
                meta=_news_meta(row),
                anchor=_anchor("player", _text(row.get("player_id"))),
                evidence=_front_page_evidence(row, "league_news_impact"),
                tone="news",
            )
        )
    if not items:
        for row in sorted(dossiers, key=lambda item: _number(item.get("market_value")), reverse=True)[:2]:
            player_name = _text(row.get("player_name")) or "Roster asset"
            items.append(
                _front_page_item(
                    title=player_name,
                    summary=f"{_human_label(_text(row.get('signal_label')) or 'no active signal')}; {_player_market_context(row).lstrip('; ')}.",
                    meta=f"{_text(row.get('position')) or 'asset'} · {_text(row.get('roster_status')) or 'roster status unknown'}",
                    anchor=_anchor("player", _text(row.get("player_id"))),
                    evidence=_front_page_evidence(row, "player_dossiers"),
                    tone="hold",
                )
            )
    return {
        "key": "team_pulse",
        "eyebrow": "Your team",
        "title": my_team_name or "Your team",
        "dek": (
            f"{len(roster)} current-season roster rows, {injury_count} with a current Sleeper injury flag, "
            f"{no_current_team_count} without a current NFL team, and {len(news)} linked news signal{'s' if len(news) != 1 else ''}."
        ),
        "facts": [
            {"label": "Starters", "value": starter_count},
            {"label": "Market rows", "value": f"{len(market_rows)}/{len(roster)}"},
            {
                "label": "Current-role baseline PPG",
                "value": round(current_role_ppg, 2) if current_role_rows else "n/a",
            },
            {
                "label": "Conditional history PPG",
                "value": round(conditional_history_ppg, 2) if conditional_history_rows else "0",
            },
            {"label": "Injury flags", "value": injury_count},
            {"label": "Matchup receipts", "value": len(matchups)},
            {"label": "Lineup attribution", "value": lineup_receipt.get("status", "unavailable")},
            {"label": "Season", "value": current_season or "current"},
        ],
        "items": items,
        "route": "#view-my-team",
        "route_label": "Open My Team",
        "uncertainty": (
            "Roster facts are exact. Current-role baseline PPG excludes players without a current NFL team; "
            "conditional history PPG remains research context and is not current-role production. Injury-limited "
            "baselines remain conditional on being active."
        ),
        "matchup_lineup_receipt": lineup_receipt,
        "source_trace": "roster_players;player_dossiers;matchups;matchup_player_points;league_news_impact",
        "tone": "team",
    }


def _matchup_lineup_receipt(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    league_id: str,
    season: str,
    roster_id: int | str | None,
    matchup: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Reconcile exact nested Sleeper player points to the selected matchup.

    Blank or placeholder 0-0 rows remain unavailable. A mismatch against the
    aggregate team score is reported as partial instead of being silently
    treated as a complete lineup explanation.
    """

    matchup = matchup if isinstance(matchup, Mapping) else {}
    matchup_id = _text(matchup.get("matchup_id"))
    base = {
        "status": "unavailable" if not matchup_id else "unplayed",
        "matchup_id": matchup_id,
        "row_count": 0,
        "known_points": 0,
        "starter_points": 0,
        "bench_points": 0,
        "top_contributors": [],
        "reconciliation_delta": "",
        "reconciliation_label": "player-point rows are unavailable",
        "source_trace": "matchup_player_points",
    }
    if not matchup_id:
        return base
    rows = [
        row
        for row in _scope_rows(_rows(tables, "matchup_player_points"), league_id=league_id, season=season)
        if _same_id(row.get("roster_id"), roster_id)
        and _same_id(row.get("matchup_id"), matchup_id)
    ]
    base["row_count"] = len(rows)
    played_rows = [row for row in rows if _text(row.get("matchup_status")).lower() == "played"]
    if not played_rows:
        return base
    known_rows = [row for row in played_rows if _text(row.get("player_points")) != ""]
    starter_rows = [row for row in known_rows if _text(row.get("is_starter")).lower() in {"true", "1", "yes"}]
    bench_rows = [row for row in known_rows if row not in starter_rows]
    starter_points = sum(_number(row.get("player_points")) for row in starter_rows)
    bench_points = sum(_number(row.get("player_points")) for row in bench_rows)
    known_points = starter_points + bench_points
    top_contributors = sorted(
        (
            {
                "player_id": _text(row.get("player_id")),
                "player_name": _text(row.get("player_name")) or _text(row.get("player_id")),
                "player_points": _number_or_text(row.get("player_points")),
                "is_starter": _text(row.get("is_starter")),
                "source_trace": _text(row.get("source_trace")) or "matchup_player_points",
            }
            for row in known_rows
        ),
        key=lambda row: (_number(row.get("player_points")), _text(row.get("player_name"))),
        reverse=True,
    )[:5]
    team_points_text = _text(matchup.get("points_for"))
    team_points = _number(team_points_text) if team_points_text else None
    delta = None if team_points is None else round(known_points - team_points, 2)
    status = "reconciled" if team_points is not None and abs(delta or 0) <= 0.1 and len(known_rows) == len(played_rows) else "partial"
    label = (
        f"player receipts reconcile to {_number_or_text(team_points)} team points"
        if status == "reconciled"
        else "player receipts are partial; inspect blank rows and aggregate matchup total"
    )
    return {
        **base,
        "status": status,
        "known_points": round(known_points, 2),
        "starter_points": round(starter_points, 2),
        "bench_points": round(bench_points, 2),
        "top_contributors": top_contributors,
        "reconciliation_delta": delta if delta is not None else "",
        "reconciliation_label": label,
        "player_rows_played": len(played_rows),
        "player_rows_known": len(known_rows),
        "team_points": team_points if team_points is not None else "",
    }


def _news_watch_panel(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    league_id: str,
    my_roster_id: int | str | None,
) -> dict[str, Any]:
    rows = _league_news_rows(tables, league_id)
    mine = [
        row for row in rows
        if _same_id(row.get("roster_id"), my_roster_id)
        and (not league_id or not _text(row.get("league_id")) or _same_id(row.get("league_id"), league_id))
    ]
    others = [row for row in rows if row not in mine]
    ordered = sorted(mine, key=lambda row: _text(row.get("published_at")), reverse=True) + sorted(
        others, key=lambda row: _text(row.get("published_at")), reverse=True
    )
    signal_map = {str(row.get("player_id")): row for row in _rows(tables, "player_signal_scores") if _text(row.get("player_id"))}
    dossier_map = {str(row.get("player_id")): row for row in _rows(tables, "player_dossiers") if _text(row.get("player_id"))}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ordered:
        event_id = _text(row.get("event_id")) or f"{row.get('player_id')}:{row.get('published_at')}"
        if event_id in seen:
            continue
        seen.add(event_id)
        signal = signal_map.get(str(row.get("player_id")), {})
        dossier = dossier_map.get(str(row.get("player_id")), {})
        context = _player_market_context({**dossier, **signal})
        if context:
            context = f" Model context: {context.lstrip('; ')}."
        items.append(
            _front_page_item(
                title=f"{_text(row.get('player_name')) or 'League player'} · {_human_label(_text(row.get('impact_type')) or 'signal')}",
                summary=f"{_text(row.get('evidence')) or 'News was matched to the league, but the claim still needs review.'}{context}",
                meta=_news_meta(row),
                anchor=_anchor("player", _text(row.get("player_id"))),
                evidence=_front_page_evidence(row, "league_news_impact"),
                tone="news",
            )
        )
        if len(items) >= 3:
            break
    return {
        "key": "news_watch",
        "eyebrow": "News desk",
        "title": "What changed",
        "dek": f"{len(mine)} news signal{'s' if len(mine) != 1 else ''} link directly to the selected roster; league context follows.",
        "facts": [
            {"label": "Linked to you", "value": len(mine)},
            {"label": "League signals", "value": len(rows)},
            {"label": "Sources", "value": len({str(row.get('source')) for row in rows if _text(row.get('source'))})},
        ],
        "items": items,
        "route": "#view-news",
        "route_label": "Open News",
        "uncertainty": "News is a catalyst for research; it is not a projection, transaction, or conclusion.",
        "source_trace": "news_events;player_news_matches;league_news_impact",
        "tone": "news",
    }


def _market_watch_panel(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    my_roster_id: int | str | None,
    *,
    league_id: str = "",
    current_season: str = "",
) -> dict[str, Any]:
    horizon_rows = [
        dict(row)
        for row in _scope_rows(
            _rows(tables, "player_horizon_market_scores"),
            league_id=league_id,
            season=current_season,
        )
        if _text(row.get("player_name")) and _text(row.get("value_lane")) != "insufficient_context"
    ]
    horizon_rows.sort(key=lambda row: abs(_number(row.get("rebuilder_contender_spread"))), reverse=True)
    available_rostered_ids = {
        _text(row.get("player_id"))
        for row in _rows(tables, "roster_players")
        if _text(row.get("player_id"))
        and (not current_season or not _text(row.get("season")) or _same_id(row.get("season"), current_season))
        and (not league_id or not _text(row.get("league_id")) or _same_id(row.get("league_id"), league_id))
    }
    available_rows = [
        dict(row)
        for row in _rows(tables, "available_player_horizon_scores")
        if _text(row.get("player_id"))
        and _text(row.get("player_name"))
        and _text(row.get("availability_status")) == "not_rostered_in_selected_league"
        and _text(row.get("identity_status")) in {"sleeper_id", "sleeper_unique_name_match"}
        and _text(row.get("player_id")) not in available_rostered_ids
        and (not current_season or not _text(row.get("season")) or _same_id(row.get("season"), current_season))
        and (not league_id or not _text(row.get("league_id")) or _same_id(row.get("league_id"), league_id))
        and any(_text(row.get(field)) for field in (
            "next_game_market_score",
            "rest_of_season_market_score",
            "dynasty_market_score",
            "career_projection_score",
        ))
    ]
    available_rows.sort(
        key=lambda row: (
            _market_clock_coverage(row),
            max(
                _number(row.get("next_game_market_score")),
                _number(row.get("rest_of_season_market_score")),
                _number(row.get("dynasty_market_score")),
                _number(row.get("career_projection_score")),
            ),
            abs(_number(row.get("rebuilder_contender_spread"))),
            _number(row.get("market_value")),
        ),
        reverse=True,
    )
    # Make the front page tell the reader that the board includes a real
    # available-market lane.  One roster clock plus one available clock is a
    # more useful edit than three nearly identical roster cards.
    horizon_items = []
    for row in horizon_rows[: (1 if available_rows else 2)]:
        lane = _text(row.get("value_lane")) or "balanced_window"
        owner_marker = " · your roster" if _same_id(row.get("roster_id"), my_roster_id) else ""
        horizon_items.append(
            _front_page_item(
                title=f"{_text(row.get('player_name'))} · {lane.replace('_', ' ')}",
                summary=(
                    f"Next-game score {_number_or_text(row.get('next_game_market_score'))} vs {_text(row.get('next_game_opponent')) or 'opponent unavailable'} "
                    f"(clock-minus-market {_number_or_text(row.get('next_game_minus_market_delta'))}); rest-of-season score "
                    f"{_number_or_text(row.get('rest_of_season_market_score'))} (clock-minus-market {_number_or_text(row.get('rest_of_season_minus_market_delta'))}; change from next game {_number_or_text(row.get('rest_of_season_minus_next_game_delta'))}); dynasty score "
                    f"{_number_or_text(row.get('dynasty_market_score'))} (clock-minus-market {_number_or_text(row.get('dynasty_minus_market_delta'))}; change from rest of season {_number_or_text(row.get('dynasty_minus_rest_of_season_delta'))}); five-year career-window score "
                    f"{_number_or_text(row.get('career_projection_score'))} (clock-minus-market {_number_or_text(row.get('career_minus_market_delta'))}; change from dynasty {_number_or_text(row.get('career_minus_dynasty_delta'))}); career history "
                    f"{_text(row.get('career_history_status')) or 'unavailable'} ({_number_or_text(row.get('career_history_ppg'))} PPG, "
                    f"{_text(row.get('career_history_games')) or '0'} games / {_text(row.get('career_history_seasons')) or '0'} seasons). Contender fit is "
                    f"{_number_or_text(row.get('contender_fit_score'))} versus rebuilder fit "
                    f"{_number_or_text(row.get('rebuilder_fit_score'))}{owner_marker}. Rest-of-season baseline is not recovery-adjusted."
                    f" Cross-position price anchor is market value {_number_or_text(row.get('market_value'))}; position market percentile is {_number_or_text(row.get('market_percentile'))}."
                    " These are position-relative percentiles, not dollar market values or cross-position price rankings."
                ),
                meta=f"{_text(row.get('position')) or 'asset'} · {lane.replace('_', ' ')} · {_text(row.get('confidence')) or 'confidence unknown'}",
                anchor=_anchor("player", _text(row.get("player_id"))),
                evidence=_front_page_evidence(row, "player_horizon_market_scores"),
                tone="market",
            )
        )
    available_items: list[dict[str, Any]] = []
    for row in available_rows[:1]:
        lane = _text(row.get("value_lane")) or "balanced_window"
        available_items.append(
            _front_page_item(
                title=f"{_text(row.get('player_name'))} · available market",
                summary=(
                    f"Available-market research row: this-week score {_number_or_text(row.get('next_game_market_score'))} (clock-minus-market {_number_or_text(row.get('next_game_minus_market_delta'))}); "
                    f"rest-of-season score {_number_or_text(row.get('rest_of_season_market_score'))} (clock-minus-market {_number_or_text(row.get('rest_of_season_minus_market_delta'))}; change from this week "
                    f"{_number_or_text(row.get('rest_of_season_minus_next_game_delta'))}); dynasty score "
                    f"{_number_or_text(row.get('dynasty_market_score'))} (clock-minus-market {_number_or_text(row.get('dynasty_minus_market_delta'))}; change from rest of season "
                    f"{_number_or_text(row.get('dynasty_minus_rest_of_season_delta'))}); career-window score "
                    f"{_number_or_text(row.get('career_projection_score'))} (clock-minus-market {_number_or_text(row.get('career_minus_market_delta'))}; change from dynasty "
                    f"{_number_or_text(row.get('career_minus_dynasty_delta'))}). Lane is {lane.replace('_', ' ')}; "
                    f"contender fit {_number_or_text(row.get('contender_fit_score'))} versus rebuilder fit "
                    f"{_number_or_text(row.get('rebuilder_fit_score'))}. Market value {_number_or_text(row.get('market_value'))}; "
                    "availability is inferred from this league's roster snapshot, not a waiver-eligibility receipt."
                ),
                meta=f"{_text(row.get('position')) or 'asset'} · available research · {_text(row.get('fit_coverage')) or 'clock coverage unavailable'}",
                anchor=_anchor("player", _text(row.get("player_id"))),
                evidence=_front_page_evidence(row, "available_player_horizon_scores"),
                tone="market",
            )
        )
    edge_rows = [
        dict(row)
        for row in _scope_rows(
            _rows(tables, "news_market_edges"),
            league_id=league_id,
            season=current_season,
        )
        if _text(row.get("player_name"))
    ]
    if edge_rows:
        edge_rows.sort(
            key=lambda row: (
                _number(row.get("news_market_edge_score")),
                _number(row.get("market_gap_score")),
                _number(row.get("sell_score")),
            ),
            reverse=True,
        )
        edge_items: list[dict[str, Any]] = []
        for row in edge_rows[: max(0, 3 - len(horizon_items) - len(available_items))]:
            direction = _text(row.get("news_direction")) or "mixed"
            edge_label = (_text(row.get("edge_type")) or "news-market review").replace("_", " ")
            owner_marker = " · your roster" if _same_id(row.get("roster_id"), my_roster_id) else ""
            edge_items.append(
                _front_page_item(
                    title=f"{_text(row.get('player_name'))} · {edge_label}",
                    summary=(
                        f"{_text(row.get('news_impact')) or 'News signal'} across {_number_or_text(row.get('news_event_count'))} event(s) "
                        f"while the market is {_number_or_text(row.get('market_value'))} and {baseline_ppg_label(row)} is "
                        f"{_number_or_text(row.get('projected_ppg'))}; {_text(row.get('team_name')) or 'team unknown'}{owner_marker}."
                    ),
                    meta=f"{_text(row.get('position')) or 'asset'} · {direction} · {_text(row.get('confidence')) or 'confidence unknown'}",
                    anchor=_anchor("player", _text(row.get("player_id"))),
                    evidence=_front_page_evidence(row, "news_market_edges"),
                    tone="market",
                )
            )
        high_confidence = sum(1 for row in edge_rows if _text(row.get("confidence")).lower() == "high")
        selected_count = sum(1 for row in edge_rows if _same_id(row.get("roster_id"), my_roster_id))
        return {
            "key": "market_watch",
            "eyebrow": "Market desk",
            "title": "Where news is ahead of price",
            "dek": "Current league catalysts paired with deterministic price or sell-pressure gaps; every row is a research lead, not a verdict.",
            "facts": [
                {"label": "Horizon rows", "value": len(horizon_rows)},
                {"label": "Available clocks", "value": len(available_rows)},
                {"label": "News-market edges", "value": len(edge_rows)},
                {"label": "High confidence", "value": high_confidence},
                {"label": "On your roster", "value": selected_count},
            ],
            "items": horizon_items + available_items + edge_items,
            "route": "#view-trade-desk",
            "route_label": "Open Trade Desk",
            "uncertainty": "A catalyst can be early, transient, duplicated across sources, or already reflected in a live market not captured here; inspect the source receipt before acting.",
            "source_trace": "player_horizon_market_scores;available_player_horizon_scores;news_market_edges;league_news_impact;player_signal_scores;player_projection_season;market_consensus_values",
            "tone": "market",
        }

    rows = []
    dossier_map = {str(row.get("player_id")): row for row in _rows(tables, "player_dossiers") if _text(row.get("player_id"))}
    for row in _rows(tables, "player_signal_scores"):
        if not _text(row.get("player_name")) or _number(row.get("market_value")) <= 0 or _number(row.get("projected_ppg")) <= 0:
            continue
        gap = _number(row.get("market_gap_score"))
        if gap <= 0:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (_number(row.get("market_gap_score")), _number(row.get("projected_ppg"))), reverse=True)
    items: list[dict[str, Any]] = []
    for row in rows[: max(0, 3 - len(horizon_items) - len(available_items))]:
        team_name = _text(row.get("team_name")) or "Unrostered / team unknown"
        owner_marker = " · your roster" if _same_id(row.get("roster_id"), my_roster_id) else ""
        dossier = dossier_map.get(str(row.get("player_id")), {})
        availability = _text(row.get("availability_note")) or _text(dossier.get("availability_note"))
        items.append(
            _front_page_item(
                title=f"{_text(row.get('player_name'))} · model gap {_number_or_text(row.get('market_gap_score'))}",
                summary=(
                    f"{_number_or_text(row.get('projected_ppg'))} {baseline_ppg_label({**dossier, **row})} against a "
                    f"{_number_or_text(row.get('market_value'))} market value; {team_name}{owner_marker}."
                    f"{f' {availability}.' if availability and not availability.startswith('No current') else ''}"
                ),
                meta=f"{_text(row.get('position')) or 'asset'} · {_text(row.get('confidence')) or 'confidence unknown'}",
                anchor=_anchor("player", _text(row.get("player_id"))),
                evidence=_front_page_evidence(row, "player_signal_scores"),
                tone="market",
            )
        )
    high_confidence = sum(1 for row in rows if _text(row.get("confidence")).lower() == "high")
    selected_count = sum(1 for row in rows if _same_id(row.get("roster_id"), my_roster_id))
    return {
        "key": "market_watch",
        "eyebrow": "Market desk",
        "title": "Where the model disagrees",
        "dek": "Projection-to-market gaps are research leads for price discovery, not confirmed mispricing.",
        "facts": [
        {"label": "Horizon rows", "value": len(horizon_rows)},
        {"label": "Available clocks", "value": len(available_rows)},
            {"label": "Positive gaps", "value": len(rows)},
            {"label": "High confidence", "value": high_confidence},
            {"label": "On your roster", "value": selected_count},
        ],
        "items": horizon_items + available_items + items,
        "route": "#view-trade-desk",
        "route_label": "Open Trade Desk",
        "uncertainty": "Market values and baseline projections can be stale or structurally different; inspect the receipt before acting.",
        "source_trace": "player_horizon_market_scores;available_player_horizon_scores;player_signal_scores;player_projection_season;market_consensus_values",
        "tone": "market",
    }


def _manager_watch_panel(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    analysis: Mapping[str, Any],
    my_roster_id: int | str | None,
) -> dict[str, Any]:
    dossiers = [
        dict(row)
        for row in (analysis.get("managerDossierItems") or analysis.get("manager_dossiers") or [])
        if isinstance(row, Mapping) and not _same_id(row.get("roster_id"), my_roster_id)
    ]
    dossiers.sort(
        key=lambda row: (
            _number((row.get("trade_fit_evaluation") or {}).get("aligned_fit_count")),
            _number((row.get("sample_size") or {}).get("observed_events")),
            _number((row.get("sample_size") or {}).get("trades")),
        ),
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    for dossier in dossiers[:2]:
        sample = dossier.get("sample_size") if isinstance(dossier.get("sample_size"), Mapping) else {}
        outcome = dossier.get("outcome_summary") if isinstance(dossier.get("outcome_summary"), Mapping) else {}
        fit = dossier.get("trade_fit_evaluation") if isinstance(dossier.get("trade_fit_evaluation"), Mapping) else {}
        summary = _excerpt(dossier.get("analysis_text")) or "Observed behavior is available in the full manager dossier."
        items.append(
            _front_page_item(
                title=_text(dossier.get("team_name")) or f"Roster {_text(dossier.get('roster_id'))}",
                summary=summary,
                meta=(
                    f"{_text(dossier.get('dynasty_cycle')) or 'cycle unclear'} · "
                    f"{sample.get('seasons', 0)} seasons · {sample.get('trades', 0)} trades · "
                    f"{fit.get('aligned_fit_count', 0)} aligned fits"
                ),
                anchor=_anchor("manager", _text(dossier.get("roster_id"))),
                evidence=(
                    f"{_text(dossier.get('source_trace')) or 'manager_dossiers'}; "
                    f"sample_events={sample.get('observed_events', 0)}; outcome={outcome.get('status', 'not recorded')}"
                ),
                tone="manager",
            )
        )
    if not items:
        behaviors = [row for row in _rows(tables, "manager_behavior_signals") if not _same_id(row.get("roster_id"), my_roster_id)]
        behaviors.sort(key=lambda row: _number(row.get("trade_activity_score")), reverse=True)
        for row in behaviors[:2]:
            items.append(
                _front_page_item(
                    title=_text(row.get("team_name")) or f"Roster {_text(row.get('roster_id'))}",
                    summary=_text(row.get("evidence")) or "Observed manager behavior is sparse.",
                    meta=f"{_text(row.get('plain_language_label')) or 'observed behavior'} · confidence {_text(row.get('confidence')) or 'unknown'}",
                    anchor=_anchor("manager", _text(row.get("roster_id"))),
                    evidence=_front_page_evidence(row, "manager_behavior_signals"),
                    tone="manager",
                )
            )
    return {
        "key": "manager_watch",
        "eyebrow": "Dossier desk",
        "title": "Who is worth studying",
        "dek": "Manager profiles turn years of transactions into conversation hypotheses; intent remains unknown.",
        "facts": [
            {"label": "Profiles", "value": len(dossiers) or len(_rows(tables, "manager_behavior_signals"))},
            {"label": "With history", "value": sum(1 for row in dossiers if (row.get("sample_size") or {}).get("seasons"))},
            {"label": "Decision path", "value": "dossier → trade desk"},
        ],
        "items": items,
        "route": "#view-league",
        "route_label": "Open Manager Room",
        "uncertainty": "Observed behavior is not motive; sample size and recency should travel with every read.",
        "source_trace": "manager_dossiers;manager_season_history;manager_event_log",
        "tone": "manager",
    }


def _priority_story(
    row: Mapping[str, Any] | None,
    *,
    is_lead: bool = False,
    persona_id: str = "front_office",
    writer_preferences: Mapping[str, Any] | None = None,
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
    reporter = _reporter_for_story(kind, writer_preferences)
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
        "reporter_id": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "reporter_persona": reporter,
    }


def _news_story(row: Mapping[str, Any], writer_preferences: Mapping[str, Any] | None = None) -> dict[str, Any]:
    player_name = _text(row.get("player_name")) or "A league player"
    impact = _text(row.get("impact_type")) or "league signal"
    impact_label = _human_label(impact)
    confidence = _confidence(row.get("confidence"))
    evidence = _text(row.get("evidence")) or f"{player_name}: {impact_label}."
    reporter = _reporter_for_story("news", writer_preferences)
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
        "reporter_id": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "reporter_persona": reporter,
    }


def _manager_story(row: Mapping[str, Any], writer_preferences: Mapping[str, Any] | None = None) -> dict[str, Any]:
    team_name = _text(row.get("team_name")) or "A league manager"
    label = _text(row.get("plain_language_label")) or "observed market behavior"
    evidence = _text(row.get("evidence")) or "Observed transaction behavior is sparse."
    claims = [
        {"label": "Read", "value": label},
        {"label": "Trade activity", "value": _number_or_text(row.get("trade_activity_score"))},
        {"label": "Pick posture", "value": _pick_posture(row)},
    ]
    reporter = _reporter_for_story("manager", writer_preferences)
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
        "reporter_id": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "reporter_persona": reporter,
    }


def _quiet_story(team_name: str, writer_preferences: Mapping[str, Any] | None = None) -> dict[str, Any]:
    team_label = team_name or "Your team"
    reporter = _reporter_for_story("quiet", writer_preferences)
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
        "reporter_id": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "reporter_persona": reporter,
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


def _sorted_news(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    my_roster_id: int | str | None,
    league_id: str = "",
) -> list[dict[str, Any]]:
    rows = _league_news_rows(tables, league_id)
    if my_roster_id is not None:
        scoped = [
            row for row in rows
            if _same_id(row.get("roster_id"), my_roster_id)
            and (not league_id or not _text(row.get("league_id")) or _same_id(row.get("league_id"), league_id))
        ]
        if scoped:
            rows = scoped
    return sorted(rows, key=lambda row: _text(row.get("published_at")), reverse=True)


def _league_news_rows(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    league_id: str = "",
) -> list[dict[str, Any]]:
    rows = _rows(tables, "league_news_impact")
    if not league_id:
        return rows
    scoped = [row for row in rows if _same_id(row.get("league_id"), league_id)]
    if scoped:
        return scoped
    # Keep older bundles readable while refusing to mix an unscoped legacy bundle with a
    # scoped league when the new artifact already provides a boundary.
    return [row for row in rows if not _text(row.get("league_id"))]


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
        "ppg": "Baseline PPG",
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


def _manager_trade_profile_rows(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    context = config.get("context") if isinstance(config.get("context"), Mapping) else {}
    rows = config.get("manager_trade_profiles") or context.get("manager_trade_profiles") or []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _select_manager_trade_profile(
    profiles: list[dict[str, Any]],
    manager_rows: list[dict[str, Any]],
    my_roster_id: int | str | None,
) -> dict[str, Any] | None:
    if not profiles:
        return None
    observed_ids = {str(row.get("roster_id")) for row in manager_rows if row.get("roster_id") not in (None, "")}
    for profile in profiles:
        roster_id = str(profile.get("roster_id") or "")
        if roster_id and roster_id in observed_ids and roster_id != str(my_roster_id):
            return profile
    for profile in profiles:
        if str(profile.get("roster_id") or "") != str(my_roster_id):
            return profile
    return profiles[0]


def _manager_profile_story(
    profile: Mapping[str, Any],
    writer_preferences: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    roster_id = _text(profile.get("roster_id"))
    manager_name = _text(profile.get("manager_name")) or "A league manager"
    trade_style = _text(profile.get("trade_style")) or "an unclassified trade style"
    preferred = _text(profile.get("preferred_assets")) or "not specified"
    protected = _text(profile.get("protected_assets")) or "not specified"
    editor_note = _text(profile.get("editor_note"))
    note = editor_note or f"Working style: {trade_style}."
    reporter = _reporter_for_story("manager", writer_preferences)
    return {
        "story_id": f"manager:note:{roster_id or manager_name}",
        "story_type": "manager",
        "eyebrow": "Personalized manager lens",
        "headline": f"Your working read on {manager_name}",
        "dek": f"Private profile: {note}",
        "action": "Move: use this as a conversation hypothesis, then verify it against current behavior before acting.",
        "watchout": "This is private editor context, not confirmed league evidence.",
        "confidence": "editorial",
        "priority_score": "",
        "entity_type": "manager",
        "entity_id": f"note:{roster_id or manager_name}",
        "entity_name": manager_name,
        "team_name": manager_name,
        "anchor": _anchor("manager", roster_id),
        "claims": [
            {"label": "Trade style", "value": trade_style},
            {"label": "Likely to chase", "value": preferred},
            {"label": "Likely to protect", "value": protected},
        ],
        "evidence": f"Private editor context, not source evidence: {note}",
        "sources": [],
        "is_lead": False,
        "reporter_id": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "reporter_persona": reporter,
    }


def _manager_dossier_story(dossier: Mapping[str, Any], writer_preferences: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Turn the durable manager dossier into a homepage story without flattening it.

    The homepage should invite the reader into the dossier, not replace the
    dossier with a generic behavior label. Structured claims keep the richer
    history visible while the dossier route remains the source of detail.
    """

    team_name = _text(dossier.get("team_name")) or "A league manager"
    construction = dossier.get("roster_construction") if isinstance(dossier.get("roster_construction"), Mapping) else {}
    sample = dossier.get("sample_size") if isinstance(dossier.get("sample_size"), Mapping) else {}
    outcome = dossier.get("outcome_summary") if isinstance(dossier.get("outcome_summary"), Mapping) else {}
    cycle = _text(dossier.get("dynasty_cycle")) or "unclear cycle"
    evidence = _text(dossier.get("evidence")) or "The deterministic manager dossier is available for inspection."
    reporter = _reporter_for_story("manager", writer_preferences)
    claims = [
        {"label": "Cycle", "value": cycle},
        {"label": "Observed seasons", "value": _number_or_text(sample.get("seasons"))},
        {"label": "Observed trades", "value": _number_or_text(sample.get("trades"))},
        {"label": "Outcome record", "value": _text(outcome.get("record")) or "not recorded"},
        {"label": "Roster market", "value": _number_or_text(construction.get("market_value_total"))},
    ]
    return {
        "story_id": f"manager:{_text(dossier.get('roster_id')) or team_name}",
        "story_type": "manager",
        "eyebrow": "Manager dossier",
        "headline": f"{team_name}: the history behind the next conversation",
        "dek": _text(dossier.get("analysis_text")) or "Observed history, roster construction, and current trade fits are available in the dossier.",
        "action": "Move: open the dossier, then compare the current trade fit with the manager's observed valuation lanes.",
        "watchout": "Observed behavior is not intent, and a trade fit is not a predicted response.",
        "confidence": _confidence(dossier.get("confidence")),
        "priority_score": "",
        "entity_type": "manager",
        "entity_id": _text(dossier.get("roster_id")),
        "entity_name": team_name,
        "team_name": team_name,
        "anchor": _anchor("manager", _text(dossier.get("roster_id"))),
        "claims": claims,
        "evidence": evidence,
        "sources": _source_links(dossier.get("source_trace")),
        "is_lead": False,
        "reporter_id": reporter["persona_id"],
        "reporter_name": reporter["name"],
        "reporter_persona": reporter,
    }


def _reporter_for_story(story_type: str, writer_preferences: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Assign a visible desk identity to deterministic cards as well as LLM articles."""

    key = {
        "market": "market_watch",
        "sell": "trade_desk",
        "manager": "manager_intel",
        "news": "team_report",
        "quiet": "daily_brief",
    }.get(story_type, "daily_brief")
    return persona_metadata(dict(writer_preferences or {}), key)


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
        "horizon_watch": "horizonWatchMode",
        "trade_desk": "tradeDeskReadMode",
        "manager_intel": "managerIntelMode",
    }
    return {
        key: _text(analysis.get(field)) or "deterministic_template"
        for key, field in fields.items()
    }


def _front_page_item(
    *,
    title: str,
    summary: str,
    meta: str,
    anchor: str,
    evidence: str,
    tone: str,
) -> dict[str, str]:
    return {
        "title": _text(title) or "Untitled read",
        "summary": _text(summary) or "No summary recorded.",
        "meta": _text(meta) or "Evidence context unavailable",
        "anchor": _text(anchor),
        "evidence": _text(evidence) or "Evidence trace not recorded.",
        "tone": _text(tone) or "info",
    }


def _front_page_evidence(row: Mapping[str, Any], table_name: str) -> str:
    identifiers = [
        f"{key}={_text(row.get(key))}"
        for key in ("event_id", "player_id", "roster_id", "source", "source_trace")
        if _text(row.get(key))
    ]
    if table_name in {"player_horizon_market_scores", "available_player_horizon_scores"}:
        identifiers.extend(
            f"{key}={_text(row.get(key))}"
            for key in (
                "horizon_model_version",
                "horizon_score_basis",
                "market_value",
                "market_percentile",
                "next_game_minus_market_delta",
                "rest_of_season_minus_market_delta",
                "dynasty_minus_market_delta",
                "career_minus_market_delta",
                "fit_basis",
                "career_history_join_method",
                "career_history_source_player_id",
                "career_history_status",
                "career_history_seasons",
                "career_history_games",
                "career_history_ppg",
                "career_history_latest_season",
            )
            if _text(row.get(key))
        )
    return f"{table_name}; " + "; ".join(identifiers) if identifiers else table_name


def _player_market_context(row: Mapping[str, Any]) -> str:
    if not row:
        return ""
    market = _text(row.get("market_value"))
    ppg = _text(row.get("projected_ppg"))
    signal = _text(row.get("signal_label"))
    bits: list[str] = []
    if market:
        bits.append(f"market {market}")
    if ppg:
        bits.append(f"{baseline_ppg_label(row)} {ppg}")
    if signal:
        bits.append(_human_label(signal))
    availability = _text(row.get("availability_note"))
    if availability and not availability.startswith("No current Sleeper injury flag"):
        bits.append(availability)
    return f"; {' · '.join(bits)}" if bits else ""


def _news_meta(row: Mapping[str, Any]) -> str:
    source = _text(row.get("source")) or "source unknown"
    published = _short_date(row.get("published_at"))
    confidence = _text(row.get("confidence")) or "confidence unknown"
    risk = _text(row.get("risk"))
    return " · ".join(part for part in (source, published, confidence, risk) if part)


def _same_id(left: Any, right: Any) -> bool:
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


def _scope_rows(
    rows: list[dict[str, Any]],
    *,
    league_id: str = "",
    season: str = "",
) -> list[dict[str, Any]]:
    """Scope presentation rows without falling through to another league or season.

    Legacy rows with no identity field remain readable when no identified rows
    exist. Once a table contains identified rows, a requested scope with no
    exact match is unavailable rather than a reason to display a neighboring
    league's facts.
    """

    scoped = list(rows)
    for field, requested in (("league_id", league_id), ("season", season)):
        if not requested:
            continue
        identified = [row for row in scoped if _text(row.get(field))]
        if identified:
            scoped = [row for row in identified if _same_id(row.get(field), requested)]
        else:
            scoped = [row for row in scoped if not _text(row.get(field))]
    return scoped


def _season_rows(rows: list[dict[str, Any]], season: str) -> list[dict[str, Any]]:
    if not season:
        return rows
    matching = [row for row in rows if _text(row.get("season")) == str(season)]
    if matching:
        return matching
    # An identified non-matching season is evidence that the requested slice
    # is absent. Returning another season here would make a historical label
    # look current in a reader-facing panel.
    return [] if any(_text(row.get("season")) for row in rows) else rows


def _excerpt(value: Any, limit: int = 250) -> str:
    text = " ".join(_text(value).split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _unpublished_writer_fragment(
    article_key: str,
    reporter: Mapping[str, Any] | None = None,
    *,
    status: str = "not_published",
) -> dict[str, Any]:
    """Return a safe placeholder for a desk with no printable fragment.

    Front-page panels need a stable contract even when a writer is held,
    unavailable, or has not run yet. The placeholder carries the assigned
    lens, but deliberately carries no prose that could leak an unapproved
    draft into the reader facade.
    """

    reporter = reporter if isinstance(reporter, Mapping) else {}
    return {
        "schema_version": "writer_fragment_v1",
        "article_key": _text(article_key),
        "available": False,
        "status": _text(status) or "not_published",
        "mode": "",
        "reporter_name": _text(reporter.get("name")) or "The Front Office",
        "assigned_reporter_name": _text(reporter.get("name")),
        "reporter_label": "Reporter",
        "headline": "",
        "lede": "",
        "thesis": "",
        "counter_evidence": "",
        "action": "",
        "evidence_ids": [],
        "source_ids": [],
        "evidence_count": 0,
        "source_count": 0,
        "evidence_fingerprint": "",
    }


def _publication_lead_story(
    article: Mapping[str, Any],
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    """Make the issue hero a view of the primary publication, not a new read.

    The issue hero is the most prominent byline on the page. When a daily
    publication is printable, its structured fragment must supply that hero's
    headline and thesis so an LLM reporter can never appear above unrelated
    deterministic priority prose. If the article is held or unavailable, the
    deterministic lead remains the truthful fallback.
    """

    fragment = article.get("story_fragment") if isinstance(article.get("story_fragment"), Mapping) else {}
    if not fragment.get("available"):
        return dict(fallback)
    structured = article.get("structured") if isinstance(article.get("structured"), Mapping) else {}
    reporter = article.get("reporter_persona") if isinstance(article.get("reporter_persona"), Mapping) else {}
    assigned = article.get("assigned_reporter_persona") if isinstance(article.get("assigned_reporter_persona"), Mapping) else {}
    evidence_ids = [str(value) for value in (fragment.get("evidence_ids") or []) if str(value).strip()]
    source_ids = [str(value) for value in (fragment.get("source_ids") or []) if str(value).strip()]
    evidence = "Article receipt: "
    evidence += f"evidence_ids={','.join(evidence_ids) or 'not recorded'}"
    evidence += f"; source_ids={','.join(source_ids) or 'not recorded'}"
    return {
        "story_id": f"publication:{_text(article.get('key')) or 'daily_brief'}",
        "story_type": "brief",
        "eyebrow": _text((article.get("template") or {}).get("label")) or "Daily GM Brief",
        "headline": _text(fragment.get("headline")) or _text(fallback.get("headline")) or "The current edition",
        "dek": _text(fragment.get("lede")) or _text(fragment.get("thesis")) or _text(fallback.get("dek")),
        "action": _text(fragment.get("action")) or _text(fallback.get("action")),
        "watchout": _text(fragment.get("counter_evidence")) or _text(fallback.get("watchout")),
        "confidence": _confidence(structured.get("confidence")) if structured.get("confidence") else _confidence(fallback.get("confidence")),
        "priority_score": "",
        "entity_type": "edition",
        "entity_id": _text(article.get("key")) or "daily_brief",
        "entity_name": _text(fallback.get("entity_name")) or "The Front Office",
        "team_name": _text(fallback.get("team_name")),
        "anchor": "view-today",
        "claims": [],
        "evidence": evidence,
        "sources": [],
        "is_lead": True,
        "reporter_id": _text(reporter.get("persona_id")) or "front_office",
        "reporter_name": _text(reporter.get("name")) or "The Front Office",
        "reporter_persona": dict(reporter),
        "assigned_reporter_id": _text(assigned.get("persona_id")),
        "assigned_reporter_name": _text(assigned.get("name")),
        "assigned_reporter_persona": dict(assigned),
        "publication_article_key": _text(article.get("key")),
        "publication_status": _text(article.get("publication_status")),
    }


def _publication_fragment(article: Mapping[str, Any]) -> dict[str, Any]:
    """Project one publication into a reusable, bounded reader fragment.

    This is the canonical bridge between a paid desk call and its placements.
    It contains only structured fields and receipt metadata; templates should
    reuse it rather than parse article prose or trigger another provider call.
    Held articles retain their status and lens but not their unapproved copy.
    """

    key = _text(article.get("key"))
    structured = article.get("structured") if isinstance(article.get("structured"), Mapping) else {}
    status = _text(article.get("publication_status")) or "not_published"
    mode = _text(article.get("mode")) or "deterministic_template"
    reporter_name = _text(article.get("reporter_name")) or "The Front Office"
    assigned_name = _text(article.get("assigned_reporter_name"))
    is_printable = status in {"approved", "fallback"} and bool(_text(article.get("body")))
    if not is_printable:
        fragment = _unpublished_writer_fragment(
            key,
            {
                "name": assigned_name or reporter_name,
            },
            status=status,
        )
        fragment["mode"] = mode
        fragment["reporter_name"] = reporter_name
        fragment["assigned_reporter_name"] = assigned_name
        fragment["reporter_label"] = "Desk" if mode == "deterministic_template" else "Reporter"
        fragment["evidence_fingerprint"] = _text(article.get("evidence_fingerprint"))
        return fragment

    evidence_ids = list(dict.fromkeys(
        _text(value)
        for value in (structured.get("evidence_ids") or structured.get("cited_evidence_ids") or [])
        if _text(value)
    ))[:40]
    source_ids = list(dict.fromkeys(
        _text(value)
        for value in (structured.get("source_ids") or [])
        if _text(value)
    ))[:40]
    return {
        "schema_version": "writer_fragment_v1",
        "article_key": key,
        "available": True,
        "status": status,
        "mode": mode,
        "reporter_name": reporter_name,
        "assigned_reporter_name": assigned_name,
        "reporter_label": "Desk" if mode == "deterministic_template" else "Reporter",
        "headline": _excerpt(structured.get("headline") or article.get("title"), 150),
        "lede": _excerpt(structured.get("lede"), 240),
        "thesis": _excerpt(structured.get("thesis") or structured.get("what_changed"), 260),
        "counter_evidence": _excerpt(structured.get("counter_evidence"), 220),
        "action": _excerpt(structured.get("action"), 220),
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
        "evidence_count": len(evidence_ids),
        "source_count": len(source_ids),
        "evidence_fingerprint": _text(article.get("evidence_fingerprint")),
    }


def _publication_articles(
    analysis: Mapping[str, Any],
    writer_preferences: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expose the actual article bodies and receipts to the reader facade.

    The deterministic issue remains the navigation layer, but generated prose is
    now a first-class publication instead of an orphaned file counted by status.
    """
    specs = (
        ("daily_brief", "Daily GM Brief", "dailyGmBrief", "dailyGmBriefMode", 6, "closes the loop", "the flagship synthesis"),
        ("team_report", "Your Team Report", "teamReport", "teamReportMode", 1, "opens the room", "what changed around your roster"),
        ("market_watch", "Market Watch", "marketWatch", "marketWatchMode", 2, "tests the price", "where role and market disagree"),
        ("horizon_watch", "Four-Window Market Read", "horizonWatch", "horizonWatchMode", 5, "sets the clock", "how the answer changes with time"),
        ("trade_desk", "Trade Desk", "tradeDeskRead", "tradeDeskReadMode", 3, "finds the counterpart", "which conversation could create value"),
        ("manager_intel", "Manager Intel", "managerIntel", "managerIntelMode", 4, "reads the room", "what league history says to investigate"),
    )
    receipts = analysis.get("articleReceipts") if isinstance(analysis.get("articleReceipts"), Mapping) else {}
    output: list[dict[str, Any]] = []
    for key, title, body_field, mode_field, conversation_order, conversation_relation, conversation_caption in specs:
        body = _text(analysis.get(body_field))
        if not body:
            continue
        receipt = receipts.get(key) if isinstance(receipts.get(key), Mapping) else {}
        default_reporter = persona_metadata(dict(writer_preferences or {}), key)
        mode = _text(receipt.get("mode") or analysis.get(mode_field)) or "deterministic_template"
        reporter = _publication_reporter(dict(writer_preferences or {}), key, receipt, mode, default_reporter)
        assigned_reporter = _assigned_publication_reporter(dict(writer_preferences or {}), key, receipt, default_reporter)
        template = publication_template(key)
        review = review_publication_article(key, body, receipt, mode)
        published_body = body if review["status"] in {"approved", "fallback"} else ""
        structured = _publication_structured(receipt, mode, assigned_reporter)
        source_receipt = dict(receipt.get("source_receipt") or {}) if isinstance(receipt.get("source_receipt"), Mapping) else {}
        article = {
                "key": key,
                "title": title,
                "body": published_body,
                "content_block_schema": "publication_blocks_v1",
                "content_blocks": publication_content_blocks(published_body, key),
                "template": template,
                "template_id": template["template_id"],
                "mode": mode,
                "reporter_id": reporter["persona_id"],
                "reporter_name": reporter["name"],
                "reporter_persona": reporter,
                "reporter_label": "Desk" if mode == "deterministic_template" else "Reporter",
                "assigned_reporter_id": assigned_reporter["persona_id"],
                "assigned_reporter_name": assigned_reporter["name"],
                "assigned_reporter_persona": assigned_reporter,
                "generated_at": _text(receipt.get("generated_at")),
                "evidence_fingerprint": _text(receipt.get("evidence_fingerprint")),
                "fallback_reason": _text(receipt.get("fallback_reason")),
                "source_receipt": source_receipt,
                "content_hash": _text(receipt.get("content_hash")),
                "model": _text(receipt.get("model")),
                "structured": structured,
                "publication_status": review["status"],
                "editorial_review": review,
                "conversation_order": conversation_order,
                "conversation_relation": conversation_relation,
                "conversation_caption": conversation_caption,
                "reality_check": structured.get("reality_check") or source_receipt.get("reality_check") or {},
            }
        article["story_fragment"] = _publication_fragment(article)
        output.append(article)
    return output


def _newsroom_conversation(publication_articles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Turn independent desk outputs into a readable chain of perspectives.

    The relationships are presentation metadata, not factual claims. Each
    card still links back to its own structured receipt and evidence drawer;
    the chain simply tells the reader why the next voice is worth opening.
    """

    entries: list[dict[str, Any]] = []
    ordered = sorted(
        (item for item in publication_articles if str(item.get("body") or "").strip()),
        key=lambda item: int(item.get("conversation_order") or 99),
    )
    previous_key = ""
    for item in ordered:
        structured = item.get("structured") if isinstance(item.get("structured"), Mapping) else {}
        fragment = item.get("story_fragment") if isinstance(item.get("story_fragment"), Mapping) else None
        if not isinstance(fragment, Mapping):
            # Keep this helper backwards-compatible for callers that provide
            # the small pre-publication shape directly. Runtime publications
            # always carry story_fragment_v1, so this branch cannot bypass the
            # publication gate for a real reader bundle.
            fragment = {
                "headline": _excerpt(structured.get("headline") or item.get("title"), 150),
                "lede": _excerpt(structured.get("lede"), 240),
                "thesis": _excerpt(structured.get("thesis") or structured.get("what_changed") or item.get("body"), 260),
                "counter_evidence": _excerpt(structured.get("counter_evidence"), 220),
                "evidence_ids": [
                    _text(value)
                    for value in (structured.get("evidence_ids") or structured.get("cited_evidence_ids") or [])
                    if _text(value)
                ],
            }
        item_persona = item.get("reporter_persona") if isinstance(item.get("reporter_persona"), Mapping) else {}
        entries.append(
            {
                "article_key": str(item.get("key") or ""),
                "title": str(item.get("title") or ""),
                "reporter_name": str(item.get("reporter_name") or item.get("assigned_reporter_name") or "The Front Office"),
                "assigned_reporter_name": str(item.get("assigned_reporter_name") or ""),
                "reporter_persona": dict(item_persona),
                "relation": str(item.get("conversation_relation") or "continues the room"),
                "caption": str(item.get("conversation_caption") or ""),
                "headline": str(fragment.get("headline") or item.get("title") or "Desk read"),
                "lede": str(fragment.get("lede") or ""),
                "thesis": str(fragment.get("thesis") or ""),
                "counter_evidence": str(fragment.get("counter_evidence") or ""),
                "room_move": str((item.get("structured") or {}).get("room_move") or "").strip().lower()
                if isinstance(item.get("structured"), Mapping)
                else "",
                "reply_to": str((item.get("structured") or {}).get("reply_to") or "").strip()
                if isinstance(item.get("structured"), Mapping)
                else "",
                "room_question": _excerpt((item.get("structured") or {}).get("room_question"), 180)
                if isinstance(item.get("structured"), Mapping)
                else "",
                "evidence_ids": list(fragment.get("evidence_ids") or [])[:40],
                "source_ids": list(fragment.get("source_ids") or [])[:40],
                "claim_positions": _claim_positions((item.get("structured") or {}).get("claim_positions"))
                if isinstance(item.get("structured"), Mapping)
                else [],
                "previous_article_key": previous_key,
                "publication_status": str(item.get("publication_status") or ""),
                "evidence_fingerprint": str(item.get("evidence_fingerprint") or ""),
                "reality_check": dict(item.get("reality_check") or {}) if isinstance(item.get("reality_check"), Mapping) else {},
            }
        )
        previous_key = str(item.get("key") or "")
    return entries


def _claim_positions(value: Any) -> list[dict[str, Any]]:
    """Keep the structured claim register small enough for reader and peer context."""

    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value[:12]:
        if not isinstance(item, Mapping):
            continue
        subject_key = _text(item.get("subject_key"))
        window = _text(item.get("decision_window")).lower()
        stance = _text(item.get("stance")).lower()
        summary = _excerpt(item.get("summary"), 220)
        evidence_ids = [
            _text(evidence_id)
            for evidence_id in (item.get("evidence_ids") or [])
            if _text(evidence_id)
        ][:12]
        if not subject_key or not window or not stance or not summary or not evidence_ids:
            continue
        output.append(
            {
                "subject_key": subject_key,
                "subject_label": _text(item.get("subject_label")) or subject_key,
                "decision_window": window,
                "stance": stance,
                "summary": summary,
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
            }
        )
    return output


def _newsroom_claim_conflicts(conversation: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compare same-subject, same-window positions without choosing a fake winner.

    A writer's prose is not parsed as fact. Only the structured claim register
    can enter this ledger, and every entry has already passed the article
    evidence boundary. The result distinguishes an explicit room disagreement
    from a conflict that still needs an editor or manager decision.
    """

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for article in conversation:
        article_key = _text(article.get("article_key"))
        reporter = _text(article.get("reporter_name")) or "The desk"
        for claim in _claim_positions(article.get("claim_positions")):
            key = (_text(claim.get("subject_key")).lower(), _text(claim.get("decision_window")).lower())
            if not key[0] or not key[1]:
                continue
            grouped.setdefault(key, []).append(
                {
                    "article_key": article_key,
                    "reporter_name": reporter,
                    "subject_key": claim["subject_key"],
                    "subject_label": claim["subject_label"],
                    "decision_window": claim["decision_window"],
                    "stance": claim["stance"],
                    "summary": claim["summary"],
                    "evidence_ids": claim["evidence_ids"],
                    "room_move": _text(article.get("room_move")).lower(),
                    "reply_to": _text(article.get("reply_to")),
                    "reality_check": article.get("reality_check") if isinstance(article.get("reality_check"), Mapping) else {},
                }
            )

    conflicts: list[dict[str, Any]] = []
    for (_, _), claims in grouped.items():
        stances = {_text(claim.get("stance")).lower() for claim in claims}
        direct_conflict = "positive" in stances and "negative" in stances
        conditional_conflict = "conditional" in stances and bool(stances & {"positive", "negative", "mixed"})
        mixed_conflict = "mixed" in stances and bool(stances & {"positive", "negative"})
        if not (direct_conflict or conditional_conflict or mixed_conflict):
            continue
        explicit_dispute = any(
            _text(claim.get("room_move")).lower() in {"disputes", "supersedes"}
            for claim in claims
        )
        high_reality_limit = any(
            any(
                _text(check.get("severity")).lower() == "high"
                for check in (claim.get("reality_check") or {}).get("matched_checks", [])
                if isinstance(check, Mapping)
            )
            for claim in claims
        )
        resolution_status = (
            "limited_by_reality_check"
            if high_reality_limit
            else "explicitly_disputed"
            if explicit_dispute
            else "unresolved"
        )
        all_evidence: list[str] = []
        for claim in claims:
            for evidence_id in claim.get("evidence_ids") or []:
                if evidence_id not in all_evidence:
                    all_evidence.append(evidence_id)
        conflicts.append(
            {
                "subject_key": claims[0]["subject_key"],
                "subject_label": claims[0]["subject_label"],
                "decision_window": claims[0]["decision_window"],
                "stances": sorted(stances),
                "resolution_status": resolution_status,
                "resolution": (
                    "Keep the competing reads conditional because a high-severity Reality Check limitation is present."
                    if resolution_status == "limited_by_reality_check"
                    else "The desks explicitly disagree; keep both receipts visible and do not select a winner without manager review."
                    if resolution_status == "explicitly_disputed"
                    else "The same subject and window have competing positions; the editor has not selected a winner."
                ),
                "claims": [
                    {
                        "article_key": claim["article_key"],
                        "reporter_name": claim["reporter_name"],
                        "stance": claim["stance"],
                        "summary": claim["summary"],
                        "evidence_ids": claim["evidence_ids"],
                    }
                    for claim in claims
                ],
                "evidence_ids": all_evidence[:24],
            }
        )
    return conflicts[:12]


def _newsroom_edges(conversation: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Create safe, queryable relationships between adjacent newsroom desks.

    An edge is editorial structure, not a new factual claim. The default is
    ``extends`` because a different evidence question should not be presented
    as disagreement unless the writer explicitly supplied that move. Explicit
    moves are accepted only when they point to a prior card in this issue.
    """

    allowed = {"supports", "disputes", "extends", "asks", "supersedes", "held_because"}
    seen_prior: set[str] = set()
    edges: list[dict[str, Any]] = []
    for item in conversation:
        target = str(item.get("article_key") or "").strip()
        source = str(item.get("reply_to") or item.get("previous_article_key") or "").strip()
        if source and source != target and source in seen_prior and target:
            relationship = str(item.get("room_move") or "extends").strip().lower()
            if relationship not in allowed:
                relationship = "extends"
            reporter = str(item.get("reporter_name") or item.get("assigned_reporter_name") or "The desk")
            caption = str(item.get("caption") or "adds a distinct evidence question")
            counterpoint = _excerpt(item.get("counter_evidence"), 180)
            summary = f"{reporter} {caption}; the relationship is editorial context, not source evidence."
            if relationship == "disputes" and counterpoint:
                summary += f" Counter-signal: {counterpoint}"
            edges.append(
                {
                    "source_article_key": source,
                    "target_article_key": target,
                    "relationship": relationship,
                    "summary": summary,
                    "source_evidence_ids": list(item.get("evidence_ids") or [])[:40],
                    "status": "visible" if str(item.get("publication_status") or "") != "held" else "held",
                }
            )
        if target:
            seen_prior.add(target)
    return edges


def _newsroom_summary(
    conversation: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    article_modes: Mapping[str, Any],
    *,
    claim_conflicts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Give the front page a truthful issue-level receipt without another LLM call."""

    expected = {str(key) for key in article_modes if str(key).strip()}
    available = {str(item.get("article_key") or "") for item in conversation if str(item.get("article_key") or "").strip()}
    relationships: dict[str, int] = {}
    for edge in edges:
        relationship = str(edge.get("relationship") or "extends").strip().lower()
        relationships[relationship] = relationships.get(relationship, 0) + 1
    missing = sorted(expected - available)
    held = sorted(
        str(item.get("article_key") or "")
        for item in conversation
        if str(item.get("publication_status") or "").lower() == "held"
    )
    questions = [
        {
            "article_key": str(item.get("article_key") or ""),
            "reporter_name": str(item.get("reporter_name") or "The desk"),
            "question": _excerpt(item.get("room_question"), 180),
        }
        for item in conversation
        if str(item.get("room_question") or "").strip()
    ]
    tensions = [
        {
            "source_article_key": str(edge.get("source_article_key") or ""),
            "target_article_key": str(edge.get("target_article_key") or ""),
            "relationship": str(edge.get("relationship") or "extends"),
            "summary": _excerpt(edge.get("summary"), 300),
        }
        for edge in edges
        if str(edge.get("relationship") or "").lower() in {"disputes", "supersedes"}
    ]
    agreements = [
        {
            "source_article_key": str(edge.get("source_article_key") or ""),
            "target_article_key": str(edge.get("target_article_key") or ""),
            "relationship": str(edge.get("relationship") or "supports"),
            "summary": _excerpt(edge.get("summary"), 300),
        }
        for edge in edges
        if str(edge.get("relationship") or "").lower() in {"supports", "held_because"}
    ]
    next_question = (
        str(questions[0].get("question") or "").strip()
        if questions
        else "Which desk read should change the manager's next investigation?"
    )
    return {
        "expected_desks": len(expected),
        "available_desks": len(available),
        "missing_desks": missing,
        "edge_count": len(edges),
        "relationship_counts": dict(sorted(relationships.items())),
        "disagreement_count": relationships.get("disputes", 0),
        "claim_conflict_count": len(claim_conflicts or []),
        "unresolved_claim_conflict_count": sum(
            1
            for conflict in (claim_conflicts or [])
            if _text(conflict.get("resolution_status")) in {"unresolved", "explicitly_disputed"}
        ),
        "claim_conflicts": [dict(conflict) for conflict in (claim_conflicts or [])[:8]],
        "agreement_count": len(agreements),
        "held_desks": held,
        "open_questions": questions[:5],
        "agreements": agreements[:5],
        "tensions": tensions[:5],
        "room_synthesis": {
            "agreement_count": len(agreements),
            "disagreement_count": len(tensions),
            "next_question": next_question,
            "agreements": agreements[:5],
            "tensions": tensions[:5],
            "open_questions": questions[:5],
        },
        "status": "complete" if expected and not missing else "partial" if available else "empty",
        "note": (
            "The room has no publishable desk notes yet; the deterministic evidence board remains available."
            if not available
            else f"{len(missing)} desk{' is' if len(missing) == 1 else 's are'} missing from the printed conversation."
            if missing
            else "All registered desk notes are present in the printed conversation."
        ),
    }


def review_publication_article(
    article_key: str,
    body: str,
    receipt: Mapping[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    """Run the deterministic desk-editor gate before content reaches the reader.

    This is intentionally a review, not a second scoring model. It verifies
    that the writer supplied the structured story spine and a real evidence
    receipt, then honors an optional persisted Luna desk decision. The
    deterministic checks remain authoritative at the seam: a stored approval
    cannot revive an article whose current receipt or story spine is invalid.
    """

    receipt = receipt if isinstance(receipt, Mapping) else {}
    structured = receipt.get("structured") if isinstance(receipt.get("structured"), Mapping) else {}
    evidence_ids = structured.get("evidence_ids") if isinstance(structured.get("evidence_ids"), list) else []
    source_ids = structured.get("source_ids") if isinstance(structured.get("source_ids"), list) else []
    errors: list[str] = []
    checks = {
        "body_present": bool(str(body or "").strip()),
        "structured_story_spine": True,
        "evidence_receipt": bool([item for item in evidence_ids if str(item).strip()]),
        "source_receipt": bool([item for item in source_ids if str(item).strip()]),
        "mode_contract": mode in {"deterministic_template", "automatic_llm"},
    }
    if not checks["body_present"]:
        errors.append("article body is empty")
    required_fields = ("headline", "thesis", "what_changed", "action")
    missing_fields = [field for field in required_fields if not str(structured.get(field) or "").strip()]
    if missing_fields:
        checks["structured_story_spine"] = False
        errors.append("structured story spine is missing " + ", ".join(missing_fields))
    if not checks["evidence_receipt"]:
        errors.append("no article-level evidence IDs are recorded")
    if not checks["source_receipt"]:
        errors.append("no source receipt is recorded")
    if not checks["mode_contract"]:
        errors.append(f"unknown publication mode {mode!r}")
    stored_editorial_review = receipt.get("editorial_review")
    stored_review = stored_editorial_review if isinstance(stored_editorial_review, Mapping) else {}
    editor_mode = _text(stored_review.get("mode"))
    stored_status = _text(stored_review.get("status"))
    if not errors and stored_review:
        if editor_mode == "llm" and stored_status in {"approved", "held"}:
            if stored_status == "held":
                errors.extend(
                    str(item).strip()
                    for item in (stored_review.get("errors") or [])
                    if str(item).strip()
                )
                if not errors:
                    errors.append("the persisted desk review held this article")
            status = stored_status
        elif editor_mode or stored_status:
            errors.append("editorial review receipt is incomplete or uses an unknown mode")
            status = "held"
        else:
            status = "approved"
    else:
        if errors:
            status = "held"
        elif mode == "deterministic_template":
            status = "fallback"
        else:
            status = "approved"
    decision = _text(stored_review.get("decision")) if stored_review else ""
    if decision not in {"approve", "modify", "hold"}:
        decision = "approve" if status == "approved" else "keep_fallback" if status == "fallback" else "hold"
    note = _text(stored_review.get("note")) if stored_review else ""
    if not note:
        note = (
            "Approved after deterministic evidence, source, and story-spine checks."
            if status == "approved"
            else "Published as the deterministic evidence-led fallback; no reporter draft is currently accepted."
            if status == "fallback"
            else "Held from the printed facade until the missing receipt or story field is repaired."
        )
    return {
        "editor": "The Desk Editor",
        "article_key": article_key,
        "mode": editor_mode or "deterministic",
        "model": _text(stored_review.get("model")),
        "status": status,
        "decision": decision,
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "changes": [str(item) for item in (stored_review.get("changes") or []) if str(item).strip()],
        "editor_notes": _text(stored_review.get("editor_notes")),
        "note": note,
    }


def publication_template(article_key: str) -> dict[str, Any]:
    """Return the reader layout contract for one newsroom desk."""

    template = PUBLICATION_TEMPLATE_REGISTRY.get(str(article_key or ""))
    if template is None:
        return {
            "template_id": "evidence-note",
            "label": "Evidence note",
            "layout": "rail",
            "section": "The Front Office",
            "list_preview_items": 3,
        }
    return dict(template)


def publication_content_blocks(body: str, article_key: str = "") -> list[dict[str, Any]]:
    """Convert stored markdown into safe, reusable reader blocks.

    Markdown remains the durable interchange format for operators and writers.
    The browser receives this small semantic projection so each template can
    render paragraphs, section headers, and lists without reparsing prose or
    inventing a second article model.
    """

    del article_key  # The layout contract is carried separately.
    text = _strip_front_matter(str(body or ""))
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    bullets: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            value = " ".join(part.strip() for part in paragraph if part.strip()).strip()
            if value:
                blocks.append({"type": "paragraph", "text": value})
            paragraph.clear()

    def flush_bullets() -> None:
        if bullets:
            blocks.append({"type": "list", "items": list(bullets)})
            bullets.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_bullets()
            continue
        if line.startswith("# "):
            flush_paragraph()
            flush_bullets()
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_bullets()
            blocks.append({"type": "heading", "text": line[3:].strip()})
            continue
        if line.startswith("- "):
            flush_paragraph()
            bullets.append(line[2:].strip())
            continue
        flush_bullets()
        paragraph.append(line)
    flush_paragraph()
    flush_bullets()
    return [{"block_id": f"block-{index}", **block} for index, block in enumerate(blocks, start=1)]


def _strip_front_matter(text: str) -> str:
    value = str(text or "")
    if not value.startswith("---"):
        return value
    parts = value.split("---", 2)
    return parts[2].lstrip("\r\n") if len(parts) == 3 else value


def _publication_reporter(
    writer_preferences: dict[str, Any],
    article_key: str,
    receipt: Mapping[str, Any],
    mode: str,
    default_reporter: dict[str, str],
) -> dict[str, str]:
    """Resolve the effective byline for a published article.

    Deterministic fallback content is always published by The Front Office;
    its assigned newsroom desk is carried separately. For a real generated
    receipt, preserve the reporter that actually wrote the artifact, but only
    when it resolves to a known persona.
    """

    receipt_id = _text(receipt.get("reporter_id")).lower()
    if mode == "deterministic_template":
        return front_office_metadata(article_key)
    if not receipt_id:
        return default_reporter
    scoped = dict(writer_preferences)
    overrides = dict(scoped.get("article_reporters") or {})
    overrides[article_key] = receipt_id
    scoped["article_reporters"] = overrides
    candidate = persona_metadata(scoped, article_key)
    return candidate if candidate["persona_id"] == receipt_id else default_reporter


def _assigned_publication_reporter(
    writer_preferences: dict[str, Any],
    article_key: str,
    receipt: Mapping[str, Any],
    default_reporter: dict[str, str],
) -> dict[str, str]:
    assigned_id = _text(receipt.get("assigned_reporter_id"))
    if not assigned_id:
        assigned_id = _text(receipt.get("reporter_id"))
    if not assigned_id or assigned_id == "front_office":
        return default_reporter
    scoped = dict(writer_preferences)
    overrides = dict(scoped.get("article_reporters") or {})
    overrides[article_key] = assigned_id
    scoped["article_reporters"] = overrides
    candidate = persona_metadata(scoped, article_key)
    return candidate if candidate["persona_id"] == assigned_id else default_reporter


def _publication_structured(
    receipt: Mapping[str, Any],
    mode: str,
    assigned_reporter: Mapping[str, Any],
) -> dict[str, Any]:
    structured = dict(receipt.get("structured") or {}) if isinstance(receipt.get("structured"), Mapping) else {}
    if mode != "deterministic_template":
        return structured
    assigned_name = _text(assigned_reporter.get("name"))
    if not assigned_name or assigned_name == "The Front Office":
        return structured

    def neutralize(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(assigned_name, "The Front Office")
        if isinstance(value, list):
            return [neutralize(item) for item in value]
        if isinstance(value, dict):
            return {key: neutralize(item) for key, item in value.items()}
        return value

    return neutralize(structured)


def _neutralize_reader_story(
    story: Mapping[str, Any],
    reporter: Mapping[str, Any],
    assigned_reporter: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(story)
    existing = (
        result.get("assigned_reporter_persona")
        if isinstance(result.get("assigned_reporter_persona"), Mapping)
        else result.get("reporter_persona")
        if isinstance(result.get("reporter_persona"), Mapping)
        else assigned_reporter
    )
    result["assigned_reporter_persona"] = dict(existing)
    result["assigned_reporter_id"] = _text(existing.get("persona_id"))
    result["assigned_reporter_name"] = _text(existing.get("name"))
    result["reporter_persona"] = dict(reporter)
    result["reporter_id"] = _text(reporter.get("persona_id")) or "front_office"
    result["reporter_name"] = _text(reporter.get("name")) or "The Front Office"
    result["reporter_label"] = "Desk"
    return result


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


def _market_clock_coverage(row: Mapping[str, Any]) -> int:
    """Count comparable clocks for available-market preview ranking."""

    try:
        return int(float(_text(row.get("fit_coverage")).split("/", 1)[0]))
    except (TypeError, ValueError):
        return sum(
            1
            for field in (
                "next_game_market_score",
                "rest_of_season_market_score",
                "dynasty_market_score",
                "career_projection_score",
            )
            if _text(row.get(field))
        )


def _number_or_text(value: Any) -> str | float:
    text = _text(value)
    if not text:
        return ""
    numeric = _number(text)
    return int(numeric) if numeric.is_integer() else numeric


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
