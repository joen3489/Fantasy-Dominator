# Fantasy Dominator

Personal, browser-first fantasy football headquarters for Sleeper leagues.

The app pulls read-only public Sleeper API data, caches raw JSON for audit/debugging, normalizes it into CSV files and SQLite, and produces decision support for roster health, manager tendencies, pick ownership, trades, waivers, projections, and weekly Hinkie-style roster workflow. Deterministic analysis is the source of truth; the API writers turn that evidence into cited personal content.

Sleeper remains the league source of truth, while open/legal external sources such as nflverse and DynastyProcess provide usage, value, scarcity, liquidity, projection, and news context when available. If an external source is unavailable, the app still builds with clearly labeled internal proxy values and source diagnostics.

## Legacy league seed

- Platform: Sleeper
- Current league ID: `1313490073630547968`
- League: `Joanie Loves Dynasty Football`
- My Sleeper display name: `joe3489`
- My team name: `Melkor Lord of Light`
- Format: 12-team dynasty superflex, 0.5 PPR, TE reception bonus

## Ownership model

The old config/leagues.yml singleton is retained as a legacy seed and CLI default. New authenticated work is scoped as:

~~~text
user
└── league
    ├── managed team identity and strategy profile
    ├── refresh and attention receipts
    ├── deterministic processed tables and analysis
    └── writer artifacts and browser site
~~~

Shared external source facts remain in data/raw_external/. User/league-derived state is written under data/users/<user_id>/leagues/<league_id>/. The database stores users, linked leagues, team profiles, content-artifact receipts, and refresh history. A read-only fallback can serve older data/leagues/<league_id>/ artifacts during migration.

Each league can customize team name/display name, strategy direction, contention window, structured strategy values, and writer preferences. Manager trade profiles are generated inside that league/team context, so one user's strategy cannot change another user's recommendations.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Refresh data

```powershell
python scripts/refresh_all.py
```

This is the legacy/default workspace refresh. The authenticated scheduler and operator routes use the linked user's private workspace. The refresh writes:

- Raw API responses to `data/raw/`
- Raw external source files to `data/raw_external/`
- Player cache to `data/cache/players_nfl.json`
- CSV tables to `data/processed/`
- SQLite database to `data/processed/sleeper_dynasty.sqlite`
- Markdown report to `data/reports/weekly_hinkie_report.md`
- Browser workspace to `data/site/index.html`

For an authenticated user's linked leagues, the equivalent workflow is scripts.refresh_all.refresh_user(username, season, user_id=...); the scheduler calls this per user and rebuilds that user's attention queue.

## Run the authenticated app

After refreshing:

```powershell
python -m app.main
```

Then open:

```text
http://localhost:8765
```

The app exposes /healthz, /login, the personal headquarters at /, and owned league sites at /league/<league_id>/. Use the home-screen Sleeper link flow to discover leagues. The headquarters includes a per-league team strategy and reporter editor backed by GET and PUT /api/leagues/<league_id>/profile, plus an authenticated `/api/continuity` receipt showing whether the current identity sees a configured durable workspace. Each league can choose a bounded reporter persona (The Front Office, The Scout, The Commissioner, or The Quant) plus a short editor note; the selected voice is carried into generated article prompts and published issue metadata.

The headquarters also exposes league-scoped manager trade profiles at
`/api/leagues/<league_id>/manager-trade-profiles`. These are private editorial
notes about how to frame a conversation with a manager (approach, preferred
assets, protected assets, and an editor note). They are passed to the selected
league's writers as context only and are never treated as observed evidence.

The browser surface is the primary weekly workspace. CSV, SQLite, and markdown outputs are supporting artifacts for auditability and ChatGPT sharing. scripts/serve.py remains a legacy static/local server for the default workspace.

## Railway Production

Railway runs the authenticated app with:

```text
python -m app.main
```

railway.json health-checks /healthz. Configure Clerk issuer/JWKS/publishable-key settings required by app/auth.py, FRONT_OFFICE_OPERATOR_TOKEN for refresh/writer/browser-rebuild mutations, FRONT_OFFICE_SCHEDULER=on for the per-user scheduler, FRONT_OFFICE_REFRESH_INTERVAL for its interval, and ANTHROPIC_API_KEY only for explicit writer actions.

For a real production Clerk deployment, use a `pk_live_` publishable key and
set `FRONT_OFFICE_PUBLIC_URL=https://your-public-domain/` (the app also falls
back to Railway's `RAILWAY_PUBLIC_DOMAIN` when present). The login page uses
that canonical URL for every Clerk redirect, which avoids Railway's internal
HTTP hop being mistaken for the public HTTPS origin. `/healthz` exposes only
safe configuration signals (`revision`, `auth_mode`, Clerk issuer/JWKS readiness,
`public_url_configured`, `data_root_configured`, SQLite schema readiness,
`writer_api_configured`, `deployment_ready`, and safe blocker messages) so a
deploy can be checked without exposing credentials or user data. In a Railway
environment, the login surface refuses to mount Clerk and league-linking or
refreshing returns a setup error until live auth, durable storage, and the
protected scheduler configuration are ready. This prevents an ephemeral or
wrong-identity deployment from looking like an empty personal headquarters.

Generated state is intentionally not stored in Git. For production continuity,
mount a durable Railway volume at `/app/data` and set
`FRONT_OFFICE_DATA_DIR=/app/data`. This single root contains the app identity
database, per-user league workspaces, refresh receipts, generated articles, and
browser edition bundles. A healthy `/healthz` response alone does not prove
that this state root is mounted or that the current Clerk identity can see the
preserved rows. An authenticated operator can use
`GET /api/operator/storage-audit` with `x-front-office-token` to see safe row
counts and distinguish the current identity from preserved rows under another
identity; it never returns Clerk subjects, league IDs, or league names.

An edition is considered readable only when its `index.html`, fact bundle,
editorial issue receipt, manifest, and lazy audit payloads are present. If a
refresh fails, the app should continue serving the last complete edition and
show the refresh receipt rather than an empty shell or raw file-not-found JSON.

Optional environment variables:

- FRONT_OFFICE_REQUIRE_OPERATOR_TOKEN=true fails operator actions closed even when the token variable is missing.
- FRONT_OFFICE_LIVE_CACHE_MAX_AGE_SECONDS controls normal Sleeper cache expiry for the current season (default 900 seconds).
- FRONT_OFFICE_HISTORICAL_CACHE_MAX_AGE_SECONDS controls historical Sleeper cache expiry (default 30 days).
- FRONT_OFFICE_PLAYER_CACHE_MAX_AGE_SECONDS controls the large `/players/nfl` cache expiry (default 24 hours).
- FRONT_OFFICE_NEWS_CACHE_MAX_AGE_SECONDS controls RotoWire/Sleeper-trending cache expiry (default 900 seconds).
- FRONT_OFFICE_EXTERNAL_CACHE_MAX_AGE_SECONDS controls DynastyProcess, nflverse, and configured external cache expiry (default 24 hours).
- FRONT_OFFICE_EXPECTED_REVISION makes the live smoke check fail if Railway is serving a different Git revision.
- HOST=0.0.0.0 and PORT=8765 are the app defaults.

Normal scheduled refreshes now honor those expiry windows. A stale source is
refetched; if that refetch fails, the last cached payload can still support the
last complete edition but its receipt is marked limited rather than current.

The production smoke check can validate the public deployment and, when
`FRONT_OFFICE_SESSION_TOKEN` is supplied locally, the authenticated home page,
continuity receipt, and every owned league edition. If
`FRONT_OFFICE_OPERATOR_TOKEN` is also supplied locally, it checks the
operator-safe storage audit and verifies that the current identity has at least
one preserved league. It fails when live Clerk or durable SQLite configuration
is incomplete and warns when the optional Anthropic writer key is absent:

```powershell
python scripts\smoke_live.py
```

## Config and migration

Edit `config/leagues.yml` to add prior league IDs by season:

```yaml
leagues:
  "2026": "1313490073630547968"
  "2025": ""
  "2024": ""
```

Blank league IDs are skipped.

The config file is now a legacy/default seed. Authenticated users link their own Sleeper account from the home screen. When a linked roster matches current_team.roster_id, its strategy profile is copied idempotently into the user's team profile; later edits are stored per league and take precedence over the seed.

## Writers and evidence

Writer actions are explicit and cost-incurring. They read only the selected league's deterministic analysis and write section articles, manager/player insight packets, and the Daily GM Brief into that league's private analysis/operator workspace. Every generated artifact is indexed by user, league, season, artifact key, and reporter persona in content_artifacts; no writer is scheduled automatically. The persona changes tone and emphasis only; deterministic evidence, citations, and read-only safety rules remain authoritative. See `docs/reporter_personas.md` for the contract.

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

- Sleeper and fantasy transaction APIs are read-only; the authenticated app requires Clerk, and operator mutations require the configured operator token.
- Raw JSON is cached before normalization.
- Player data is cached because `/players/nfl` is large.
- This project does not execute fantasy transactions.
- Analyst artifacts are interpretation only and must cite deterministic processed outputs.

## Verification

~~~powershell
python -m unittest discover -s tests
python -m py_compile app\main.py app\scheduler.py src\context.py scripts\refresh_all.py
python scripts\validate_local_data.py
~~~

`validate_local_data.py` is read-only: it checks refresh age, imported news,
source freshness, evidence traces, and deterministic analysis artifacts. It
returns success when optional sources are explicitly disabled but reports those
sources as warnings.
