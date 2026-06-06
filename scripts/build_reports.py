from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reports import build_weekly_report
from src.utils import PROCESSED_DIR, REPORTS_DIR, load_config


def main() -> None:
    teams = pd.read_csv(PROCESSED_DIR / "teams.csv")
    roster_players = pd.read_csv(PROCESSED_DIR / "roster_players.csv")
    trades = pd.read_csv(PROCESSED_DIR / "trades.csv")
    waivers = pd.read_csv(PROCESSED_DIR / "waivers.csv")
    manager_profiles = pd.read_csv(PROCESSED_DIR / "manager_profiles.csv")
    pick_ownership = pd.read_csv(PROCESSED_DIR / "pick_ownership.csv")
    config = load_config()
    my = roster_players[roster_players["is_my_team"] == True]
    my_roster_id = int(my.iloc[0]["roster_id"]) if not my.empty else None
    build_weekly_report(
        REPORTS_DIR / "weekly_hinkie_report.md",
        teams,
        roster_players,
        trades,
        waivers,
        manager_profiles,
        pick_ownership,
        my_roster_id,
        config.get("strategy_profile") or {},
    )


if __name__ == "__main__":
    main()
