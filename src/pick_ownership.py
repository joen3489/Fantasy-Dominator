from __future__ import annotations

import pandas as pd


def build_pick_ownership(
    traded_picks_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    my_roster_id: int | None,
) -> pd.DataFrame:
    if traded_picks_df.empty:
        return pd.DataFrame()

    team_names = {
        int(row["roster_id"]): row.get("team_name", "")
        for _, row in teams_df.iterrows()
        if not pd.isna(row.get("roster_id"))
    }

    rows = []
    for _, pick in traded_picks_df.iterrows():
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
