"""Resolve current Sleeper team labels without confusing them with identity.

Roster IDs establish ownership. Team names are mutable source labels, and a
private profile may also contain a Front Office label. This module keeps those
concerns separate while repairing the common case where an old Sleeper name
was persisted as if it were a deliberate customization.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _matching_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    league_id: str,
    season: str,
    roster_id: int | str | None,
) -> list[Mapping[str, Any]]:
    expected_roster_id = _int_or_none(roster_id)
    if expected_roster_id is None:
        return []
    expected_league_id = _clean(league_id)
    expected_season = _clean(season)
    return [
        row
        for row in rows
        if isinstance(row, Mapping)
        and _int_or_none(row.get("roster_id")) == expected_roster_id
        and (not expected_league_id or _clean(row.get("league_id")) == expected_league_id)
        and (not expected_season or _clean(row.get("season")) == expected_season)
    ]


def current_sleeper_team_name(
    rows: Iterable[Mapping[str, Any]],
    *,
    league_id: str = "",
    season: str = "",
    roster_id: int | str | None = None,
) -> str:
    """Return the current source label for one exact league/season/roster."""

    rows = list(rows)
    for row in _matching_rows(rows, league_id=league_id, season=season, roster_id=roster_id):
        label = _clean(row.get("team_name")) or _clean(row.get("display_name"))
        if label:
            return label
    return ""


def sleeper_team_name_aliases(
    rows: Iterable[Mapping[str, Any]],
    *,
    league_id: str = "",
    season: str = "",
    roster_id: int | str | None = None,
) -> set[str]:
    """Return known source labels for the same roster lineage.

    Historical roster IDs can be reused by a different owner, so when the
    current row carries an owner ID we restrict aliases to that owner. The
    aliases are only used to recognize stale source labels; they never select
    a roster.
    """

    rows = list(rows)
    current_rows = _matching_rows(rows, league_id=league_id, season=season, roster_id=roster_id)
    if not current_rows:
        return set()
    owner_ids = {_clean(row.get("owner_id")) for row in current_rows if _clean(row.get("owner_id"))}
    expected_roster_id = _int_or_none(roster_id)
    aliases: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or _int_or_none(row.get("roster_id")) != expected_roster_id:
            continue
        owner_id = _clean(row.get("owner_id"))
        if owner_ids and owner_id and owner_id not in owner_ids:
            continue
        for field in ("team_name", "display_name"):
            label = _clean(row.get(field))
            if label:
                aliases.add(label.casefold())
    return aliases


def resolve_team_name(
    profile_name: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    league_id: str = "",
    season: str = "",
    roster_id: int | str | None = None,
) -> str:
    """Resolve a private label against the current source-backed team name.

    Empty profiles use the current Sleeper label. A profile value that matches
    a known source alias is treated as a stale source label and follows the
    current name. Any other non-empty value is retained as an intentional
    Front Office customization.
    """

    rows = list(rows)
    candidate = _clean(profile_name)
    source_name = current_sleeper_team_name(
        rows,
        league_id=league_id,
        season=season,
        roster_id=roster_id,
    )
    if not source_name:
        return candidate
    aliases = sleeper_team_name_aliases(
        rows,
        league_id=league_id,
        season=season,
        roster_id=roster_id,
    )
    if not candidate or candidate.casefold() in aliases:
        return source_name
    return candidate
