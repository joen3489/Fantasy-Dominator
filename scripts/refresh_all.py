from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser_site import build_browser_site
from src.economics import build_economic_tables
from src.external_sources import refresh_external_sources
from src.manager_profiles import build_manager_profiles
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
from src.reports import build_weekly_report
from src.sleeper_api import SleeperAPI
from src.utils import PROCESSED_DIR, REPORTS_DIR, SITE_DIR, ensure_dirs, load_config


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

    for season, league_id in (config.get("leagues") or {}).items():
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
    dataframes["refresh_metadata"] = pd.DataFrame(
        [
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "current_season": config.get("current_season", ""),
                "configured_league_ids": ";".join(
                    str(value) for value in (config.get("leagues") or {}).values() if value
                ),
                "transaction_week_start": week_start,
                "transaction_week_end": week_end,
                "source_scope": "Sleeper public API plus open/legal external sources",
                "raw_cache_root": str((Path("data") / "raw").as_posix()),
                "raw_external_cache_root": str((Path("data") / "raw_external").as_posix()),
                "browser_is_primary_surface": True,
                "recommendation_packets_status": "planned_contract_only",
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


if __name__ == "__main__":
    main(force="--force" in sys.argv)
