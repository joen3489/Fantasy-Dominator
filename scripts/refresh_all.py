from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import build_default_analysis_artifacts
from src.browser_site import build_browser_site
from src.economics import build_economic_tables
from src.external_sources import refresh_external_sources
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
    to_dataframes,
)
from src.pick_ownership import build_pick_ownership
from src.players import load_players, players_table
from src.priority_board import build_today_priority_board
from src.profile_intelligence import build_profile_intelligence_tables
from src.projection_accuracy import append_projection_accuracy_snapshot, build_projection_accuracy_table
from src.projections import _load_raw_stats, build_projection_tables
from src.reports import build_weekly_report
from src.sleeper_api import SleeperAPI
from src.signals import build_signal_tables
from src.utils import PROCESSED_DIR, RAW_EXTERNAL_DIR, REPORTS_DIR, SITE_DIR, ensure_dirs, load_config


def main(force: bool = False) -> None:
    ensure_dirs()
    config = load_config()
    api = SleeperAPI()
    players = load_players(api, force=force)
    current_team = config.get("current_team", {}) or {}
    my_display_name = current_team.get("display_name") or config.get("my_display_name", "")
    my_team_name = current_team.get("team_name") or config.get("my_team_name", "")
    configured_roster_id = current_team.get("roster_id")
    configured_roster_id = int(configured_roster_id) if configured_roster_id not in (None, "") else None
    week_start = int(config.get("transaction_weeks", {}).get("start", 1))
    week_end = int(config.get("transaction_weeks", {}).get("end", 18))
    league_ids_by_season = _discover_league_history(config, api, force=force)

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
    }
    current_my_roster_id = None

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
        transactions_by_week = {
            week: api.transactions(season, league_id, week, force=force)
            for week in range(week_start, week_end + 1)
        }

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
            normalize_roster_players(season, league_id, rosters, roster_map, my_roster_id, players)
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

    dataframes = to_dataframes(all_tables)
    manager_profiles = build_manager_profiles(
        dataframes["teams"],
        dataframes["trades"],
        dataframes["waivers"],
        dataframes["roster_players"],
    )
    pick_ownership = build_pick_ownership(dataframes["traded_picks"], dataframes["teams"], current_my_roster_id)
    dataframes["manager_profiles"] = manager_profiles
    dataframes["pick_ownership"] = pick_ownership
    dataframes.update(external_frames)
    dataframes.update(build_news_tables(config, api, players, dataframes["teams"], dataframes["roster_players"], force=force))

    nflverse_stats_path = RAW_EXTERNAL_DIR / "nflverse" / str(config.get("current_season", "")) / "player_stats.csv"
    raw_stats_for_grading = _load_raw_stats(nflverse_stats_path)
    accuracy_history_path = PROCESSED_DIR / "projection_snapshot_history.csv"
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
    # Append-only projection history log (Sprint 10 pattern) -- deliberately not part
    # of the overwrite-every-refresh export loop below.
    append_projection_accuracy_snapshot(accuracy_history_path, dataframes["projection_source_components"], config)

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
        )
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
        )
    )
    configured_seasons = [str(season) for season, league_id in league_ids_by_season.items() if league_id]
    ingested_seasons = sorted({str(value) for value in dataframes["leagues"].get("season", pd.Series(dtype=str)).dropna().tolist()})
    analysis_metadata = build_default_analysis_artifacts(dataframes, config, current_my_roster_id)
    dataframes["refresh_metadata"] = pd.DataFrame(
        [
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "current_season": config.get("current_season", ""),
                "configured_league_ids": ";".join(
                    str(value) for value in league_ids_by_season.values() if value
                ),
                "configured_seasons": ";".join(configured_seasons),
                "ingested_seasons": ";".join(ingested_seasons),
                "historical_league_ids_configured": max(0, len(configured_seasons) - 1),
                "transaction_week_start": week_start,
                "transaction_week_end": week_end,
                "source_scope": "Sleeper public API plus open/legal external sources",
                "raw_cache_root": str((Path("data") / "raw").as_posix()),
                "raw_external_cache_root": str((Path("data") / "raw_external").as_posix()),
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
                "counterparty_edge_rows": len(dataframes.get("counterparty_trade_edges", pd.DataFrame())),
                "manager_profile_tag_rows": len(dataframes.get("manager_profile_tags", pd.DataFrame())),
                "player_profile_tag_rows": len(dataframes.get("player_profile_tags", pd.DataFrame())),
                "player_dossier_rows": len(dataframes.get("player_dossiers", pd.DataFrame())),
            }
        ]
    )

    sqlite_path = PROCESSED_DIR / "sleeper_dynasty.sqlite"
    with _sqlite_connection(sqlite_path) as conn:
        for name, frame in dataframes.items():
            csv_path = PROCESSED_DIR / f"{name}.csv"
            frame.to_csv(csv_path, index=False)
            frame.to_sql(name, conn, if_exists="replace", index=False)
            print(f"Wrote {csv_path} ({len(frame)} rows)")

    build_weekly_report(
        REPORTS_DIR / "weekly_hinkie_report.md",
        dataframes["teams"],
        dataframes["roster_players"],
        dataframes["trades"],
        dataframes["waivers"],
        manager_profiles,
        pick_ownership,
        current_my_roster_id,
        config.get("strategy_profile") or {},
    )
    print(f"Wrote {REPORTS_DIR / 'weekly_hinkie_report.md'}")
    site_path = build_browser_site(SITE_DIR, PROCESSED_DIR)
    print(f"Wrote {site_path}")


def _sqlite_connection(path: Path):
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def _discover_league_history(config: dict, api: SleeperAPI, force: bool = False) -> dict[str, str]:
    configured = {str(season): str(league_id) for season, league_id in (config.get("leagues") or {}).items() if league_id}
    if not (config.get("historical_ingestion") or {}).get("auto_discover_previous_leagues", True):
        return configured
    current_season = str(config.get("current_season", "") or "")
    current_league_id = configured.get(current_season)
    if not current_league_id:
        return configured

    discovered = dict(configured)
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
    main(force="--force" in sys.argv)
