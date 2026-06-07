# Fantasy Dominator

Local structured data repository for a Sleeper dynasty fantasy football league.

This project pulls read-only public Sleeper API data, caches raw JSON for audit/debugging, normalizes it into CSV files, writes a SQLite database, and produces a browser-first local surface for manager tendencies, pick ownership, trades, waivers, and weekly Hinkie-style roster workflow.

The second sprint adds an economic market layer. Sleeper remains the league source of truth, while open/legal external sources such as nflverse and DynastyProcess are used for usage, value, scarcity, and liquidity context when available. If an external source is unavailable, the app still builds with clearly labeled internal proxy values and source diagnostics.

## League

- Platform: Sleeper
- Current league ID: `1313490073630547968`
- League: `Joanie Loves Dynasty Football`
- My Sleeper display name: `joe3489`
- My team name: `Melkor Lord of Light`
- Format: 12-team dynasty superflex, 0.5 PPR, TE reception bonus

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Refresh All Data

```powershell
python scripts/refresh_all.py
```

The refresh writes:

- Raw API responses to `data/raw/`
- Raw external source files to `data/raw_external/`
- Player cache to `data/cache/players_nfl.json`
- CSV tables to `data/processed/`
- SQLite database to `data/processed/sleeper_dynasty.sqlite`
- Markdown report to `data/reports/weekly_hinkie_report.md`
- Browser workspace to `data/site/index.html`

## Open The Browser Surface

After refreshing:

```powershell
python scripts/serve.py
```

Then open:

```text
http://localhost:8765
```

The browser surface is the primary weekly workspace. CSV, SQLite, and markdown outputs are supporting artifacts for auditability and ChatGPT sharing.

## Railway Production

Railway should run the app as a Python service with:

```text
python scripts/start.py
```

The production start script:

- Uses Railway's `PORT` environment variable.
- Binds to `0.0.0.0` so the service is externally reachable.
- Runs `python scripts/refresh_all.py` on first boot when `data/site/index.html` is missing.
- Serves the generated browser surface from `data/site/`.

Optional environment variables:

- `FANTASY_REFRESH_ON_START=true` refreshes data on every boot.
- `FANTASY_FORCE_REFRESH=true` bypasses existing raw/cache files during startup refresh.
- `HOST=0.0.0.0` is the production default; local `scripts/serve.py` still defaults to `127.0.0.1`.

## Config

Edit `config/leagues.yml` to add prior league IDs by season:

```yaml
leagues:
  "2026": "1313490073630547968"
  "2025": ""
  "2024": ""
```

Blank league IDs are skipped.

## Tables

The first deliverable exports:

- `leagues.csv`
- `teams.csv`
- `players.csv`
- `roster_players.csv`
- `drafts.csv`
- `draft_picks.csv`
- `traded_picks.csv`
- `transactions_raw.csv`
- `transactions_normalized.csv`
- `trades.csv`
- `waivers.csv`
- `manager_profiles.csv`
- `pick_ownership.csv`
- `player_usage_weekly.csv`
- `player_market_values.csv`
- `pick_market_values.csv`
- `team_asset_inventory.csv`
- `manager_event_log.csv` planned as a fuller event feed; manager behavior signals are exported now
- `manager_behavior_signals.csv`
- `team_needs_matrix.csv`
- `liquidity_scores.csv`
- `asset_market_gaps.csv`
- `opportunity_board.csv`
- `source_freshness.csv`
- `news_events.csv`
- `player_news_matches.csv`
- `league_news_impact.csv`
- `news_source_freshness.csv`
- `player_projection_season.csv`
- `player_projection_weekly.csv`
- `projection_source_freshness.csv`
- `player_signal_scores.csv`
- `breakout_candidates.csv`
- `sell_candidates.csv`
- `projection_market_gaps.csv`
- `team_fit_scores.csv`
- `action_recommendations.csv`
- `refresh_metadata.csv`

Analysis artifacts are generated separately under `data/analysis/`:

- `analysis_context_packets.json`
- `target_theses.json`
- `sell_theses.json`
- `trade_theses.json`
- `daily_gm_brief.md`
- `manager_dossiers.md`
- `news_impact_brief.md`
- `analysis_validation.json`

## Notes

- The API is read-only and does not require a token.
- Raw JSON is cached before normalization.
- Player data is cached because `/players/nfl` is large.
- This project does not execute fantasy transactions.
- Analyst artifacts are interpretation only and must cite deterministic processed outputs.
