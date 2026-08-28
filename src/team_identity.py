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


def historical_sleeper_team_names(
    rows: Iterable[Mapping[str, Any]],
    *,
    league_id: str = "",
    season: str = "",
    roster_id: int | str | None = None,
) -> set[str]:
    """Return historical team-name labels for this same-owner roster lineage.

    This is intentionally narrower than ``sleeper_team_name_aliases``: article
    presentation may repair an old team name, but it must not rewrite a
    manager's Sleeper display name into the team's current label.
    """

    rows = list(rows)
    current_name = current_sleeper_team_name(
        rows,
        league_id=league_id,
        season=season,
        roster_id=roster_id,
    )
    current_rows = _matching_rows(rows, league_id=league_id, season=season, roster_id=roster_id)
    if not current_rows or not current_name:
        return set()
    owner_ids = {_clean(row.get("owner_id")) for row in current_rows if _clean(row.get("owner_id"))}
    expected_roster_id = _int_or_none(roster_id)
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or _int_or_none(row.get("roster_id")) != expected_roster_id:
            continue
        owner_id = _clean(row.get("owner_id"))
        if owner_ids and owner_id and owner_id not in owner_ids:
            continue
        name = _clean(row.get("team_name"))
        if name and name.casefold() != current_name.casefold():
            names.add(name)
    return names


def current_sleeper_team_label_migrations(
    rows: Iterable[Mapping[str, Any]],
    *,
    league_id: str = "",
    season: str = "",
) -> dict[str, str]:
    """Map historical source team names to current names by owner lineage.

    The map is presentation-only. It lets current decision surfaces stop using
    an old mutable Sleeper team name without changing historical tables. Owner
    ID is the lineage key when available because roster IDs can change or be
    reused between seasons. If an old label could identify more than one
    current owner, it is omitted rather than guessed.
    """

    rows = [row for row in rows if isinstance(row, Mapping)]
    expected_league_id = _clean(league_id)
    expected_season = _clean(season)
    current_rows = [
        row
        for row in rows
        if (not expected_league_id or _clean(row.get("league_id")) == expected_league_id)
        and (not expected_season or _clean(row.get("season")) == expected_season)
        and (_clean(row.get("team_name")) or _clean(row.get("display_name")))
    ]
    candidates: dict[str, tuple[str, set[str]]] = {}
    for current in current_rows:
        current_name = _clean(current.get("team_name")) or _clean(current.get("display_name"))
        owner_id = _clean(current.get("owner_id"))
        roster_id = _int_or_none(current.get("roster_id"))
        if not current_name:
            continue
        for historical in rows:
            if owner_id:
                if _clean(historical.get("owner_id")) != owner_id:
                    continue
            elif roster_id is None or _int_or_none(historical.get("roster_id")) != roster_id:
                continue
            historical_name = _clean(historical.get("team_name"))
            if not historical_name or historical_name.casefold() == current_name.casefold():
                continue
            folded = historical_name.casefold()
            original, destinations = candidates.setdefault(folded, (historical_name, set()))
            destinations.add(current_name)
            candidates[folded] = (original, destinations)
    return {
        original: next(iter(destinations))
        for original, destinations in candidates.values()
        if len(destinations) == 1
    }


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
