"""Deterministic player value across four decision windows of a dynasty league.

The existing projection table is a season baseline and the weekly table is an
opponent-neutral allocation of that baseline.  This module keeps those facts
separate from the decision horizon that consumes them.  It intentionally does
not manufacture a lifetime career-points forecast: the dynasty lane is a
market and timeline lens over observed market evidence, age, and production
context, while the separate career field is a bounded five-year scenario
anchored to preserved historical production when a unique source join exists.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any
import unicodedata

import pandas as pd

from .availability import availability_factor as shared_availability_factor
from .availability import availability_note as shared_availability_note
from .availability import current_availability_status
from .projections import _normalize_name, _prepared_stats, _project_player, _scoring_settings


HORIZON_MODEL_VERSION = "horizon_market_v2"
HORIZON_SCORE_BASIS = (
    "position-relative percentile score from 0-100 within the current season cohort; "
    "not a dollar market value and not a cross-position price ranking"
)

HORIZON_COLUMNS = [
    "season",
    "league_id",
    "as_of_week",
    "horizon_model_version",
    "horizon_score_basis",
    "next_game_week",
    "player_id",
    "player_name",
    "position",
    "age",
    "roster_id",
    "team_name",
    "availability_scope",
    "current_availability_status",
    "injury_status",
    "injury_body_part",
    "availability_note",
    "projection_ppg",
    "projection_confidence",
    "market_value",
    "market_percentile",
    "market_source_count",
    "market_disagreement_score",
    "market_source_confidence",
    "next_game_baseline_points",
    "next_game_expected_points",
    "next_game_market_score",
    "next_game_minus_market_delta",
    "next_game_status",
    "next_game_basis",
    "next_game_opponent",
    "next_game_home_away",
    "next_game_schedule_status",
    "next_game_matchup_factor",
    "next_game_matchup_validation_status",
    "next_game_matchup_validation_games",
    "next_game_matchup_validation_mae_delta",
    "next_game_matchup_adjustment_status",
    "rest_of_season_weeks",
    "rest_of_season_games",
    "rest_of_season_bye_weeks",
    "rest_of_season_baseline_points",
    "rest_of_season_ppg",
    "rest_of_season_market_score",
    "rest_of_season_minus_market_delta",
    "rest_of_season_minus_next_game_delta",
    "rest_of_season_status",
    "rest_of_season_basis",
    "schedule_status",
    "dynasty_market_score",
    "dynasty_minus_market_delta",
    "dynasty_minus_rest_of_season_delta",
    "dynasty_status",
    "dynasty_basis",
    "career_projection_years",
    "career_projection_points",
    "career_projection_ppg",
    "career_projection_score",
    "career_minus_market_delta",
    "career_minus_dynasty_delta",
    "career_projection_status",
    "career_projection_basis",
    "career_history_join_method",
    "career_history_source_player_id",
    "career_history_status",
    "career_history_seasons",
    "career_history_games",
    "career_history_ppg",
    "career_history_latest_season",
    "contender_fit_score",
    "rebuilder_fit_score",
    "fit_coverage",
    "fit_basis",
    "rebuilder_contender_spread",
    "value_lane",
    "confidence",
    "evidence",
    "risk",
    "source_trace",
]

# Available players are deliberately kept out of the rostered-player horizon
# table.  Ownership is a league fact, while the market file is an external
# ranking and must not silently become a Sleeper roster.  This table reuses the
# same clock columns but carries an explicit availability and identity receipt.
AVAILABLE_HORIZON_COLUMNS = [
    "league_id",
    "availability_status",
    "identity_status",
    "market_rank",
    *(column for column in HORIZON_COLUMNS if column != "league_id"),
]

_POSITIONS = ("QB", "RB", "WR", "TE")
HORIZON_FIT_WEIGHT_KEYS = ("next_game", "rest_of_season", "dynasty", "career_window")
DEFAULT_HORIZON_FIT_WEIGHTS = {
    "contender": {
        "next_game": 0.52,
        "rest_of_season": 0.34,
        "dynasty": 0.09,
        "career_window": 0.05,
    },
    "rebuilder": {
        "next_game": 0.08,
        "rest_of_season": 0.22,
        "dynasty": 0.40,
        "career_window": 0.30,
    },
}


def build_player_horizon_market_scores(
    season_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    signal_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    config: dict[str, Any] | None = None,
    schedule_df: pd.DataFrame | None = None,
    defense_df: pd.DataFrame | None = None,
    usage_df: pd.DataFrame | None = None,
    market_consensus_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one evidence-backed value row per projected player/roster.

    ``next_game`` uses a schedule and historical position-specific defensive
    factor when those sources are available; otherwise it remains an explicit
    opponent-neutral weekly allocation. ``rest_of_season`` counts scheduled
    games when the team's schedule is known and calendar weeks otherwise.
    ``dynasty`` is a market/timeline score, not a career fantasy-points
    projection.
    """

    config = config or {}
    if season_df is None or season_df.empty:
        return pd.DataFrame(columns=HORIZON_COLUMNS)

    season = str(config.get("current_season") or _first_value(season_df, "season"))
    scope_league_id = _scope_league_id(config)
    as_of_week = _clamp_week(config.get("current_week", config.get("maintenance_week_end", 0)))
    next_week = as_of_week + 1 if as_of_week < 17 else None
    current_season = season_df[season_df.get("season", "").astype(str) == season].copy() if "season" in season_df else season_df.copy()
    if current_season.empty:
        current_season = season_df.copy()
    if scope_league_id and "league_id" in current_season.columns:
        identified = current_season[current_season["league_id"].map(_safe_text) != ""]
        if not identified.empty:
            current_season = identified[
                identified["league_id"].map(lambda value: _same_identifier(value, scope_league_id))
            ].copy()
            if current_season.empty:
                # A scoped projection frame that proves it belongs to another
                # league must not fall back to an unscoped player universe.
                return pd.DataFrame(columns=HORIZON_COLUMNS)
    current_weekly = weekly_df.copy() if isinstance(weekly_df, pd.DataFrame) else pd.DataFrame()
    if "season" in current_weekly.columns:
        current_weekly = current_weekly[current_weekly["season"].astype(str) == season]
    signals = _row_map(signal_df, "player_id")
    market_consensus = _row_map(market_consensus_df, "player_id")
    market_consensus_by_name = _market_consensus_name_map(market_consensus_df)
    roster = _roster_map(roster_players_df, season, scope_league_id)
    weekly_next = _next_week_map(current_weekly, next_week)
    weekly_values = _positive_values(current_weekly, "projected_fantasy_points", "position")
    ros_values = _ros_values(current_season, as_of_week)
    ppg_values = _positive_values(current_season, "projected_ppg", "position")
    schedule_frame = _schedule_frame(schedule_df, season)
    defense_map = _defense_map(defense_df)
    career_history = _career_history_map(usage_df, season)
    fit_weights, fit_weight_profile = resolve_horizon_fit_weights(
        config.get("strategy_profile")
    )

    career_context_by_player: dict[str, dict[str, Any]] = {}
    career_values: dict[str, list[float]] = {}
    for _, player in current_season.fillna("").iterrows():
        player_id = str(player.get("player_id") or "")
        signal = signals.get(player_id, {})
        roster_row = roster.get(player_id, {})
        position = str(player.get("position") or signal.get("position") or roster_row.get("position") or "")
        age = _num(signal.get("age", roster_row.get("age", player.get("age"))))
        ppg = _num(player.get("projected_ppg"))
        projected_games = _num(player.get("projected_games"))
        history = career_history.get(
            (_history_name_key(player.get("player_name")), position.upper()),
            _empty_career_history("not_matched"),
        )
        career = _career_projection(position, age, ppg, projected_games, history)
        career_context_by_player[player_id] = career
        if career.get("points") is not None and career.get("points", 0) > 0:
            career_values.setdefault(position, []).append(float(career["points"]))

    # Calculate matchup-adjusted next-game baselines for every player first so
    # the percentile score compares like with like rather than ranking one
    # opponent-adjusted row against a pool of flat allocations.
    next_context_by_player: dict[str, dict[str, Any]] = {}
    next_values: dict[str, list[float]] = {}
    for _, player in current_season.fillna("").iterrows():
        player_id = str(player.get("player_id") or "")
        roster_row = roster.get(player_id, {})
        position = str(player.get("position") or roster_row.get("position") or "")
        team = str(player.get("team") or roster_row.get("nfl_team") or "").upper()
        ppg = _num(player.get("projected_ppg"))
        season_points = _num(player.get("projected_fantasy_points"))
        baseline, basis = _next_baseline_points(
            player_id, position, ppg, season_points, weekly_next, next_week
        )
        schedule_context = _schedule_team_context(schedule_frame, team, next_week, as_of_week)
        opponent = str(schedule_context.get("opponent") or "")
        factor_row = defense_map.get((opponent, position), {}) if opponent else {}
        matchup_factor = _num_or_none(factor_row.get("matchup_factor"))
        matchup_validation_status = str(factor_row.get("validation_status") or "unavailable")
        matchup_validation_games = _num_or_none(factor_row.get("validation_games"))
        matchup_validation_mae_delta = _num_or_none(factor_row.get("validation_mae_delta"))
        matchup_adjustment_status = _matchup_adjustment_status(matchup_factor, matchup_validation_status)
        if schedule_context.get("next_status") == "bye":
            adjusted = 0.0 if baseline is not None else None
        elif baseline is None:
            adjusted = None
        elif matchup_adjustment_status != "applied":
            # A factor that has not earned an improving holdout receipt is
            # useful context, but it must not change the points or percentile.
            adjusted = round(baseline, 2)
        else:
            adjusted = round(baseline * matchup_factor, 2)
        next_context_by_player[player_id] = {
            "baseline": baseline,
            "basis": basis,
            "adjusted": adjusted,
            "opponent": opponent,
            "home_away": schedule_context.get("home_away", ""),
            "schedule_status": schedule_context.get("next_status", "schedule_unavailable"),
            "schedule_coverage": schedule_context.get("coverage", "schedule_unavailable"),
            "matchup_factor": matchup_factor,
            "matchup_validation_status": matchup_validation_status,
            "matchup_validation_games": matchup_validation_games,
            "matchup_validation_mae_delta": matchup_validation_mae_delta,
            "matchup_adjustment_status": matchup_adjustment_status,
            "rest_games": schedule_context.get("rest_games"),
            "bye_weeks": schedule_context.get("bye_weeks"),
        }
        availability_record = dict(roster_row)
        if "nfl_team" not in availability_record and "team" not in availability_record:
            projected_team = str(player.get("team") or "").strip()
            if projected_team:
                availability_record["team"] = projected_team
        availability_status = current_availability_status(availability_record)
        if adjusted is not None and adjusted > 0 and availability_status != "no_current_nfl_team":
            next_values.setdefault(position, []).append(adjusted)

    rows: list[dict[str, Any]] = []
    for _, player in current_season.fillna("").iterrows():
        player_id = str(player.get("player_id") or "")
        signal = signals.get(player_id, {})
        roster_row = roster.get(player_id, {})
        position = str(player.get("position") or signal.get("position") or roster_row.get("position") or "")
        age = _num(signal.get("age", roster_row.get("age", player.get("age"))))
        ppg = _num(player.get("projected_ppg"))
        season_points = _num(player.get("projected_fantasy_points"))
        projection_confidence = str(player.get("projection_confidence") or signal.get("projection_confidence") or "low")
        market_value = _num_or_none(signal.get("market_value"))
        if market_value is not None and market_value <= 0:
            market_value = None
        market_percentile = _num_or_none(signal.get("market_percentile"))
        market_record = market_consensus.get(player_id, {})
        if not market_record:
            name_key = (_canonical_market_name(player.get("player_name")), str(position).upper().strip())
            name_matches = market_consensus_by_name.get(name_key, [])
            if len(name_matches) == 1:
                # Some market providers do not publish a Sleeper ID. A unique
                # name+position bridge is safe for the market receipt, while
                # ambiguous matches remain unresolved and blank.
                market_record = name_matches[0]
        market_source_count = _num_or_none(market_record.get("source_count"))
        if market_source_count is not None:
            market_source_count = int(market_source_count)
        market_disagreement_score = _num_or_none(market_record.get("disagreement_score"))
        market_source_confidence = str(market_record.get("confidence") or "")
        career = career_context_by_player.get(player_id, {})
        availability_record = dict(roster_row)
        if "nfl_team" not in availability_record and "team" not in availability_record:
            projected_team = str(player.get("team") or "").strip()
            if projected_team:
                availability_record["team"] = projected_team
        availability_status = current_availability_status(availability_record)
        injury_status = str(roster_row.get("injury_status") or "")
        injury_body_part = str(roster_row.get("injury_body_part") or "")
        availability_note = shared_availability_note(availability_record)
        immediate_factor, availability_label = shared_availability_factor(availability_record)

        next_context = next_context_by_player.get(player_id, {})
        baseline_next = next_context.get("baseline")
        next_basis = str(next_context.get("basis") or "")
        adjusted_next = next_context.get("adjusted")
        opponent = str(next_context.get("opponent") or "")
        home_away = str(next_context.get("home_away") or "")
        schedule_status = str(next_context.get("schedule_status") or "schedule_unavailable")
        schedule_coverage = str(next_context.get("schedule_coverage") or "schedule_unavailable")
        matchup_factor = next_context.get("matchup_factor")
        matchup_validation_status = str(next_context.get("matchup_validation_status") or "unavailable")
        matchup_validation_games = next_context.get("matchup_validation_games")
        matchup_validation_mae_delta = next_context.get("matchup_validation_mae_delta")
        matchup_adjustment_status = str(next_context.get("matchup_adjustment_status") or "unavailable")
        rest_games = next_context.get("rest_games")
        bye_weeks = next_context.get("bye_weeks")
        if opponent and adjusted_next is not None:
            factor_note = (
                (
                    f"; historical {position} matchup factor={_display(matchup_factor)} applied"
                    if matchup_adjustment_status == "applied"
                    else f"; historical {position} matchup factor={_display(matchup_factor)} descriptive only; not applied"
                )
                if matchup_factor is not None
                else "; opponent context only, no defensive factor available"
            )
            validation_note = (
                f"; holdout validation={matchup_validation_status} across {_display(matchup_validation_games)} games"
                f" (MAE delta {_display(matchup_validation_mae_delta)})"
                if matchup_factor is not None
                else ""
            )
            adjustment_note = (
                "; schedule-aware adjustment applied to the weekly baseline"
                if matchup_adjustment_status == "applied"
                else "; factor is descriptive only; expected points remain at the weekly baseline"
            )
            next_basis = (
                f"{next_basis}; scheduled {home_away or 'game'} vs {opponent}"
                f"{factor_note}{validation_note}{adjustment_note}"
            )
        elif schedule_status == "bye":
            next_basis = "The team's schedule shows a bye in the next NFL week; expected fantasy points are zero for this week."
        elif schedule_coverage == "schedule_team_unmatched":
            next_basis = f"{next_basis}; schedule source is present but the player's team abbreviation did not match."
        elif schedule_coverage == "schedule_partial":
            next_basis = f"{next_basis}; schedule source is present but coverage is incomplete, so opponent and bye claims are withheld."
        if availability_status == "no_current_nfl_team":
            next_expected = None
            next_score = None
            next_status = "unavailable_no_current_nfl_team"
            next_basis = (
                "Sleeper currently lists no NFL team; historical weekly production is retained as context, "
                "but no next-game expectation is published until the player has a team."
            )
        elif baseline_next is None:
            next_expected = None
            next_score = None
            next_status = "season_complete" if next_week is None else "unavailable_missing_projection"
        else:
            next_value = float(adjusted_next if adjusted_next is not None else baseline_next)
            next_expected = round(next_value * immediate_factor, 2)
            weekly_percentile = _midrank_percentile(
                next_value, next_values.get(position, weekly_values.get(position, []))
            )
            next_score = round(weekly_percentile * immediate_factor, 2)
            if schedule_status == "bye":
                next_status = "bye_week"
            elif opponent and matchup_adjustment_status == "applied":
                next_status = "schedule_aware_matchup_projection" if availability_label == "available" else f"availability_flagged_{availability_label}"
            elif opponent:
                next_status = "schedule_aware_opponent_context" if availability_label == "available" else f"availability_flagged_{availability_label}"
            else:
                next_status = "opponent_neutral_weekly_allocation" if availability_label == "available" else f"availability_flagged_{availability_label}"

        remaining_weeks = max(0, 17 - as_of_week)
        if rest_games is not None and ppg > 0:
            ros_baseline = round(ppg * int(rest_games), 2)
            ros_games = int(rest_games)
            ros_byes = int(bye_weeks or 0)
        else:
            ros_baseline = round((season_points / 17.0) * remaining_weeks, 2) if season_points > 0 else None
            ros_games = None
            ros_byes = None
        ros_ppg = round(ppg, 2) if ppg > 0 else None
        if availability_status == "no_current_nfl_team":
            ros_score = None
            ros_status = "unavailable_no_current_nfl_team"
            ros_basis = (
                f"historical production baseline {ppg:.2f} PPG is retained for context, but Sleeper currently "
                "lists no NFL team; rest-of-season utility is conditional on signing"
            )
        elif ros_baseline is None:
            ros_score = None
            ros_status = "season_complete" if remaining_weeks == 0 else "unavailable_missing_projection"
            ros_basis = "No season projection is available; zero is not a forecast."
        else:
            ros_score = _midrank_percentile(ros_baseline, ros_values.get(position, []))
            if ros_games is not None:
                ros_status = "schedule_aware_games_baseline"
                ros_basis = (
                    f"projected PPG {ppg:.2f} across {ros_games} scheduled games and {ros_byes} bye week(s); "
                    "opponent strength beyond the next game is not modeled; "
                    "this is a production baseline, and the rest-of-season baseline is not recovery-adjusted"
                )
            else:
                ros_status = "season_projection_baseline"
                ros_basis = (
                    f"season projection {season_points:.2f} points allocated across {remaining_weeks} remaining weeks; "
                    "schedule unavailable, not a schedule-adjusted forecast; "
                    "this is a production baseline, and the rest-of-season baseline is not recovery-adjusted"
                )

        if market_percentile is not None and market_value is not None and market_value > 0:
            longevity = _dynasty_longevity_score(position, age)
            dynasty_score = round((market_percentile * 0.75) + (longevity * 0.25), 2)
            dynasty_status = (
                "conditional_no_current_nfl_team_external_market_plus_timeline"
                if availability_status == "no_current_nfl_team"
                else "external_market_plus_timeline"
            )
            dynasty_basis = (
                "position market percentile plus age/position timeline; current team absence is a material risk; not a career-points forecast"
                if availability_status == "no_current_nfl_team"
                else "position market percentile plus age/position timeline; not a career-points forecast"
            )
        elif ppg > 0:
            production_percentile = _midrank_percentile(ppg, ppg_values.get(position, []))
            longevity = _dynasty_longevity_score(position, age)
            dynasty_score = round((production_percentile * 0.65) + (longevity * 0.35), 2)
            dynasty_status = "internal_proxy_production_age"
            dynasty_basis = "projected PPG percentile plus age/position timeline; market evidence unavailable; not a career-points forecast"
        else:
            dynasty_score = None
            dynasty_status = "unavailable_missing_market_and_projection"
            dynasty_basis = "No market or projection evidence is available; zero is not a dynasty forecast."

        career_points = career.get("points")
        career_score = (
            _midrank_percentile(float(career_points), career_values.get(position, []))
            if career_points is not None
            else None
        )

        # These transitions are deliberately separate from contender/rebuilder
        # fit.  They show where a player gains or loses value as the decision
        # window moves forward, while preserving missing evidence as missing.
        rest_minus_next = _score_delta(ros_score, next_score)
        dynasty_minus_rest = _score_delta(dynasty_score, ros_score)
        career_minus_dynasty = _score_delta(career_score, dynasty_score)
        next_minus_market = _score_delta(next_score, market_percentile)
        ros_minus_market = _score_delta(ros_score, market_percentile)
        dynasty_minus_market = _score_delta(dynasty_score, market_percentile)
        career_minus_market = _score_delta(career_score, market_percentile)

        contender_score = _weighted_horizon_score(
            next_score,
            ros_score,
            dynasty_score,
            career_score,
            fit_weights["contender"],
        )
        rebuilder_score = _weighted_horizon_score(
            next_score,
            ros_score,
            dynasty_score,
            career_score,
            fit_weights["rebuilder"],
        )
        spread = (
            round(rebuilder_score - contender_score, 2)
            if rebuilder_score is not None and contender_score is not None
            else None
        )
        clock_scores = {
            "next_game": next_score,
            "rest_of_season": ros_score,
            "dynasty": dynasty_score,
            "career_window": career_score,
        }
        available_clocks = [name for name, value in clock_scores.items() if value is not None]
        unavailable_clocks = [name for name, value in clock_scores.items() if value is None]
        fit_coverage = f"{len(available_clocks)}/4"
        fit_basis = (
            f"fit weight profile={fit_weight_profile}; "
            f"{_fit_weight_text('contender', fit_weights['contender'])}; "
            f"{_fit_weight_text('rebuilder', fit_weights['rebuilder'])}; "
            f"available components={','.join(available_clocks) or 'none'}; "
            f"unavailable components={','.join(unavailable_clocks) or 'none'}; "
            "missing components are omitted and remaining weights are renormalized"
        )
        lane = _value_lane(spread)
        confidence = _confidence(
            projection_confidence,
            dynasty_status,
            injury_status,
            career.get("status", ""),
            availability_status,
        )
        risk_bits = [
            "next-game points use a historical matchup factor only when schedule and defensive evidence are available",
            f"current availability is {availability_note.lower()}",
            "rest-of-season baseline is a production baseline and does not model a recovery timeline",
        ]
        if availability_label != "available":
            risk_bits.append(
                "current availability flag is applied only to the next-game lane; rest-of-season baseline does not model season-long availability"
            )
        if availability_status == "no_current_nfl_team":
            risk_bits.append(
                "historical PPG and long-window market context are conditional on the player signing with an NFL team"
            )
        if not opponent:
            risk_bits.append("opponent-neutral weekly allocation because the next schedule matchup is unavailable")
        if schedule_coverage == "schedule_partial":
            risk_bits.append("schedule source is partial, so matchup and bye evidence are withheld")
        elif opponent and matchup_factor is None:
            risk_bits.append("schedule opponent is known but defensive matchup factor is unavailable")
        elif opponent and matchup_factor is not None and matchup_adjustment_status != "applied":
            risk_bits.append(
                f"historical matchup factor is descriptive only and was not applied ({matchup_validation_status} holdout validation)"
            )
        if dynasty_status.startswith("internal_proxy"):
            risk_bits.append("dynasty score uses an internal proxy because market evidence is unavailable")
        if market_percentile is not None and market_value is not None and market_value > 0:
            if not market_record:
                risk_bits.append("market quality receipt is unavailable because the provider row did not resolve to this player")
            elif market_source_count is not None and market_source_count <= 1:
                risk_bits.append("external market is single-source in the current bundle")
            elif market_source_confidence in {"low", "medium"}:
                risk_bits.append(
                    f"external market confidence is {market_source_confidence}; inspect source count and disagreement before acting"
                )
        if career.get("status") == "unavailable_missing_age":
            risk_bits.append("career window is unavailable because age evidence is missing")
        elif career.get("status") == "unavailable_missing_projection":
            risk_bits.append("career window is unavailable because projection evidence is missing")
        elif career.get("status", "").startswith("internal"):
            risk_bits.append("career window is an internal age-curve projection, not a guaranteed career total")
        if career.get("history_status") == "ambiguous":
            risk_bits.append("historical career anchor was withheld because the normalized source-player join is ambiguous")
        elif career.get("history_status") not in {"matched", "unavailable"} and career_points is not None:
            risk_bits.append("career window has no unique historical production anchor")
        source_trace = _join_trace(
            player.get("source_trace"),
            signal.get("source_trace"),
            market_record.get("source_trace"),
            "player_projection_weekly" if baseline_next is not None else "",
            "roster_players" if roster_row else "",
            "nfl_schedule" if schedule_coverage == "schedule_available" else "",
            "nfl_team_defense_factors" if matchup_factor is not None else "",
            career.get("source_trace", ""),
            career.get("status", "") if career_points is not None else "",
        )
        evidence = (
            f"model_version={HORIZON_MODEL_VERSION}; next_game_week={next_week or 'complete'}; next_game_baseline={_display(baseline_next)}; "
            f"score_basis={HORIZON_SCORE_BASIS}; "
            f"market_value={_display(market_value)}; market_percentile_position={_display(market_percentile)}; "
            f"market_source_count={_display(market_source_count)}; market_disagreement_score={_display(market_disagreement_score)}; "
            f"market_source_confidence={_display(market_source_confidence)}; "
            "market_value_is_the_cross_position_price_anchor; "
            f"next_game_expected={_display(next_expected)}; next_game_score={_display(next_score)}; "
            f"next_game_opponent={opponent or 'unavailable'}; matchup_factor={_display(matchup_factor)}; "
            f"matchup_validation={matchup_validation_status}; matchup_validation_games={_display(matchup_validation_games)}; "
            f"matchup_validation_mae_delta={_display(matchup_validation_mae_delta)}; "
            f"matchup_adjustment={matchup_adjustment_status}; "
            f"rest_of_season_weeks={remaining_weeks}; rest_of_season_points={_display(ros_baseline)}; "
            f"rest_of_season_games={_display(ros_games)}; rest_of_season_byes={_display(ros_byes)}; "
            f"rest_of_season_score={_display(ros_score)}; dynasty_score={_display(dynasty_score)}; "
            f"next_game_minus_market_delta={_display(next_minus_market)}; "
            f"rest_of_season_minus_market_delta={_display(ros_minus_market)}; "
            f"dynasty_minus_market_delta={_display(dynasty_minus_market)}; "
            f"career_minus_market_delta={_display(career_minus_market)}; "
            f"rest_of_season_minus_next_game_delta={_display(rest_minus_next)}; "
            f"dynasty_minus_rest_of_season_delta={_display(dynasty_minus_rest)}; "
            f"career_projection_points={_display(career_points)}; career_projection_score={_display(career_score)}; "
            f"career_minus_dynasty_delta={_display(career_minus_dynasty)}; "
            f"career_history_status={career.get('history_status', 'unavailable')}; "
            f"career_history_join_method={career.get('history_join_method', 'not_matched')}; "
            f"career_history_source_player_id={career.get('history_source_player_id') or 'unavailable'}; "
            f"career_history_seasons={career.get('history_seasons', 0)}; career_history_games={career.get('history_games', 0)}; "
            f"career_history_ppg={_display(career.get('history_ppg'))}; "
            f"contender_fit={_display(contender_score)}; rebuilder_fit={_display(rebuilder_score)}; "
            f"spread={_display(spread)}; fit_coverage={fit_coverage}; fit_weight_profile={fit_weight_profile}; fit_basis={fit_basis}"
        )
        row_league_id = _safe_text(
            roster_row.get("league_id") or scope_league_id or player.get("league_id")
        )
        rows.append(
            {
                "season": season,
                "league_id": row_league_id,
                "as_of_week": as_of_week,
                "horizon_model_version": HORIZON_MODEL_VERSION,
                "horizon_score_basis": HORIZON_SCORE_BASIS,
                "next_game_week": next_week or "",
                "player_id": player_id,
                "player_name": player.get("player_name", ""),
                "position": position,
                "age": age,
                # The selected Sleeper roster is the identity authority. A
                # projection row may be legacy/unscoped or carry a stale team
                # label, so it can only fill gaps after the scoped roster row.
                "roster_id": roster_row.get("roster_id") or player.get("roster_id", signal.get("roster_id", "")),
                "team_name": roster_row.get("team_name") or player.get("team_name", signal.get("team_name", "")),
                "availability_scope": roster_row.get("availability_scope", ""),
                "current_availability_status": availability_status,
                "injury_status": injury_status,
                "injury_body_part": injury_body_part,
                "availability_note": availability_note,
                "projection_ppg": ppg,
                "projection_confidence": projection_confidence,
                "market_value": market_value,
                "market_percentile": market_percentile,
                "market_source_count": market_source_count,
                "market_disagreement_score": market_disagreement_score,
                "market_source_confidence": market_source_confidence,
                "next_game_baseline_points": baseline_next,
                "next_game_expected_points": next_expected,
                "next_game_market_score": next_score,
                "next_game_minus_market_delta": next_minus_market,
                "next_game_status": next_status,
                "next_game_basis": next_basis,
                "next_game_opponent": opponent,
                "next_game_home_away": home_away,
                "next_game_schedule_status": schedule_status,
                "next_game_matchup_factor": matchup_factor,
                "next_game_matchup_validation_status": matchup_validation_status,
                "next_game_matchup_validation_games": matchup_validation_games,
                "next_game_matchup_validation_mae_delta": matchup_validation_mae_delta,
                "next_game_matchup_adjustment_status": matchup_adjustment_status,
                "rest_of_season_weeks": remaining_weeks,
                "rest_of_season_games": ros_games,
                "rest_of_season_bye_weeks": ros_byes,
                "rest_of_season_baseline_points": ros_baseline,
                "rest_of_season_ppg": ros_ppg,
                "rest_of_season_market_score": ros_score,
                "rest_of_season_minus_market_delta": ros_minus_market,
                "rest_of_season_minus_next_game_delta": rest_minus_next,
                "rest_of_season_status": ros_status,
                "rest_of_season_basis": ros_basis,
                "schedule_status": schedule_coverage,
                "dynasty_market_score": dynasty_score,
                "dynasty_minus_market_delta": dynasty_minus_market,
                "dynasty_minus_rest_of_season_delta": dynasty_minus_rest,
                "dynasty_status": dynasty_status,
                "dynasty_basis": dynasty_basis,
                "career_projection_years": career.get("years"),
                "career_projection_points": career_points,
                "career_projection_ppg": career.get("ppg"),
                "career_projection_score": career_score,
                "career_minus_market_delta": career_minus_market,
                "career_minus_dynasty_delta": career_minus_dynasty,
                "career_projection_status": career.get("status", "unavailable_missing_projection"),
                "career_projection_basis": career.get("basis", "No career-window projection is available; zero is not a forecast."),
                "career_history_join_method": career.get("history_join_method", "not_matched"),
                "career_history_source_player_id": career.get("history_source_player_id", ""),
                "career_history_status": career.get("history_status", "unavailable"),
                "career_history_seasons": career.get("history_seasons", 0),
                "career_history_games": career.get("history_games", 0),
                "career_history_ppg": career.get("history_ppg"),
                "career_history_latest_season": career.get("history_latest_season", ""),
                "contender_fit_score": contender_score,
                "rebuilder_fit_score": rebuilder_score,
                "fit_basis": fit_basis,
                "fit_coverage": fit_coverage,
                "rebuilder_contender_spread": spread,
                "value_lane": lane,
                "confidence": confidence,
                "evidence": evidence,
                "risk": "; ".join(risk_bits),
                "source_trace": source_trace,
            }
        )
    return pd.DataFrame(rows, columns=HORIZON_COLUMNS)


def build_available_player_horizon_scores(
    market_df: pd.DataFrame,
    players_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    leagues_df: pd.DataFrame | None,
    config: dict[str, Any] | None = None,
    schedule_df: pd.DataFrame | None = None,
    defense_df: pd.DataFrame | None = None,
    usage_df: pd.DataFrame | None = None,
    raw_stats_df: pd.DataFrame | None = None,
    season_projection_df: pd.DataFrame | None = None,
    weekly_projection_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build four-window rows for market names not rostered in this league.

    This is an availability research board, not a waiver-eligibility feed.  A
    market name must resolve to one canonical Sleeper player and must not be in
    the selected league's current roster before it is scored.  The projection
    is produced by the same deterministic nflverse history model as the
    rostered projection table; missing history stays visibly unavailable.
    """

    config = config or {}
    empty = pd.DataFrame(columns=AVAILABLE_HORIZON_COLUMNS)
    if market_df is None or market_df.empty or players_df is None or players_df.empty:
        return empty

    candidates = _available_market_candidates(market_df, players_df, roster_players_df, config)
    if not candidates:
        return empty

    season = str(config.get("current_season") or _first_value(market_df, "season") or "")
    raw_stats = raw_stats_df if isinstance(raw_stats_df, pd.DataFrame) else pd.DataFrame()
    prepared_stats = _prepared_stats(raw_stats, season) if not raw_stats.empty and season else pd.DataFrame()
    stat_groups = (
        {name: group for name, group in prepared_stats.groupby("normalized_name")}
        if not prepared_stats.empty and "normalized_name" in prepared_stats.columns
        else {}
    )
    scoring = _scoring_settings(leagues_df if isinstance(leagues_df, pd.DataFrame) else pd.DataFrame())

    season_rows: list[dict[str, Any]] = []
    roster_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        player = candidate["player"]
        position = candidate["position"]
        player_stats = stat_groups.get(_normalize_name(candidate["player_name"]), pd.DataFrame())
        if not player_stats.empty and candidate["nfl_team"] and "team" in player_stats.columns:
            team_rows = player_stats[player_stats["team"].astype(str).str.upper() == candidate["nfl_team"]]
            if not team_rows.empty:
                player_stats = team_rows
        projection = _project_player(player_stats, scoring, position)
        season_rows.append(
            {
                "season": season,
                "player_id": candidate["player_id"],
                "player_name": candidate["player_name"],
                "position": position,
                "team": candidate["nfl_team"],
                "roster_id": "",
                "team_name": "Available market",
                **{key: projection.get(key, 0.0) for key in (
                    "projected_games", "projected_fantasy_points", "projected_ppg",
                    "projection_method", "projection_confidence", "source_trace", "projection_note",
                )},
            }
        )
        roster_rows.append(
            {
                "season": season,
                "league_id": _scope_league_id(config),
                "roster_id": "",
                "player_id": candidate["player_id"],
                "player_name": candidate["player_name"],
                "position": position,
                "nfl_team": candidate["nfl_team"],
                "age": candidate["age"],
                "availability_scope": "current_season_snapshot",
                "injury_status": candidate["injury_status"],
                "injury_body_part": candidate["injury_body_part"],
                "roster_status": "available_market",
                "team_name": "Available market",
            }
        )
    # Market percentiles must use the same position cohort for every market
    # row, not only the candidates that happened to survive the selected
    # league's ownership filter.
    market_peers = _market_value_peers(market_df)

    signal_rows = [
        {
            "player_id": candidate["player_id"],
            "market_value": candidate["market_value"],
            "market_percentile": _midrank_percentile(candidate["market_value"], market_peers.get(candidate["position"], [])),
            "position": candidate["position"],
            "age": candidate["age"],
            "source_trace": candidate["market_source_trace"],
        }
        for candidate in candidates
    ]
    candidate_ids = {str(candidate["player_id"]) for candidate in candidates}
    candidate_season = pd.DataFrame(season_rows)
    candidate_weekly = _available_weekly_projection_rows(candidate_season)
    # In production, score candidates inside the same deterministic projection
    # universe used by the rostered horizon table.  Without this, a one-player
    # available pool receives a misleading 50th-percentile clock by default.
    # The fallback remains useful for small unit fixtures that do not provide
    # the projection tables.
    score_season = _append_candidate_projection_rows(season_projection_df, candidate_season, candidate_ids)
    score_weekly = _append_candidate_projection_rows(weekly_projection_df, candidate_weekly, candidate_ids)
    scored = build_player_horizon_market_scores(
        score_season,
        score_weekly,
        pd.DataFrame(signal_rows),
        _append_rows_excluding_ids(roster_players_df, pd.DataFrame(roster_rows), candidate_ids),
        config,
        schedule_df=schedule_df,
        defense_df=defense_df,
        usage_df=usage_df,
        market_consensus_df=market_df,
    )
    metadata = {candidate["player_id"]: candidate for candidate in candidates}
    league_id = _scope_league_id(config)
    output: list[dict[str, Any]] = []
    for _, row in scored.fillna("").iterrows():
        if str(row.get("player_id") or "") not in candidate_ids:
            continue
        candidate = metadata.get(str(row.get("player_id")), {})
        trace = "; ".join(
            value for value in (
                str(row.get("source_trace") or "").replace("roster_players", "").strip("; ").strip(),
                candidate.get("market_source_trace", ""),
                "players",
            )
            if value
        )
        output_row = row.to_dict()
        output_row.update(
            {
                "league_id": league_id,
                "availability_status": "not_rostered_in_selected_league",
                "identity_status": candidate.get("identity_status", "unresolved"),
                "market_rank": candidate.get("market_rank", ""),
                "market_source_count": candidate.get("market_source_count", ""),
                "market_source_confidence": candidate.get("market_source_confidence", ""),
                "source_trace": trace,
                "evidence": (
                    f"{row.get('evidence', '')}; availability=not_rostered_in_selected_league; "
                    f"identity={candidate.get('identity_status', 'unresolved')}; "
                    "this is an available-market research row, not a waiver-eligibility or claim receipt"
                ),
                "risk": (
                    f"{row.get('risk', '')}; current roster absence is inferred from the selected Sleeper roster snapshot; "
                    "confirm waiver/free-agent eligibility and current news before acting"
                ).strip("; ").strip(),
            }
        )
        output.append(output_row)
    if not output:
        return empty
    return pd.DataFrame(output, columns=AVAILABLE_HORIZON_COLUMNS).sort_values(
        ["position", "market_value", "market_rank"],
        ascending=[True, False, True],
        na_position="last",
    ).reset_index(drop=True)


def _available_market_candidates(
    market_df: pd.DataFrame,
    players_df: pd.DataFrame,
    roster_players_df: pd.DataFrame,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve market names and prove they are absent from the selected league."""

    if roster_players_df is None or roster_players_df.empty:
        return []
    season = str(config.get("current_season") or "")
    roster = roster_players_df.copy().fillna("")
    if "season" in roster.columns and season:
        current = roster[roster["season"].astype(str) == season]
        if current.empty:
            return []
        roster = current
    league_id = _scope_league_id(config)
    if league_id and "league_id" in roster.columns:
        identified = roster[roster["league_id"].astype(str).str.strip() != ""]
        if not identified.empty:
            roster = identified[identified["league_id"].astype(str).map(lambda value: _same_identifier(value, league_id))]
            if roster.empty:
                return []
    rostered_ids = {str(value).strip() for value in roster.get("player_id", pd.Series(dtype=str)).tolist() if str(value).strip()}
    if not rostered_ids:
        return []

    metadata: dict[str, dict[str, Any]] = {}
    name_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for _, row in players_df.fillna("").iterrows():
        player_id = _safe_text(row.get("player_id"))
        name = _safe_text(row.get("full_name") or row.get("player_name"))
        position = _safe_text(row.get("position")).upper()
        if not player_id or not name:
            continue
        record = {
            "player_id": player_id,
            "player_name": name,
            "position": position,
            "nfl_team": _safe_text(row.get("team")).upper(),
            "age": _num(row.get("age")),
            "injury_status": _safe_text(row.get("injury_status")),
            "injury_body_part": _safe_text(row.get("injury_body_part")),
        }
        metadata[player_id] = record
        name_index.setdefault((_canonical_market_name(name), position), []).append(record)

    unique: dict[str, dict[str, Any]] = {}
    for _, row in market_df.fillna("").iterrows():
        market_value = _num_or_none(row.get("consensus_value", row.get("market_value")))
        name = _safe_text(row.get("player_name"))
        if market_value is None or market_value <= 0 or not name:
            continue
        position = _safe_text(row.get("position")).upper()
        if position not in _POSITIONS:
            continue
        source_id = _safe_text(row.get("player_id") or row.get("source_player_id"))
        player = metadata.get(source_id) if source_id else None
        identity_status = "sleeper_id" if player is not None else "unresolved"
        if player is None:
            matches = name_index.get((_canonical_market_name(name), position), [])
            if len(matches) == 1:
                player = matches[0]
                identity_status = "sleeper_unique_name_match"
        if player is None:
            # A market row that cannot be joined to Sleeper cannot safely be
            # labeled available, scored, or sent to an article writer.
            continue
        player_id = str(player["player_id"])
        if player_id in rostered_ids:
            continue
        candidate = {
            "player_id": player_id,
            "player_name": str(player.get("player_name") or name),
            "position": position,
            "nfl_team": str(player.get("nfl_team") or "").upper(),
            "age": _num(player.get("age")),
            "injury_status": player.get("injury_status", ""),
            "injury_body_part": player.get("injury_body_part", ""),
            "market_value": round(float(market_value), 2),
            "market_rank": row.get("market_rank", ""),
            "market_source_count": row.get("source_count", 1) or 1,
            "market_source_confidence": _safe_text(row.get("confidence") or row.get("source_confidence")) or "single_source",
            "market_source_trace": _safe_text(row.get("source_trace")) or "market_consensus_values",
            "identity_status": identity_status,
            "player": player,
        }
        prior = unique.get(player_id)
        if prior is None or candidate["market_value"] > prior["market_value"]:
            unique[player_id] = candidate
    return list(unique.values())


def _available_weekly_projection_rows(season_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if season_df is None or season_df.empty:
        return pd.DataFrame()
    for _, row in season_df.iterrows():
        weekly = _num(row.get("projected_fantasy_points")) / 17.0 if _num(row.get("projected_fantasy_points")) > 0 else 0.0
        for week in range(1, 18):
            rows.append(
                {
                    "season": row.get("season", ""),
                    "week": week,
                    "player_id": row.get("player_id", ""),
                    "projected_fantasy_points": round(weekly, 2),
                }
            )
    return pd.DataFrame(rows)


def _append_candidate_projection_rows(
    base_df: pd.DataFrame | None,
    candidate_df: pd.DataFrame,
    candidate_ids: set[str],
) -> pd.DataFrame:
    """Replace candidate IDs in a base universe with the availability rows."""

    base = base_df.copy() if isinstance(base_df, pd.DataFrame) else pd.DataFrame()
    if base.empty:
        return candidate_df.copy()
    base_ids = base["player_id"].astype(str) if "player_id" in base.columns else pd.Series("", index=base.index)
    existing = base[base_ids.isin(candidate_ids)].copy()
    retained = base[~base_ids.isin(candidate_ids)].copy()
    if candidate_df is None or candidate_df.empty:
        return base.reset_index(drop=True)
    identity_fields = {
        "season", "week", "player_id", "player_name", "position", "team",
        "roster_id", "team_name",
    }
    additions: list[dict[str, Any]] = []
    for _, candidate in candidate_df.iterrows():
        merged = candidate.to_dict()
        matches = existing[existing["player_id"].astype(str) == str(candidate.get("player_id"))] if "player_id" in existing.columns else pd.DataFrame()
        if not matches.empty:
            # Reuse the canonical projection values already produced by the
            # refresh, while retaining the candidate's available-market scope.
            for key, value in matches.iloc[0].to_dict().items():
                if key not in identity_fields:
                    merged[key] = value
        additions.append(merged)
    return pd.concat([retained, pd.DataFrame(additions)], ignore_index=True, sort=False)


def _append_rows_excluding_ids(
    base_df: pd.DataFrame | None,
    additions_df: pd.DataFrame,
    excluded_ids: set[str],
) -> pd.DataFrame:
    base = base_df.copy() if isinstance(base_df, pd.DataFrame) else pd.DataFrame()
    if not base.empty and "player_id" in base.columns and excluded_ids:
        base = base[~base["player_id"].astype(str).isin(excluded_ids)]
    if additions_df is None or additions_df.empty:
        return base.reset_index(drop=True)
    if base.empty:
        return additions_df.copy()
    return pd.concat([base, additions_df], ignore_index=True, sort=False)


def _market_value_peers(market_df: pd.DataFrame) -> dict[str, list[float]]:
    peers: dict[str, list[float]] = {}
    if market_df is None or market_df.empty:
        return peers
    for _, row in market_df.fillna("").iterrows():
        position = _safe_text(row.get("position")).upper()
        value = _num_or_none(row.get("consensus_value", row.get("market_value")))
        if position in _POSITIONS and value is not None and value > 0:
            peers.setdefault(position, []).append(float(value))
    return peers


def _canonical_market_name(value: Any) -> str:
    parts = re.sub(r"[^a-z0-9 ]", "", str(value or "").lower()).split()
    while len(parts) > 1 and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v", "vi"}:
        parts.pop()
    return "".join(parts)


def _safe_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _scope_league_id(config: dict[str, Any]) -> str:
    context = config.get("context") if isinstance(config.get("context"), dict) else {}
    return _safe_text(context.get("league_id") or config.get("league_id"))


def _same_identifier(left: Any, right: Any) -> bool:
    return _safe_text(left) == _safe_text(right)


def _next_baseline_points(
    player_id: str,
    position: str,
    ppg: float,
    season_points: float,
    weekly_next: dict[str, dict[str, Any]],
    next_week: int | None,
) -> tuple[float | None, str]:
    if next_week is None:
        return None, "The configured season is complete; no next game is in scope."
    row = weekly_next.get(player_id)
    if row is not None:
        value = _num_or_none(row.get("projected_fantasy_points"))
        if value is not None and value > 0:
            return round(value, 2), "weekly projection row; opponent and bye adjustment unavailable"
    if season_points > 0:
        return round(season_points / 17.0, 2), "season projection divided across 17 weeks; weekly row or opponent adjustment unavailable"
    return None, "No weekly or season projection is available; zero is not a forecast."


def _availability_factor(value: Any, team: Any = "") -> tuple[float, str]:
    """Backward-compatible wrapper around the shared availability contract."""

    return shared_availability_factor({"injury_status": value, "team": team})


def _availability_note(status: Any, body_part: Any, team: Any = "") -> str:
    """Backward-compatible wrapper around the shared availability contract."""

    return shared_availability_note(
        {"injury_status": status, "injury_body_part": body_part, "team": team}
    )


def _dynasty_longevity_score(position: str, age: float) -> float:
    if not age:
        return 50.0
    if position == "RB":
        return 86.0 if age <= 23 else 76.0 if age <= 25 else 61.0 if age <= 27 else 38.0 if age <= 29 else 20.0
    if position in {"WR", "TE"}:
        return 88.0 if age <= 24 else 80.0 if age <= 26 else 68.0 if age <= 28 else 50.0 if age <= 30 else 28.0
    if position == "QB":
        return 86.0 if age <= 25 else 78.0 if age <= 28 else 66.0 if age <= 31 else 48.0 if age <= 34 else 28.0
    return 50.0


def _career_history_map(usage_df: pd.DataFrame | None, current_season: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Build a conservative name/position bridge to historical nflverse output.

    The weekly usage table has nflverse player IDs, while the horizon table is
    keyed by canonical Sleeper IDs.  Until an explicit cross-source ID map is
    available, a unique normalized name plus position is the only permissible
    bridge.  A name that resolves to multiple nflverse IDs is retained as an
    ambiguity receipt and is not used in the projection.
    """

    required = {"season", "week", "player_id", "player_name", "position", "fantasy_points_ppr"}
    if usage_df is None or usage_df.empty or not required.issubset(usage_df.columns):
        return {}
    frame = usage_df.copy().fillna("")
    frame["season_num"] = pd.to_numeric(frame["season"], errors="coerce")
    target_season = _num_or_none(current_season)
    if target_season is not None:
        frame = frame[frame["season_num"] < target_season]
    if frame.empty:
        return {}
    frame["history_name_key"] = frame["player_name"].map(_history_name_key)
    frame["history_position"] = frame["position"].astype(str).str.upper().str.strip()
    frame["history_points"] = pd.to_numeric(frame["fantasy_points_ppr"], errors="coerce").fillna(0.0)
    frame["history_game_key"] = frame.apply(
        lambda row: str(row.get("game_id") or f"{row.get('season_num')}:{row.get('week')}"), axis=1
    )
    frame["history_player_id"] = frame["player_id"].astype(str).str.strip()
    frame = frame[
        frame["history_name_key"].ne("")
        & frame["history_position"].isin(_POSITIONS)
        & frame["season_num"].notna()
        & frame["history_player_id"].ne("")
    ]
    if frame.empty:
        return {}

    season_records: dict[tuple[str, str], list[dict[str, Any]]] = {}
    grouped = frame.groupby(["history_name_key", "history_position", "season_num"], dropna=False, sort=False)
    for (name_key, position, season_num), group in grouped:
        games = int(group["history_game_key"].nunique())
        if games <= 0:
            continue
        points = round(float(group["history_points"].sum()), 2)
        traces = _join_trace(*group.get("source_trace", pd.Series(dtype=str)).tolist())
        key = (str(name_key), str(position))
        season_records.setdefault(key, []).append(
            {
                "season": int(season_num),
                "games": games,
                "ppg": round(points / games, 2),
                "player_ids": sorted({str(value) for value in group["history_player_id"] if str(value)}),
                "source_trace": traces,
            }
        )

    output: dict[tuple[str, str], dict[str, Any]] = {}
    for key, records in season_records.items():
        records = sorted(records, key=lambda row: int(row["season"]))
        latest = records[-1]["season"] if records else ""
        used = records[-5:]
        source_ids = sorted({player_id for row in records for player_id in row["player_ids"]})
        traces = _join_trace(*(row.get("source_trace", "") for row in used))
        if len(source_ids) != 1:
            output[key] = {
                "status": "ambiguous",
                "join_method": "ambiguous_normalized_name_position",
                "source_player_id": "",
                "seasons": len(used),
                "games": sum(int(row["games"]) for row in used),
                "weighted_ppg": None,
                "latest_season": latest,
                "source_trace": traces,
            }
            continue
        weights = [0.75 ** max(0, int(latest) - int(row["season"])) for row in used]
        weight_total = sum(weights) or 1.0
        weighted_ppg = sum(float(row["ppg"]) * weight for row, weight in zip(used, weights)) / weight_total
        output[key] = {
            "status": "matched",
            "join_method": "normalized_name_position_unique_source_id",
            "source_player_id": source_ids[0],
            "seasons": len(used),
            "games": sum(int(row["games"]) for row in used),
            "weighted_ppg": round(weighted_ppg, 2),
            "latest_season": latest,
            "source_trace": traces,
        }
    return output


def _empty_career_history(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "join_method": "not_matched" if status == "not_matched" else "unavailable",
        "source_player_id": "",
        "seasons": 0,
        "games": 0,
        "weighted_ppg": None,
        "latest_season": "",
        "source_trace": "",
    }


def _history_name_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def _career_projection(
    position: str,
    age: float,
    ppg: float,
    projected_games: float,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a bounded five-year production window with explicit assumptions.

    This is intentionally not called a lifetime total.  It is a deterministic
    internal age-curve scenario that lets a rebuilder compare the shape of an
    asset's future production while keeping market value and uncertainty in
    separate columns.
    """

    years = 5
    history = history or _empty_career_history("not_matched")
    history_fields = {
        "history_join_method": history.get("join_method", "not_matched"),
        "history_source_player_id": history.get("source_player_id", ""),
        "history_status": history.get("status", "unavailable"),
        "history_seasons": history.get("seasons", 0),
        "history_games": history.get("games", 0),
        "history_ppg": _num_or_none(history.get("weighted_ppg")),
        "history_latest_season": history.get("latest_season", ""),
        "source_trace": history.get("source_trace", ""),
    }
    if ppg <= 0:
        return {
            "years": years,
            "points": None,
            "ppg": None,
            "status": "unavailable_missing_projection",
            "basis": "No projected PPG is available; zero is not a career-window forecast.",
            **history_fields,
        }
    if not age:
        return {
            "years": years,
            "points": None,
            "ppg": None,
            "status": "unavailable_missing_age",
            "basis": "No age evidence is available for the internal five-year age curve; zero is not a forecast.",
            **history_fields,
        }
    peak_age, decline, floor = {
        "QB": (30, 0.045, 0.55),
        "RB": (25, 0.13, 0.15),
        "WR": (27, 0.07, 0.25),
        "TE": (28, 0.06, 0.30),
    }.get(position, (27, 0.07, 0.25))
    history_ppg = _num_or_none(history.get("weighted_ppg"))
    if history.get("status") == "matched" and history_ppg is not None:
        base_ppg = round((ppg * 0.65) + (history_ppg * 0.35), 2)
        status = "internal_history_age_curve_5yr"
        basis_prefix = (
            f"five-year history-anchored internal age curve for {position or 'unknown position'}; "
            f"current projection {ppg:.2f} PPG blended with recency-weighted nflverse history {history_ppg:.2f} PPG "
            f"across {history.get('games', 0)} games in {history.get('seasons', 0)} observed season(s) "
            f"through {history.get('latest_season') or 'unknown'} via {history.get('join_method')}; "
        )
    else:
        base_ppg = ppg
        status = "internal_age_curve_5yr"
        if history.get("status") == "ambiguous":
            history_note = " Historical nflverse production was withheld because the normalized name/position resolved to multiple source player IDs."
        else:
            history_note = " No unique historical nflverse production match was available; the current projection is used as the base."
        basis_prefix = f"five-year internal age curve for {position or 'unknown position'}; base {ppg:.2f} PPG;{history_note} "
    games = projected_games if projected_games > 0 else 17.0
    games = min(17.0, max(10.0, games))
    year_points: list[float] = []
    for year in range(years):
        future_age = age + year
        if future_age <= peak_age:
            age_factor = max(0.90, 1.0 - ((peak_age - future_age) * 0.02))
        else:
            age_factor = max(floor, 1.0 - ((future_age - peak_age) * decline))
        year_points.append(base_ppg * games * age_factor)
    total = round(sum(year_points), 2)
    total_games = games * years
    return {
        "years": years,
        "points": total,
        "ppg": round(total / total_games, 2) if total_games else None,
        "status": status,
        "basis": (
            f"{basis_prefix}{games:.0f} projected games/year, peak age {peak_age}; "
            "not a lifetime or guaranteed career total"
        ),
        **history_fields,
    }


def _value_lane(spread: float | None) -> str:
    if spread is None:
        return "insufficient_context"
    if spread >= 12:
        return "rebuilder_edge"
    if spread <= -12:
        return "contender_edge"
    return "balanced_window"


def _matchup_adjustment_status(matchup_factor: float | None, validation_status: str) -> str:
    """Only a holdout-improving factor may change next-game points.

    The raw factor remains available as historical context when validation is
    limited or non-improving, but that evidence cannot silently become a
    predictive adjustment at the consumption seam.
    """

    if matchup_factor is None:
        return "unavailable"
    if validation_status == "validated_improvement":
        return "applied"
    return "descriptive_only"


def resolve_horizon_fit_weights(
    strategy_profile: Any = None,
) -> tuple[dict[str, dict[str, float]], str]:
    """Resolve private contender/rebuilder weights without weakening the seam.

    The four component scores remain canonical and position-relative.  A league
    may change how its two strategic lenses prioritize those components, but a
    malformed or partial lane falls back to the documented defaults and is
    named in the row's fit receipt.
    """

    defaults = {
        lane: dict(weights) for lane, weights in DEFAULT_HORIZON_FIT_WEIGHTS.items()
    }
    if not isinstance(strategy_profile, Mapping):
        return defaults, "default"
    configured = strategy_profile.get("horizon_fit_weights")
    if configured in (None, {}):
        return defaults, "default"
    if not isinstance(configured, Mapping):
        return defaults, "invalid_custom_fallback"
    if any(str(key) not in {"contender", "rebuilder"} for key in configured.keys()):
        return defaults, "invalid_custom_fallback"

    resolved = dict(defaults)
    custom_lanes: set[str] = set()
    invalid = False
    for lane in ("contender", "rebuilder"):
        if lane not in configured:
            continue
        normalized = _normalize_horizon_weights(configured.get(lane))
        if normalized is None:
            invalid = True
            continue
        resolved[lane] = normalized
        custom_lanes.add(lane)

    if invalid:
        return resolved, "invalid_custom_fallback"
    if not custom_lanes:
        return defaults, "default"
    return resolved, "custom" if len(custom_lanes) == 2 else "mixed_custom_default"


def _normalize_horizon_weights(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    if set(value.keys()) != set(HORIZON_FIT_WEIGHT_KEYS):
        return None
    parsed: dict[str, float] = {}
    for key in HORIZON_FIT_WEIGHT_KEYS:
        raw = value.get(key)
        if isinstance(raw, bool):
            return None
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0:
            return None
        parsed[key] = number
    total = sum(parsed.values())
    if total <= 0:
        return None
    return {key: round(parsed[key] / total, 8) for key in HORIZON_FIT_WEIGHT_KEYS}


def _weighted_horizon_score(
    next_score: float | None,
    rest_of_season_score: float | None,
    dynasty_score: float | None,
    career_score: float | None,
    weights: Mapping[str, float],
) -> float | None:
    return _weighted_score(
        (
            (next_score, float(weights["next_game"])),
            (rest_of_season_score, float(weights["rest_of_season"])),
            (dynasty_score, float(weights["dynasty"])),
            (career_score, float(weights["career_window"])),
        )
    )


def _fit_weight_text(lane: str, weights: Mapping[str, float]) -> str:
    def percent(key: str) -> str:
        value = f"{float(weights[key]) * 100:.1f}".rstrip("0").rstrip(".")
        return f"{value}%"

    return (
        f"{lane} fit weights next game {percent('next_game')}, "
        f"rest of season {percent('rest_of_season')}, "
        f"dynasty market {percent('dynasty')}, "
        f"five-year career window {percent('career_window')}"
    )


def _weighted_score(values: tuple[tuple[float | None, float], ...]) -> float | None:
    usable = [(value, weight) for value, weight in values if value is not None]
    if not usable:
        return None
    total = sum(weight for _, weight in usable)
    return round(sum(value * weight for value, weight in usable) / total, 2)


def _score_delta(later: float | None, earlier: float | None) -> float | None:
    """Return a later-clock minus earlier-clock delta without inventing zero."""

    if later is None or earlier is None:
        return None
    return round(float(later) - float(earlier), 2)


def _confidence(
    projection_confidence: str,
    dynasty_status: str,
    injury_status: str,
    career_status: str = "",
    availability_status: str = "",
) -> str:
    if availability_status == "no_current_nfl_team":
        return "low"
    if projection_confidence == "low" or dynasty_status.startswith("unavailable") or career_status.startswith("unavailable"):
        return "low"
    availability_limited = _availability_factor(injury_status)[1] != "available"
    if dynasty_status.startswith("internal_proxy") or career_status.startswith("internal") or availability_limited:
        return "medium"
    return "high" if projection_confidence == "high" else "medium"


def _schedule_frame(schedule_df: pd.DataFrame | None, season: str) -> pd.DataFrame:
    if schedule_df is None or schedule_df.empty:
        return pd.DataFrame()
    required = {"season", "week", "away_team", "home_team"}
    if not required.issubset(schedule_df.columns):
        return pd.DataFrame()
    frame = schedule_df.copy().fillna("")
    frame = frame[frame["season"].astype(str) == str(season)]
    if "game_type" in frame.columns:
        frame = frame[frame["game_type"].astype(str).str.upper().isin({"", "REG"})]
    frame["week_num"] = pd.to_numeric(frame["week"], errors="coerce")
    frame["away_team"] = frame["away_team"].astype(str).str.upper().str.strip()
    frame["home_team"] = frame["home_team"].astype(str).str.upper().str.strip()
    return frame[frame["week_num"].notna() & frame["away_team"].ne("") & frame["home_team"].ne("")]


def _schedule_team_context(
    schedule_df: pd.DataFrame,
    team: str,
    next_week: int | None,
    as_of_week: int,
) -> dict[str, Any]:
    unavailable = {
        "coverage": "schedule_unavailable",
        "next_status": "schedule_unavailable",
        "opponent": "",
        "home_away": "",
        "rest_games": None,
        "bye_weeks": None,
    }
    if schedule_df is None or schedule_df.empty:
        return unavailable
    coverage = _schedule_coverage_status(schedule_df)
    if coverage != "schedule_available":
        return unavailable | {"coverage": coverage, "next_status": coverage}
    known_teams = set(schedule_df["away_team"]) | set(schedule_df["home_team"])
    team = str(team or "").upper().strip()
    if not team or team not in known_teams:
        return unavailable | {"coverage": "schedule_team_unmatched", "next_status": "schedule_team_unmatched"}

    team_games = schedule_df[
        schedule_df["away_team"].eq(team) | schedule_df["home_team"].eq(team)
    ].drop_duplicates(subset=["week_num"])
    remaining_weeks = max(0, 17 - as_of_week)
    future_games = team_games[(team_games["week_num"] > as_of_week) & (team_games["week_num"] <= 17)]
    rest_games = int(future_games["week_num"].nunique())
    context = {
        "coverage": "schedule_available",
        "next_status": "season_complete" if next_week is None else "bye",
        "opponent": "",
        "home_away": "",
        "rest_games": rest_games,
        "bye_weeks": max(0, remaining_weeks - rest_games),
    }
    if next_week is None:
        return context
    next_rows = team_games[team_games["week_num"].eq(next_week)]
    if next_rows.empty:
        return context
    game = next_rows.iloc[0]
    is_home = str(game.get("home_team")) == team
    return context | {
        "next_status": "scheduled_game",
        "opponent": str(game.get("away_team" if is_home else "home_team") or ""),
        "home_away": "home" if is_home else "away",
    }


def _schedule_coverage_status(schedule_df: pd.DataFrame) -> str:
    """Return a trustworthy NFL regular-season coverage state.

    A missing future row is only a bye when the complete 32-team schedule is
    present.  The source normally contains 272 regular-season games; the
    looser row/team thresholds tolerate a small source correction while still
    rejecting a partial extract that could turn missing data into fake byes.
    """

    if schedule_df is None or schedule_df.empty:
        return "schedule_unavailable"
    known_teams = set(schedule_df["away_team"]) | set(schedule_df["home_team"])
    counts = pd.concat(
        [schedule_df["away_team"].value_counts(), schedule_df["home_team"].value_counts()],
        axis=1,
    ).fillna(0).sum(axis=1)
    if len(known_teams) < 32 or len(schedule_df) < 260 or counts.min() < 16:
        return "schedule_partial"
    return "schedule_available"


def _defense_map(frame: pd.DataFrame | None) -> dict[tuple[str, str], dict[str, Any]]:
    if frame is None or frame.empty or not {"team", "position"}.issubset(frame.columns):
        return {}
    return {
        (str(row.get("team") or "").upper().strip(), str(row.get("position") or "").upper().strip()): row.to_dict()
        for _, row in frame.fillna("").iterrows()
    }


def _next_week_map(weekly_df: pd.DataFrame, next_week: int | None) -> dict[str, dict[str, Any]]:
    if next_week is None or weekly_df.empty or "player_id" not in weekly_df.columns:
        return {}
    frame = weekly_df[pd.to_numeric(weekly_df.get("week"), errors="coerce") == next_week]
    return {str(row.get("player_id")): row.to_dict() for _, row in frame.iterrows()}


def _ros_values(season_df: pd.DataFrame, as_of_week: int) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    remaining = max(0, 17 - as_of_week)
    if season_df.empty:
        return values
    for _, row in season_df.iterrows():
        total = _num(row.get("projected_fantasy_points"))
        if total <= 0:
            continue
        values.setdefault(str(row.get("position") or ""), []).append((total / 17.0) * remaining)
    return values


def _positive_values(frame: pd.DataFrame, value_column: str, group_column: str) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    if frame is None or frame.empty or value_column not in frame.columns:
        return values
    for _, row in frame.iterrows():
        value = _num(row.get(value_column))
        if value > 0:
            values.setdefault(str(row.get(group_column) or ""), []).append(value)
    return values


def _midrank_percentile(value: float, peers: list[float]) -> float:
    if value <= 0 or not peers:
        return 0.0
    less = sum(peer < value for peer in peers)
    equal = sum(peer == value for peer in peers)
    return round(((less + (equal * 0.5)) / len(peers)) * 100.0, 2)


def _row_map(frame: pd.DataFrame | None, key: str) -> dict[str, dict[str, Any]]:
    if frame is None or frame.empty or key not in frame.columns:
        return {}
    return {str(row.get(key)): row.to_dict() for _, row in frame.fillna("").iterrows() if str(row.get(key) or "")}


def _market_consensus_name_map(frame: pd.DataFrame | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Index provider market rows for a conservative no-ID name bridge.

    The bridge is intentionally a list: duplicate provider rows or duplicate
    player names stay ambiguous instead of silently attaching one receipt to
    the wrong Sleeper player.
    """

    output: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if frame is None or frame.empty:
        return output
    for _, row in frame.fillna("").iterrows():
        name = _canonical_market_name(row.get("player_name"))
        position = _safe_text(row.get("position")).upper()
        if name and position:
            output.setdefault((name, position), []).append(row.to_dict())
    return output


def _roster_map(
    frame: pd.DataFrame | None,
    season: str,
    league_id: str = "",
) -> dict[str, dict[str, Any]]:
    if frame is None or frame.empty:
        return {}
    current = frame
    if "season" in current.columns:
        scoped = current[current["season"].astype(str) == season]
        if not scoped.empty:
            current = scoped
    if league_id and "league_id" in current.columns:
        identified = current[current["league_id"].map(_safe_text) != ""]
        if not identified.empty:
            current = identified[
                identified["league_id"].map(lambda value: _same_identifier(value, league_id))
            ]
    return _row_map(current, "player_id")


def _first_value(frame: pd.DataFrame, key: str) -> str:
    if key not in frame.columns or frame.empty:
        return ""
    return str(frame.iloc[0].get(key) or "")


def _clamp_week(value: Any) -> int:
    try:
        return max(0, min(17, int(float(value))))
    except (TypeError, ValueError):
        return 0


def _join_trace(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        for part in str(value or "").split(";"):
            part = part.strip()
            if part and part not in parts:
                parts.append(part)
    return "; ".join(parts)


def _num(value: Any) -> float:
    try:
        if value in (None, "") or pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _num_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _display(value: Any) -> str:
    return "n/a" if value in (None, "") else str(value)
