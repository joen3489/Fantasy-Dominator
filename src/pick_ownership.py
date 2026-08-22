from __future__ import annotations

import pandas as pd


def build_pick_ownership(
    traded_picks_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    my_roster_id: int | None,
    league_id: str | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    if traded_picks_df.empty:
        return pd.DataFrame()

    scoped_picks = traded_picks_df
    # Historical ingestion contains several leagues whose Sleeper roster IDs
    # repeat.  The reader-facing ownership ledger must be current-league
    # scoped; callers can omit these filters when they explicitly need the
    # historical reconstruction.
    if league_id and "league_id" in scoped_picks.columns:
        scoped_picks = scoped_picks[scoped_picks["league_id"].astype(str) == str(league_id)]
    if season and "season" in scoped_picks.columns:
        scoped_picks = scoped_picks[scoped_picks["season"].astype(str) == str(season)]
    if scoped_picks.empty:
        return pd.DataFrame()

    team_names = {
        int(row["roster_id"]): row.get("team_name", "")
        for _, row in teams_df.iterrows()
        if not pd.isna(row.get("roster_id"))
    }

    rows = []
    for _, pick in scoped_picks.iterrows():
        original = int(pick["original_roster_id"])
        current = int(pick["current_owner_roster_id"])
        previous = int(pick["previous_owner_roster_id"]) if pick.get("previous_owner_roster_id", "") != "" else None
        rows.append(
            {
                "original_roster_id": original,
                "original_team": pick.get("original_team_name", "") or team_names.get(original, ""),
                "pick_season": str(pick.get("pick_season", "")),
                "round": int(pick.get("round", 0)),
                "current_owner_roster_id": current,
                "current_owner": pick.get("current_owner_team_name", "") or team_names.get(current, ""),
                "previous_owner_roster_id": previous or "",
                "previous_owner": pick.get("previous_owner_team_name", "") or (team_names.get(previous, "") if previous else ""),
                "is_my_original_pick": bool(pick.get("is_my_original_pick", original == my_roster_id)),
                "is_currently_owned_by_me": bool(pick.get("is_currently_owned_by_me", current == my_roster_id)),
                "i_currently_own_it": bool(pick.get("is_currently_owned_by_me", current == my_roster_id)),
            }
        )

    return pd.DataFrame(rows).sort_values(["pick_season", "round", "original_roster_id"])
