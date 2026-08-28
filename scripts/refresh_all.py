from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import build_analysis_artifacts
from src.browser_site import build_browser_site
from src.context import FantasyContext, context_from_league_row, scoped_config
from src.economics import build_economic_tables
from src.external_sources import refresh_external_sources
from src.league_paths import LeaguePaths
from src.league_registry import discover_leagues, save_registry
from src.manager_profiles import build_manager_profiles
from src.news import build_news_tables
from src.normalize import (
    build_roster_maps,
    normalize_draft_picks,
    normalize_drafts,
    normalize_league,
    normalize_roster_players,
    normalize_teams,
    normalize_traded_picks,
    normalize_transactions,
    normalize_transactions_raw,
    normalize_trades,
    normalize_waivers,
    normalize_matchups,
    normalize_matchup_player_points,
    to_dataframes,
)
from src.pick_ownership import build_pick_ownership
from src.players import load_players, players_table
from src.priority_board import build_today_priority_board
from src.profile_intelligence import build_profile_intelligence_tables
from src.horizon_accuracy import (
    append_horizon_snapshot,
    build_horizon_accuracy_table,
    build_horizon_movement_table,
)
from src.projection_accuracy import append_projection_accuracy_snapshot, build_projection_accuracy_table
from src.opportunity import build_opportunity_scores
from src.projections import _load_raw_stats, build_projection_tables
from src.horizons import build_available_player_horizon_scores, build_player_horizon_market_scores
from src.matchups import build_team_defense_factors
from src.reports import build_weekly_report
from src.sleeper_api import SleeperAPI, SleeperAPIError
from src.signals import (
    build_signal_tables,
    build_counterparty_asset_interest,
    enrich_counterparty_trade_edges_with_horizons,
)
from src.team_identity import resolve_team_name
from src.utils import ANALYSIS_DIR, PROCESSED_DIR, RAW_EXTERNAL_DIR, REPORTS_DIR, SITE_DIR, ensure_dirs, load_config


REFRESH_MODES = {"bootstrap", "maintenance"}

# Maintenance refreshes intentionally replace only these canonical source tables.
# Derived tables are rebuilt from the merged canonical set below, so a narrower
# current-season refresh never erases the historical evidence assembled by setup.
CANONICAL_TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "leagues": ("season", "league_id"),
    "teams": ("season", "league_id", "roster_id"),
    "players": ("player_id",),
    "roster_players": ("season", "league_id", "roster_id", "player_id"),
    "drafts": ("season", "league_id", "draft_id"),
    "draft_picks": ("season", "league_id", "draft_id", "pick_no"),
    "traded_picks": ("season", "league_id", "original_roster_id", "pick_season", "round"),
    "transactions_raw": ("season", "league_id", "week", "transaction_id"),
    "transactions_normalized": ("season", "league_id", "week", "transaction_id"),
    "trades": ("season", "league_id", "week", "transaction_id"),
    "waivers": ("season", "league_id", "week", "transaction_id"),
    "matchups": ("season", "league_id", "week", "roster_id"),
    "matchup_player_points": ("season", "league_id", "week", "matchup_id", "roster_id", "player_id"),
}


def normalize_refresh_mode(run_mode: str | None = None) -> str:
    """Return a fail-closed refresh lifecycle mode.

    ``bootstrap`` is the explicit historical setup path. ``maintenance`` is
    the recurring current-state path. An environment override is useful for
    Railway scheduled jobs, but an invalid value must not silently choose a
    destructive or surprising behavior.
    """

    value = str(run_mode or os.environ.get("FRONT_OFFICE_REFRESH_MODE", "bootstrap")).strip().lower()
    if value not in REFRESH_MODES:
        raise ValueError(f"refresh mode must be one of {sorted(REFRESH_MODES)}, got {value!r}")
    return value


def refresh_mode_for_paths(paths: "LeaguePaths", requested: str | None = None) -> str:
    """Choose setup for an empty edition and maintenance for an existing one."""

    if requested is not None:
        return normalize_refresh_mode(requested)
    configured = os.environ.get("FRONT_OFFICE_REFRESH_MODE", "").strip()
    if configured:
        return normalize_refresh_mode(configured)
    return "maintenance" if (paths.processed_dir / "teams.csv").is_file() else "bootstrap"


def _maintenance_week_end(config: dict, league: dict) -> int:
    """Choose the latest week maintenance should request without guessing facts."""

    configured_end = int(config.get("transaction_weeks", {}).get("end", 18))
    override = os.environ.get("FRONT_OFFICE_MAINTENANCE_WEEK_END", "").strip()
    if override:
        try:
            return max(0, min(configured_end, int(override)))
        except ValueError:
            pass
    configured = config.get("maintenance_week_end")
    if configured not in (None, ""):
        try:
            return max(0, min(configured_end, int(configured)))
        except (TypeError, ValueError):
            pass
    settings = league.get("settings") if isinstance(league, dict) else {}
    sleeper_leg = settings.get("leg") if isinstance(settings, dict) else None
    try:
        if sleeper_leg not in (None, "") and int(sleeper_leg) > 0:
            return max(0, min(configured_end, int(sleeper_leg)))
    except (TypeError, ValueError):
        pass
    # If Sleeper did not provide an observable leg, fail closed rather than
    # requesting every future week and turning placeholder rows into evidence.
    return 0


def _merge_maintenance_canonical_tables(
    all_tables: dict[str, list[dict]],
    processed_dir: Path,
) -> dict[str, list[dict]]:
    """Merge a current maintenance slice into the last canonical snapshot.

    The fresh row wins on an exact source key. This keeps renamed teams and
    changed roster state current while preserving prior seasons/weeks that a
    maintenance run deliberately did not request.
    """

    merged = dict(all_tables)
    for table, keys in CANONICAL_TABLE_KEYS.items():
        path = processed_dir / f"{table}.csv"
        if not path.is_file():
            continue
        try:
            previous = pd.read_csv(path, dtype=object).fillna("")
        except (OSError, pd.errors.ParserError):
            continue
        fresh = pd.DataFrame(merged.get(table, []))
        if previous.empty and fresh.empty:
            merged[table] = []
            continue
        combined = pd.concat([previous, fresh], ignore_index=True, sort=False).fillna("")
        available_keys = [key for key in keys if key in combined.columns]
        if len(available_keys) == len(keys):
            # CSV snapshots commonly read numeric IDs as strings while fresh
            # API rows carry them as ints. Normalize only the dedupe keys so
            # an exact source row is replaced across refresh boundaries.
            dedupe_columns: list[str] = []
            for key in keys:
                marker = f"__maintenance_key_{key}"
                combined[marker] = combined[key].map(lambda value: str(value).strip())
                dedupe_columns.append(marker)
            combined = combined.drop_duplicates(subset=dedupe_columns, keep="last")
            combined = combined.drop(columns=dedupe_columns)
        merged[table] = combined.to_dict(orient="records")
    return merged


def main(
    force: bool = False,
    league_id: str | None = None,
    roster_id: int | None = None,
    paths: "LeaguePaths | None" = None,
    league_type: str = "dynasty",
    context: FantasyContext | None = None,
    run_mode: str | None = None,
) -> None:
    run_mode = normalize_refresh_mode(run_mode)
    if paths is None and context is not None and context.user_id is not None:
        paths = LeaguePaths.for_user_league(context.user_id, context.league_id)
    if paths is None:
        ensure_dirs()
        raw_dir = None
        processed_dir = PROCESSED_DIR
        reports_dir = REPORTS_DIR
        site_dir = SITE_DIR
        analysis_dir = ANALYSIS_DIR
    else:
        paths.ensure()
        raw_dir = paths.raw_dir
        processed_dir = paths.processed_dir
        reports_dir = paths.reports_dir
        site_dir = paths.site_dir
        analysis_dir = paths.analysis_dir

    config = scoped_config(load_config(), context) if context is not None else load_config()
    api = (
        SleeperAPI(raw_dir=raw_dir, current_season=str(config.get("current_season", "")))
        if raw_dir is not None
        else SleeperAPI(current_season=str(config.get("current_season", "")))
    )
    players = load_players(api, force=force)
    current_team = config.get("current_team", {}) or {}
    my_display_name = current_team.get("display_name") or config.get("my_display_name", "")
    my_team_name = current_team.get("team_name") or config.get("my_team_name", "")
    configured_roster_id = roster_id if roster_id is not None else current_team.get("roster_id")
    configured_roster_id = int(configured_roster_id) if configured_roster_id not in (None, "") else None
    week_start = int(config.get("transaction_weeks", {}).get("start", 1))
    week_end = int(config.get("transaction_weeks", {}).get("end", 18))
    current_season = str(config.get("current_season", "") or "")
    requested_league_id = str(league_id or "")
    if league_id and run_mode == "bootstrap":
        league_ids_by_season = _discover_league_history_from_seed(config, api, requested_league_id, force=force)
    elif league_id:
        league_ids_by_season = {current_season: requested_league_id} if current_season else {"": requested_league_id}
    elif run_mode == "maintenance":
        configured_current_league = (config.get("leagues") or {}).get(current_season, "")
        league_ids_by_season = {current_season: str(configured_current_league)} if configured_current_league else {}
    else:
        league_ids_by_season = _discover_league_history(config, api, force=force)
    current_scope_league_id = str(
        context.league_id
        if context
        else league_ids_by_season.get(current_season) or requested_league_id or ""
    )
    # Derived tables may outlive the in-memory request context. Keep the
    # selected league boundary explicit for every downstream horizon builder.
    config["league_id"] = current_scope_league_id

    external_frames = refresh_external_sources(config, force=force)

    all_tables: dict[str, list[dict]] = {
        "leagues": [],
        "teams": [],
        "players": players_table(players),
        "roster_players": [],
        "drafts": [],
        "draft_picks": [],
        "traded_picks": [],
        "transactions_raw": [],
        "transactions_normalized": [],
        "trades": [],
        "waivers": [],
        "matchups": [],
        "matchup_player_points": [],
    }
    current_my_roster_id = None
    matchup_source_statuses: list[str] = []
    requested_week_ends: list[int] = []
    requested_week_ends_by_season: dict[str, int] = {}

    for season, league_id in league_ids_by_season.items():
        if not league_id:
            continue
        season = str(season)
        league_id = str(league_id)
        print(f"Refreshing season {season}, league {league_id}")

        league = api.league(season, league_id, force=force)
        users = api.users(season, league_id, force=force)
        rosters = api.rosters(season, league_id, force=force)
        traded_picks = api.traded_picks(season, league_id, force=force)
        drafts = api.drafts(season, league_id, force=force)
        draft_picks_by_draft = {
            draft.get("draft_id"): api.draft_picks(season, draft.get("draft_id"), force=force)
            for draft in drafts
            if draft.get("draft_id")
        }
        # Historical seasons use the configured full week range. The current
        # season is bounded by Sleeper's observable leg in both modes so a
        # bootstrap cannot manufacture future 0-0 ties.
        requested_week_end = _maintenance_week_end(config, league) if season == current_season else week_end
        requested_week_ends.append(requested_week_end)
        requested_week_ends_by_season[season] = requested_week_end
        requested_weeks = range(week_start, requested_week_end + 1)
        transactions_by_week = {
            week: api.transactions(season, league_id, week, force=force)
            for week in requested_weeks
        }
        matchups_by_week: dict[int, list[dict]] = {}
        matchups_available = True
        for week in requested_weeks:
            try:
                matchups_by_week[week] = api.matchups(season, league_id, week, force=force)
            except SleeperAPIError:
                # Matchups are a depth source, not a reason to discard a
                # trustworthy transaction/roster refresh. The dossier will
                # render outcomes as not recorded when this endpoint is absent.
                matchups_by_week[week] = []
                matchups_available = False
        matchup_source_statuses.append("available" if matchups_available else "unavailable")

        roster_map, my_roster_id = build_roster_maps(
            rosters,
            users,
            my_display_name,
            my_team_name,
            configured_roster_id,
        )
        if str(season) == str(config.get("current_season")):
            current_my_roster_id = my_roster_id

        all_tables["leagues"].extend(normalize_league(season, league))
        all_tables["teams"].extend(normalize_teams(season, league_id, users, rosters))
        all_tables["roster_players"].extend(
            normalize_roster_players(
                season,
                league_id,
                rosters,
                roster_map,
                my_roster_id,
                players,
                current_season=current_season,
            )
        )
        all_tables["drafts"].extend(normalize_drafts(season, league_id, drafts))
        all_tables["draft_picks"].extend(normalize_draft_picks(season, league_id, draft_picks_by_draft, players))
        all_tables["traded_picks"].extend(
            normalize_traded_picks(season, league_id, traded_picks, roster_map, my_roster_id)
        )
        all_tables["transactions_raw"].extend(normalize_transactions_raw(season, league_id, transactions_by_week))
        all_tables["transactions_normalized"].extend(
            normalize_transactions(season, league_id, transactions_by_week, roster_map, players)
        )
        all_tables["trades"].extend(normalize_trades(season, league_id, transactions_by_week, roster_map, players))
        all_tables["waivers"].extend(normalize_waivers(season, league_id, transactions_by_week, roster_map, players))
        all_tables["matchups"].extend(normalize_matchups(season, league_id, matchups_by_week, roster_map))
        all_tables["matchup_player_points"].extend(
            normalize_matchup_player_points(season, league_id, matchups_by_week, roster_map, players)
        )

    if run_mode == "maintenance":
        all_tables = _merge_maintenance_canonical_tables(all_tables, processed_dir)

    # Sleeper's current team label is source data, not a durable profile alias.
    # Resolve a stale historical name before any analysis artifact or browser
    # bundle is written, while preserving a genuinely custom Front Office label.
    resolved_team_name = resolve_team_name(
        my_team_name,
        all_tables["teams"],
        league_id=current_scope_league_id,
        season=current_season,
        roster_id=current_my_roster_id or configured_roster_id,
    )
    if resolved_team_name:
        my_team_name = resolved_team_name
        current_team = dict(config.get("current_team") or {})
        current_team["team_name"] = resolved_team_name
        if current_my_roster_id is not None:
            current_team["roster_id"] = current_my_roster_id
        config["current_team"] = current_team

    dataframes = to_dataframes(all_tables)
    manager_profiles = build_manager_profiles(
        dataframes["teams"],
        dataframes["trades"],
        dataframes["waivers"],
        dataframes["roster_players"],
    )
    pick_ownership = build_pick_ownership(
        dataframes["traded_picks"],
        dataframes["teams"],
        current_my_roster_id,
        league_id=current_scope_league_id,
        season=current_season,
    )
    dataframes["manager_profiles"] = manager_profiles
    dataframes["pick_ownership"] = pick_ownership
    dataframes.update(external_frames)
    dataframes.update(build_news_tables(config, api, players, dataframes["teams"], dataframes["roster_players"], force=force))

    nflverse_stats_path = RAW_EXTERNAL_DIR / "nflverse" / str(config.get("current_season", "")) / "player_stats.csv"
    raw_stats_for_grading = _load_raw_stats(nflverse_stats_path)
    accuracy_history_path = processed_dir / "projection_snapshot_history.csv"
    accuracy_df = build_projection_accuracy_table(raw_stats_for_grading, dataframes["leagues"], config, accuracy_history_path)
    dataframes["source_accuracy_scores"] = accuracy_df

    dataframes.update(
        build_projection_tables(
            config,
            dataframes["leagues"],
            dataframes["roster_players"],
            dataframes.get("fantasy_nerds_projection_source", pd.DataFrame()),
            accuracy_df,
        )
    )
    dataframes["nfl_team_defense_factors"] = build_team_defense_factors(
        dataframes.get("player_usage_weekly", pd.DataFrame()),
        config,
    )
    # The current Sleeper leg is the only defensible local clock for horizon
    # analysis.  Keep it in the in-memory config so every derived horizon row
    # carries the same as-of boundary as refresh_metadata.
    config["current_week"] = requested_week_ends_by_season.get(current_season, 0)
    # Append-only projection history log (Sprint 10 pattern) -- deliberately not part
    # of the overwrite-every-refresh export loop below.
    append_projection_accuracy_snapshot(accuracy_history_path, dataframes["projection_source_components"], config)

    # Opportunity-based scores (Sprint 18) from nflverse weekly usage -- the verified forward-looking
    # signal the projection average was missing. Computed after projections, before signals consume it.
    dataframes["player_opportunity_scores"] = build_opportunity_scores(
        raw_stats_for_grading, dataframes["roster_players"], config
    )

    dataframes.update(
        build_economic_tables(
            dataframes["teams"],
            dataframes["roster_players"],
            dataframes["pick_ownership"],
            dataframes["trades"],
            dataframes["waivers"],
            manager_profiles,
            dataframes["player_market_values"],
            dataframes["pick_market_values"],
            config,
            dataframes.get("matchups", pd.DataFrame()),
        )
    )
    dataframes.update(
        build_signal_tables(
            dataframes["player_projection_season"],
            dataframes["roster_players"],
            dataframes["player_market_values"],
            dataframes["team_needs_matrix"],
            dataframes["manager_behavior_signals"],
            dataframes["league_news_impact"],
            config,
            dataframes["manager_valuation_profiles"],
            dataframes["player_opportunity_scores"],
            dataframes["team_asset_inventory"],
        )
    )
    dataframes["player_horizon_market_scores"] = build_player_horizon_market_scores(
        dataframes["player_projection_season"],
        dataframes["player_projection_weekly"],
        dataframes["player_signal_scores"],
        dataframes["roster_players"],
        config,
        schedule_df=dataframes.get("nfl_schedule", pd.DataFrame()),
        defense_df=dataframes.get("nfl_team_defense_factors", pd.DataFrame()),
        usage_df=dataframes.get("player_usage_weekly", pd.DataFrame()),
        market_consensus_df=dataframes.get("market_consensus_values", pd.DataFrame()),
    )
    dataframes["available_player_horizon_scores"] = build_available_player_horizon_scores(
        dataframes.get("market_consensus_values", pd.DataFrame()),
        dataframes.get("players", pd.DataFrame()),
        dataframes.get("roster_players", pd.DataFrame()),
        dataframes.get("leagues", pd.DataFrame()),
        config,
        schedule_df=dataframes.get("nfl_schedule", pd.DataFrame()),
        defense_df=dataframes.get("nfl_team_defense_factors", pd.DataFrame()),
        usage_df=dataframes.get("player_usage_weekly", pd.DataFrame()),
        raw_stats_df=raw_stats_for_grading,
        season_projection_df=dataframes.get("player_projection_season", pd.DataFrame()),
        weekly_projection_df=dataframes.get("player_projection_weekly", pd.DataFrame()),
    )
    horizon_history_path = processed_dir / "horizon_snapshot_history.csv"
    horizon_snapshot_receipt = append_horizon_snapshot(
        horizon_history_path,
        dataframes["player_horizon_market_scores"],
        config,
    )
    # The current refresh can only grade snapshots for which later realized
    # nflverse usage exists.  An empty table is an honest cold start, not a
    # reason to manufacture a forecast-quality number.
    dataframes["horizon_score_accuracy"] = build_horizon_accuracy_table(
        horizon_history_path,
        dataframes.get("player_usage_weekly", pd.DataFrame()),
        config,
    )
    dataframes["horizon_market_movements"] = build_horizon_movement_table(
        horizon_history_path,
        dataframes["player_horizon_market_scores"],
        config,
    )
    dataframes["today_priority_board"] = build_today_priority_board(
        dataframes["action_recommendations"],
        dataframes["league_news_impact"],
        dataframes["pick_ownership"],
        dataframes["manager_behavior_signals"],
        config,
    )
    dataframes.update(
        build_profile_intelligence_tables(
            dataframes["manager_profiles"],
            dataframes["manager_event_log"],
            dataframes["manager_valuation_profiles"],
            dataframes["team_needs_matrix"],
            dataframes["pick_ownership"],
            dataframes["roster_players"],
            dataframes["trades"],
            dataframes["waivers"],
            dataframes["draft_picks"],
            dataframes["market_consensus_values"],
            dataframes["player_projection_season"],
            dataframes["player_projection_weekly"],
            dataframes["league_news_impact"],
            dataframes["player_signal_scores"],
            config,
            dataframes["team_asset_inventory"],
            dataframes["players"],
            dataframes["player_horizon_market_scores"],
        )
    )
    dataframes["counterparty_trade_edges"] = enrich_counterparty_trade_edges_with_horizons(
        dataframes.get("counterparty_trade_edges", pd.DataFrame()),
        dataframes["player_horizon_market_scores"],
        dataframes["team_needs_matrix"],
        config,
    )
    dataframes["counterparty_asset_interest"] = build_counterparty_asset_interest(
        dataframes.get("team_asset_inventory", pd.DataFrame()),
        dataframes.get("manager_transaction_preferences", pd.DataFrame()),
        dataframes.get("team_needs_matrix", pd.DataFrame()),
        dataframes.get("player_horizon_market_scores", pd.DataFrame()),
        config,
    )
    configured_seasons = [str(season) for season, league_id in league_ids_by_season.items() if league_id]
    ingested_seasons = sorted({str(value) for value in dataframes["leagues"].get("season", pd.Series(dtype=str)).dropna().tolist()})
    analysis_metadata = build_analysis_artifacts(analysis_dir, dataframes, config, current_my_roster_id)
    dataframes["refresh_metadata"] = pd.DataFrame(
        [
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "refresh_mode": run_mode,
                "current_season": config.get("current_season", ""),
                "configured_league_ids": ";".join(
                    str(value) for value in league_ids_by_season.values() if value
                ),
                "configured_seasons": ";".join(configured_seasons),
                "ingested_seasons": ";".join(ingested_seasons),
                "historical_league_ids_configured": max(0, len(configured_seasons) - 1),
                "transaction_week_start": week_start,
                "transaction_week_end": week_end,
                "requested_week_end": requested_week_ends_by_season.get(
                    current_season,
                    max(requested_week_ends) if requested_week_ends else week_end,
                ),
                "current_week": config.get("current_week", 0),
                "historical_refresh_scope": "all_discovered_seasons" if run_mode == "bootstrap" else "preserved_from_prior_snapshot",
                "matchups_status": ";".join(matchup_source_statuses) or "not_requested",
                "matchup_rows": len(dataframes.get("matchups", pd.DataFrame())),
                "matchup_player_points_rows": len(dataframes.get("matchup_player_points", pd.DataFrame())),
                "source_scope": "Sleeper public API plus open/legal external sources",
                "raw_cache_root": str((raw_dir or Path("data") / "raw").as_posix()),
                "raw_external_cache_root": str((Path("data") / "raw_external").as_posix()),
                "user_id": context.user_id if context else "",
                "league_id": current_scope_league_id,
                "team_scope_key": context.scope_key if context else "legacy",
                "browser_is_primary_surface": True,
                "recommendation_packets_status": "planned_contract_only",
                "analysis_artifacts_status": analysis_metadata.get("status", "unknown"),
                "analysis_generated_at": analysis_metadata.get("generated_at", ""),
                "analysis_context_packet_count": analysis_metadata.get("context_packet_count", 0),
                "target_thesis_count": analysis_metadata.get("target_thesis_count", 0),
                "sell_thesis_count": analysis_metadata.get("sell_thesis_count", 0),
                "trade_thesis_count": analysis_metadata.get("trade_thesis_count", 0),
                "market_source_rows": len(dataframes.get("market_value_sources", pd.DataFrame())),
                "market_consensus_rows": len(dataframes.get("market_consensus_values", pd.DataFrame())),
                "projection_source_rows": len(dataframes.get("projection_source_components", pd.DataFrame())),
                "projection_accuracy_rows": len(dataframes.get("source_accuracy_scores", pd.DataFrame())),
                "today_priority_board_rows": len(dataframes.get("today_priority_board", pd.DataFrame())),
                "manager_valuation_profile_rows": len(dataframes.get("manager_valuation_profiles", pd.DataFrame())),
                "manager_transaction_preference_rows": len(dataframes.get("manager_transaction_preferences", pd.DataFrame())),
                "counterparty_edge_rows": len(dataframes.get("counterparty_trade_edges", pd.DataFrame())),
                "counterparty_asset_interest_rows": len(dataframes.get("counterparty_asset_interest", pd.DataFrame())),
                "manager_profile_tag_rows": len(dataframes.get("manager_profile_tags", pd.DataFrame())),
                "player_profile_tag_rows": len(dataframes.get("player_profile_tags", pd.DataFrame())),
                "player_dossier_rows": len(dataframes.get("player_dossiers", pd.DataFrame())),
                "player_horizon_market_rows": len(dataframes.get("player_horizon_market_scores", pd.DataFrame())),
                "available_player_horizon_rows": len(dataframes.get("available_player_horizon_scores", pd.DataFrame())),
                "horizon_snapshot_rows": horizon_snapshot_receipt.get("row_count", 0),
                "horizon_accuracy_rows": len(dataframes.get("horizon_score_accuracy", pd.DataFrame())),
                "horizon_movement_rows": len(dataframes.get("horizon_market_movements", pd.DataFrame())),
                "nfl_schedule_rows": len(dataframes.get("nfl_schedule", pd.DataFrame())),
                "nfl_team_defense_factor_rows": len(dataframes.get("nfl_team_defense_factors", pd.DataFrame())),
            }
        ]
    )

    sqlite_path = processed_dir / "sleeper_dynasty.sqlite"
    with _sqlite_connection(sqlite_path) as conn:
        for name, frame in dataframes.items():
            csv_path = processed_dir / f"{name}.csv"
            frame.to_csv(csv_path, index=False)
            frame.to_sql(name, conn, if_exists="replace", index=False)
            print(f"Wrote {csv_path} ({len(frame)} rows)")

    build_weekly_report(
        reports_dir / "weekly_hinkie_report.md",
        dataframes["teams"],
        dataframes["roster_players"],
        dataframes["trades"],
        dataframes["waivers"],
        manager_profiles,
        pick_ownership,
        current_my_roster_id,
        config.get("strategy_profile") or {},
    )
    print(f"Wrote {reports_dir / 'weekly_hinkie_report.md'}")
    site_path = build_browser_site(
        site_dir,
        processed_dir,
        analysis_dir,
        league_type=league_type,
        # ``league_id`` is the loop variable above and ends on the oldest
        # historical season.  The browser is the current reader surface, so
        # its scoped receipts must use the current-season league id.
        league_id=current_scope_league_id,
        config=config,
    )
    print(f"Wrote {site_path}")


def _sqlite_connection(path: Path):
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def refresh_user(
    username: str,
    season: str,
    force: bool = False,
    user_id: int | str | None = None,
    run_mode: str | None = None,
) -> dict[str, dict[str, str]]:
    api = SleeperAPI(current_season=str(season))
    entries = discover_leagues(api, username, str(season))
    save_registry(entries, user_id=user_id)
    statuses: dict[str, dict[str, str]] = {}

    app_db = None
    db_user_id: int | None = None
    if user_id is not None:
        try:
            db_user_id = int(user_id)
            from app import db as app_db_module

            app_db = app_db_module
            app_db.init_db()
            sleeper_user_ids = {
                str(entry.get("sleeper_user_id") or "")
                for entry in entries
                if entry.get("sleeper_user_id")
            }
            app_db.set_sleeper_account(
                db_user_id,
                username,
                next(iter(sleeper_user_ids), None),
            )
        except (TypeError, ValueError):
            db_user_id = None

    for entry in entries:
        league_id = str(entry.get("league_id") or "")
        league_type = str(entry.get("league_type") or "")
        if not league_id:
            continue
        if league_type == "best_ball":
            continue
        run_id: int | None = None
        try:
            if app_db and db_user_id is not None:
                run_id = app_db.start_refresh_run(
                    db_user_id,
                    league_id,
                    str(entry.get("season") or season),
                )
            profile = app_db.get_team_profile(db_user_id, league_id) if app_db and db_user_id is not None else None
            if app_db and db_user_id is not None and profile is None:
                app_db.migrate_legacy_team_profile(db_user_id, entry, load_config())
                profile = app_db.get_team_profile(db_user_id, league_id)
            manager_trade_profiles = (
                app_db.list_manager_trade_profiles(db_user_id, league_id)
                if app_db and db_user_id is not None
                else []
            )
            context = (
                context_from_league_row(
                    str(user_id),
                    entry,
                    profile,
                    manager_trade_profiles=manager_trade_profiles,
                )
                if user_id is not None
                else None
            )
            roster_id = entry.get("roster_id")
            refresh_paths = (
                LeaguePaths.for_user_league(str(user_id), league_id)
                if user_id is not None
                else LeaguePaths.for_league(league_id)
            )
            selected_mode = refresh_mode_for_paths(refresh_paths, run_mode)
            main(
                force=force,
                league_id=league_id,
                roster_id=int(roster_id) if roster_id not in (None, "") else None,
                paths=refresh_paths,
                league_type=league_type,
                context=context,
                run_mode=selected_mode,
            )
            if app_db and run_id is not None:
                app_db.finish_refresh_run(run_id, "complete")
            statuses[league_id] = {"state": "complete", "message": f"{selected_mode.title()} refresh complete.", "league_type": league_type, "refresh_mode": selected_mode}
        except Exception as exc:  # noqa: BLE001 - one league failing must not stop the rest.
            if app_db and run_id is not None:
                app_db.finish_refresh_run(run_id, "failed", str(exc))
            statuses[league_id] = {
                "state": "failed",
                "message": f"Refresh failed: {exc}",
                "league_type": league_type,
            }

    return statuses


def _discover_league_history(config: dict, api: SleeperAPI, force: bool = False) -> dict[str, str]:
    configured = {str(season): str(league_id) for season, league_id in (config.get("leagues") or {}).items() if league_id}
    if not (config.get("historical_ingestion") or {}).get("auto_discover_previous_leagues", True):
        return configured
    current_season = str(config.get("current_season", "") or "")
    current_league_id = configured.get(current_season)
    if not current_league_id:
        return configured

    return _discover_league_history_from_seed(config, api, current_league_id, force=force, configured=configured)


def _discover_league_history_from_seed(
    config: dict,
    api: SleeperAPI,
    current_league_id: str,
    force: bool = False,
    configured: dict[str, str] | None = None,
) -> dict[str, str]:
    configured = dict(configured or {})
    if not (config.get("historical_ingestion") or {}).get("auto_discover_previous_leagues", True):
        current_season = str(config.get("current_season", "") or "")
        return configured or ({current_season: current_league_id} if current_season and current_league_id else {})
    current_season = str(config.get("current_season", "") or "")
    if not current_season or not current_league_id:
        return configured

    discovered = dict(configured)
    discovered.setdefault(current_season, current_league_id)
    season = int(current_season) if current_season.isdigit() else 0
    league_id = current_league_id
    seen = {league_id}
    max_history = int((config.get("historical_ingestion") or {}).get("max_previous_seasons", 8))

    for _ in range(max_history):
        league = api.league(str(season), league_id, force=force)
        previous_id = str(league.get("previous_league_id") or "")
        if not previous_id or previous_id in seen or not season:
            break
        season -= 1
        discovered.setdefault(str(season), previous_id)
        seen.add(previous_id)
        league_id = previous_id

    return dict(sorted(discovered.items(), reverse=True))


if __name__ == "__main__":
    main(
        force="--force" in sys.argv,
        run_mode=(sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv and sys.argv.index("--mode") + 1 < len(sys.argv) else None),
    )
