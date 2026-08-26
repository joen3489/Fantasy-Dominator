"""Explicit ownership and customization context for fantasy workspaces.

The original application treated the checked-in YAML configuration as the
current user's team.  That is useful as a legacy default, but it is not a
safe boundary once one installation can serve more than one user or league.
This module keeps the boundary small and serializable so refresh, analysis,
and writer workflows can all receive the same context.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from .personas import normalize_writer_preferences


@dataclass(frozen=True)
class FantasyContext:
    """The identity and customization scope for one managed fantasy team."""

    user_id: str | None
    league_id: str
    season: str
    roster_id: int | None
    league_type: str = "dynasty"
    league_name: str = ""
    team_name: str = ""
    display_name: str = ""
    sleeper_user_id: str | None = None
    strategy_profile: dict[str, Any] = field(default_factory=dict)
    writer_preferences: dict[str, Any] = field(default_factory=dict)
    manager_trade_profiles: list[dict[str, Any]] = field(default_factory=list)
    identity_status: str = "unverified"
    identity_checked_at: str = ""

    @property
    def scope_key(self) -> str:
        """Return a stable key suitable for logs and artifact metadata."""

        owner = self.user_id or "legacy"
        roster = self.roster_id if self.roster_id is not None else "unassigned"
        return f"{owner}:{self.league_id}:{self.season}:{roster}"

    @property
    def is_legacy(self) -> bool:
        return self.user_id is None


def _as_dict(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def scoped_config(base_config: Mapping[str, Any], context: FantasyContext) -> dict[str, Any]:
    """Return a config copy whose team-specific values belong to ``context``.

    Existing analytical functions accept the project's mapping-shaped config.
    Producing a scoped copy lets those functions remain deterministic while
    preventing a global ``current_team`` or ``strategy_profile`` from leaking
    into another league.
    """

    config = deepcopy(dict(base_config))

    current_team = _as_dict(config.get("current_team"))
    if context.roster_id is not None:
        current_team["roster_id"] = context.roster_id
    if not context.is_legacy:
        # Do not let the legacy singleton's name or display identity leak into
        # a newly linked user's scope when that user has not customized it yet.
        current_team["team_name"] = context.team_name
        current_team["display_name"] = context.display_name
    elif context.team_name:
        current_team["team_name"] = context.team_name
    elif context.display_name:
        current_team["display_name"] = context.display_name
    config["current_team"] = current_team

    if context.season:
        config["current_season"] = context.season
    config["strategy_profile"] = (
        deepcopy(context.strategy_profile)
        if not context.is_legacy
        else deepcopy(context.strategy_profile or config.get("strategy_profile") or {})
    )
    config["writer_preferences"] = normalize_writer_preferences(context.writer_preferences)
    config["manager_trade_profiles"] = deepcopy(context.manager_trade_profiles)

    # These fields are intentionally metadata rather than configuration used
    # by the legacy analytics modules.  They make the selected scope visible
    # to downstream artifact builders and future writers.
    config["context"] = {
        "user_id": context.user_id,
        "league_id": context.league_id,
        "season": context.season,
        "roster_id": context.roster_id,
        "league_type": context.league_type,
        "league_name": context.league_name,
        "team_name": context.team_name,
        "display_name": context.display_name,
        "sleeper_user_id": context.sleeper_user_id,
        "identity_status": context.identity_status,
        "identity_checked_at": context.identity_checked_at,
        "writer_preferences": normalize_writer_preferences(context.writer_preferences),
        "manager_trade_profiles": deepcopy(context.manager_trade_profiles),
    }
    return config


def context_from_league_row(
    user_id: str | int,
    league: Mapping[str, Any],
    profile: Mapping[str, Any] | None = None,
    manager_trade_profiles: list[Mapping[str, Any]] | None = None,
) -> FantasyContext:
    """Build a context from a row returned by ``app.db.list_user_leagues``."""

    profile = profile or {}
    strategy = profile.get("strategy_profile", profile.get("strategy_json", {}))
    writer_preferences = profile.get(
        "writer_preferences", profile.get("writer_preferences_json", {})
    )
    if not isinstance(strategy, Mapping):
        strategy = {}
    if not isinstance(writer_preferences, Mapping):
        writer_preferences = {}

    # The authenticated league row is the only identity boundary. A private
    # profile may contain a stale roster from an older migration, so it must
    # never resurrect an unverified or missing Sleeper roster assignment.
    roster_id = league.get("roster_id")
    try:
        roster_id = int(roster_id) if roster_id is not None else None
    except (TypeError, ValueError):
        roster_id = None

    identity_status = str(
        league.get("identity_status")
        or ("verified_roster_match" if roster_id is not None else "unverified")
    )
    identity_verified = identity_status.lower() in {"verified", "verified_roster_match"} and roster_id is not None

    return FantasyContext(
        user_id=str(user_id),
        league_id=str(league.get("league_id", "")),
        season=str(league.get("season", "")),
        roster_id=roster_id,
        league_type=str(league.get("league_type", "dynasty")),
        league_name=str(league.get("name", league.get("league_name", ""))),
        team_name=str(profile.get("team_name", "")) if identity_verified else "",
        display_name=str(profile.get("display_name", "")) if identity_verified else "",
        sleeper_user_id=str(league.get("sleeper_user_id") or "") or None,
        strategy_profile=deepcopy(dict(strategy)),
        writer_preferences=deepcopy(dict(writer_preferences)),
        manager_trade_profiles=[deepcopy(dict(item)) for item in (manager_trade_profiles or []) if isinstance(item, Mapping)],
        identity_status=identity_status,
        identity_checked_at=str(league.get("identity_checked_at") or ""),
    )
