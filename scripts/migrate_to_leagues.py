from __future__ import annotations

"""Copy legacy generated state into the new per-league layout for continuity."""

import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.league_paths import LeaguePaths
from src.league_registry import REGISTRY_PATH, classify_league, load_registry, save_registry
from src.utils import ANALYSIS_DIR, OPERATOR_INBOX_DIR, OPERATOR_OUTBOX_DIR, OPERATOR_STATUS_DIR, PROCESSED_DIR, SITE_DIR, load_config, load_json


def main() -> None:
    config = load_config()
    current_season = str(config.get("current_season", "") or "")
    league_id = str((config.get("leagues") or {}).get(current_season) or "")
    if not current_season or not league_id:
        raise SystemExit("No current season league is configured.")

    paths = LeaguePaths.for_league(league_id)
    paths.ensure()
    copied: list[str] = []
    for source, target in (
        (PROCESSED_DIR, paths.processed_dir),
        (ANALYSIS_DIR, paths.analysis_dir),
        (SITE_DIR, paths.site_dir),
        (OPERATOR_INBOX_DIR, paths.operator_inbox_dir),
        (OPERATOR_OUTBOX_DIR, paths.operator_outbox_dir),
        (OPERATOR_STATUS_DIR, paths.operator_status_dir),
    ):
        if source.exists():
            shutil.copytree(source, target, dirs_exist_ok=True)
            copied.append(f"{source} -> {target}")

    entries = [entry for entry in load_registry(REGISTRY_PATH) if str(entry.get("league_id")) != league_id]
    league = _cached_league_payload(current_season)
    entries.append(
        {
            "league_id": league_id,
            "name": league.get("name", ""),
            "season": current_season,
            "league_type": classify_league(league),
            "roster_id": _configured_roster_id(config),
            "total_rosters": league.get("total_rosters"),
        }
    )
    save_registry(entries, REGISTRY_PATH)

    print(f"Migrated current league {league_id} for season {current_season}.")
    if copied:
        print("Copied:")
        for item in copied:
            print(f"- {item}")
    else:
        print("No legacy generated directories were present to copy.")
    print(f"Wrote registry: {REGISTRY_PATH}")


def _cached_league_payload(season: str) -> dict[str, Any]:
    path = LeaguePaths.default().raw_dir / season / "league.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def _configured_roster_id(config: dict[str, Any]) -> int | None:
    roster_id = (config.get("current_team") or {}).get("roster_id")
    return int(roster_id) if roster_id not in (None, "") else None


if __name__ == "__main__":
    main()
