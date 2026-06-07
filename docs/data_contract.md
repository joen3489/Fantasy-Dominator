# Sleeper Dynasty Data Contract

This project follows a V-model workflow: define trusted data requirements first, then verify each layer with schema, identity, source trace, browser, and refresh checks. `docs/sprint_plan.md` owns the long-range roadmap; this file owns the enforceable table/source contract for the current app.

## Core Invariants

- Sleeper is the league source of truth.
- Raw payloads are preserved before normalization.
- Deterministic app code owns facts and derived analytics.
- Codex-authored content, when added later, must live outside canonical tables.
- Browser and markdown are presentation artifacts only.
- No transaction execution, message sending, Sleeper auth, or Sleeper mutation.
- Every team-scoped output must work for any selected `roster_id`.

## Data Hierarchy

### Layer 0: Raw Sources

Raw sources are cached before transformation:

- Sleeper API JSON under `data/raw/{season}/`
- Open/legal external source files under `data/raw_external/{source}/{season}/`
- Sleeper player cache under `data/cache/players_nfl.json`

Raw files are audit artifacts. Normalization may refresh them, but raw source shape must remain inspectable.

### Layer 1: Canonical Tables

Canonical tables live in `data/processed/` as CSV and SQLite tables. They contain facts from Sleeper or external sources, preserving source identifiers whenever possible.

### Layer 2: Derived Analytics

Derived analytics are generated from canonical tables only. They may include model scores, proxy values, labels, confidence, evidence, and strategy fit, but must preserve enough source trace to audit the result.

### Layer 2A: Projection Data Layer

Projection tables convert historical/open data and league scoring settings into projected fantasy production. They are deterministic model outputs, not analyst prose. Projection rows must preserve player identity, projection method, source trace, and confidence.

### Layer 2B: Transform Signal Layer

Transform tables convert projections, market values, news, roster ownership, manager behavior, and strategy config into deterministic target/sell/breakout/watch signals. Signals must include evidence, risk, confidence, and source trace.

### Layer 3: Strategy And Analyst Views

Strategy views are browser and markdown outputs that apply configurable team strategy. Melkor-specific rebuild logic belongs in `config/leagues.yml` and presentation/report overlays, not in canonical normalization.

## Table Contracts

### Canonical Sleeper Tables

| Table | Owner | Purpose | Source of truth | Required columns | Trace requirement |
| --- | --- | --- | --- | --- | --- |
| `leagues` | Sleeper normalization | League metadata and settings | Sleeper `/league/{league_id}` | `season`, `league_id`, `name`, `status`, `scoring_settings`, `roster_positions`, `playoff_week_start`, `settings` | `season` + `league_id` identify source payload |
| `teams` | Sleeper normalization | Roster/user identity map | Sleeper users + rosters | `season`, `league_id`, `roster_id`, `owner_id`, `display_name`, `team_name`, `waiver_position`, `waiver_budget_used`, `total_moves` | `season`, `league_id`, `roster_id`, `owner_id` |
| `players` | Sleeper player cache | Player metadata | Sleeper `/players/nfl` | `player_id`, `full_name`, `position`, `team`, `age`, `years_exp`, `fantasy_positions`, `status` | `player_id` |
| `roster_players` | Sleeper normalization | Player ownership and roster status | Sleeper rosters + player cache | `season`, `league_id`, `roster_id`, `owner_id`, `player_id`, `player_name`, `position`, `nfl_team`, `age`, `years_exp`, `roster_status`, `is_my_team`, `team_name` | `season`, `league_id`, `roster_id`, `player_id` |
| `drafts` | Sleeper normalization | Draft metadata | Sleeper league drafts | `season`, `league_id`, `draft_id`, `status`, `type`, `settings` | `draft_id` |
| `draft_picks` | Sleeper normalization | Completed draft picks | Sleeper draft picks | `season`, `league_id`, `draft_id`, `pick_no`, `round`, `roster_id`, `picked_by`, `player_id`, `player_name`, `position`, `nfl_team` | `draft_id`, `pick_no`, `player_id` |
| `traded_picks` | Sleeper normalization | Sleeper traded pick state | Sleeper traded picks | `season`, `league_id`, `original_roster_id`, `original_team_name`, `round`, `pick_season`, `current_owner_roster_id`, `current_owner_team_name`, `previous_owner_roster_id`, `previous_owner_team_name`, `is_my_original_pick`, `is_currently_owned_by_me` | original/current/previous roster IDs |
| `transactions_raw` | Sleeper normalization | Raw transaction audit rows | Sleeper transactions by week | `season`, `league_id`, `week`, `transaction_id`, `type`, `status`, `created`, `raw` | `transaction_id`, `raw` |
| `transactions_normalized` | Sleeper normalization | Human-readable transaction facts | Sleeper transactions by week | `season`, `league_id`, `week`, `transaction_id`, `type`, `status`, `created_datetime`, `roster_ids_involved`, `manager_team_names_involved`, `adds`, `drops`, `draft_picks_moved`, `waiver_bid`, `faab_moved`, `failure_reason` | `transaction_id` |
| `trades` | Sleeper normalization | Two-team trade ledger | Sleeper trade transactions | `season`, `league_id`, `week`, `transaction_id`, `created_datetime`, `team_a_roster_id`, `team_a_name`, `team_a_players_received`, `team_a_picks_received`, `team_a_faab_received`, `team_b_roster_id`, `team_b_name`, `team_b_players_received`, `team_b_picks_received`, `team_b_faab_received`, `raw` | `transaction_id`, `raw` |
| `waivers` | Sleeper normalization | Waiver claim ledger | Sleeper waiver transactions | `season`, `league_id`, `week`, `transaction_id`, `roster_id`, `team_name`, `player_added`, `player_dropped`, `waiver_bid`, `status`, `failure_reason` | `transaction_id`, `roster_id` |

### Canonical External Tables

| Table | Owner | Purpose | Source of truth | Required columns | Trace requirement |
| --- | --- | --- | --- | --- | --- |
| `player_usage_weekly` | External source normalization | Weekly NFL usage/performance context | nflverse player stats | `source`, `season`, `week`, `player_id`, `player_name`, `position`, `team`, `targets`, `carries`, `receptions`, `passing_attempts`, `fantasy_points_ppr`, `source_trace` | `source`, `source_trace` |
| `market_value_sources` | External source normalization | Component-level player market value rows before consensus | DynastyProcess plus user-provided/manual market files when configured | `source`, `source_access_type`, `source_player_id`, `player_id`, `player_name`, `position`, `raw_value`, `normalized_value`, `market_rank`, `value_format`, `source_confidence`, `source_trace`, `checked_at` | `source`, `source_access_type`, `source_confidence`, `source_trace`, `checked_at`; KTC-like data is manual/permissioned only |
| `market_consensus_values` | Deterministic market normalization | Consensus player market value derived from component sources | `market_value_sources` | `player_id`, `player_name`, `position`, `consensus_value`, `source_count`, `disagreement_score`, `best_source`, `confidence`, `source_trace` | source count, disagreement, confidence, and component traces required |
| `player_market_values` | External source compatibility view | Legacy player market values for existing transforms | `market_consensus_values` | `source`, `source_player_id`, `player_id`, `player_name`, `position`, `market_value`, `market_rank`, `value_format`, `source_trace` | `source`, `source_trace`; should be treated as compatibility output, not the only market model |
| `pick_market_values` | External source normalization | Pick market values when source is available | DynastyProcess or configured pick value source | `source`, `pick_label`, `pick_season`, `round`, `market_value`, `source_trace` | `source`, `source_trace`; empty table is valid when source unavailable |
| `source_freshness` | External source normalization | Source status and row-count diagnostics | Refresh process | `source`, `dataset`, `status`, `source_url`, `cache_path`, `checked_at`, `row_count` | rows must explain available, cached, disabled, or unavailable source state |
| `news_events` | News source normalization | Raw news/trending items normalized into rows | RotoWire RSS and Sleeper trending | `source`, `event_id`, `event_type`, `published_at`, `title`, `summary`, `url`, `player_id`, `player_name`, `team`, `position`, `source_trace` | `event_id`, `source`, `source_trace` |
| `player_news_matches` | News source normalization | Match news items to Sleeper player IDs | `news_events` + Sleeper player cache | `event_id`, `source`, `input_player_name`, `player_id`, `matched_player_name`, `match_method`, `match_confidence`, `is_ambiguous`, `source_trace` | match method and confidence required |
| `league_news_impact` | Deterministic news analytics | Roster-scoped news impacts | `news_events`, `player_news_matches`, `roster_players`, `teams` | `event_id`, `source`, `published_at`, `player_id`, `player_name`, `roster_id`, `team_name`, `impact_type`, `evidence`, `risk`, `confidence`, `source_trace` | `evidence`, `risk`, `confidence`, `source_trace` required |
| `news_source_freshness` | News source normalization | News source status and row-count diagnostics | Refresh process | `source`, `dataset`, `status`, `source_url`, `cache_path`, `checked_at`, `row_count` | rows must explain cached, refreshed, disabled, or unavailable source state |

### Projection Tables

| Table | Owner | Purpose | Inputs | Required columns | Trace/evidence requirement |
| --- | --- | --- | --- | --- | --- |
| `player_projection_season` | Deterministic projection code | Season-level projected fantasy production | `player_usage_weekly`, `players`, league scoring config, roster ownership | `season`, `player_id`, `player_name`, `position`, `team`, `projected_games`, `projected_passing_yards`, `projected_passing_tds`, `projected_interceptions`, `projected_rushing_yards`, `projected_rushing_tds`, `projected_receptions`, `projected_receiving_yards`, `projected_receiving_tds`, `projected_fantasy_points`, `projected_ppg`, `projection_method`, `projection_confidence`, `source_trace` | `projection_method`, `projection_confidence`, `source_trace` required |
| `player_projection_weekly` | Deterministic projection code | Weekly projected fantasy allocation | `player_projection_season`, schedule/weekly allocation rules | `season`, `week`, `player_id`, `player_name`, `position`, `team`, `projected_fantasy_points`, `projected_snap_or_usage_note`, `projection_method`, `projection_confidence`, `source_trace` | `projection_method`, `projection_confidence`, `source_trace` required |
| `projection_source_freshness` | Projection refresh process | Projection source status and diagnostics | Refresh process | `source`, `dataset`, `status`, `source_url`, `cache_path`, `checked_at`, `row_count` | rows must explain available, cached, disabled, or unavailable projection inputs |

### Derived Analytics Tables

| Table | Owner | Purpose | Inputs | Required columns | Trace/evidence requirement |
| --- | --- | --- | --- | --- | --- |
| `manager_profiles` | Deterministic analytics | Summarize manager trade/waiver tendencies across current and discovered historical Sleeper leagues | `teams`, `trades`, `waivers`, `roster_players` | `owner_id`, `roster_id`, `display_name`, `team_name`, `seasons_covered`, `roster_ids_by_season`, `team_names_by_season`, `total_trades`, `trades_by_season`, `players_acquired`, `players_sold`, `picks_acquired`, `picks_sold`, `future_1sts_acquired`, `future_1sts_sold`, `future_2nds_acquired`, `future_2nds_sold`, `faab_spent_on_waivers`, `number_of_waiver_claims`, `average_waiver_bid`, `max_waiver_bid`, `most_common_transaction_partners`, `qb_count`, `rb_count`, `pass_catcher_count`, `contender_rebuilder_indicator`, `notes` | owner ID is cross-season identity when available; roster ID remains current-season label |
| `pick_ownership` | Deterministic analytics | Human-readable traded pick ownership | `traded_picks`, `teams` | `original_roster_id`, `original_team`, `pick_season`, `round`, `current_owner_roster_id`, `current_owner`, `previous_owner_roster_id`, `previous_owner`, `is_my_original_pick`, `is_currently_owned_by_me`, `i_currently_own_it` | original/current/previous roster IDs |
| `team_asset_inventory` | Deterministic economics | Unified player/pick asset ledger | roster, pick, market value tables | `roster_id`, `team_name`, `asset_type`, `asset_id`, `asset_name`, `position`, `age`, `market_value`, `liquidity_tier`, `timeline_fit`, `source_trace` | `source_trace` required; proxy values must be labeled |
| `manager_event_log` | Deterministic analytics | Traceable manager event feed | `trades`, `waivers` | `event_type`, `week`, `created_datetime`, `transaction_id`, `roster_id`, `team_name`, `counterparty`, `players_in`, `picks_in`, `faab_in`, `players_out`, `picks_out`, `faab_out`, `evidence` | `transaction_id`, `evidence` |
| `team_needs_matrix` | Deterministic economics | Team roster-shape and pick-capital needs | `teams`, `roster_players`, `pick_ownership` | `roster_id`, `team_name`, `qb_count`, `rb_count`, `wr_count`, `te_count`, `pass_catcher_count`, `future_firsts_owned`, `need_qb`, `need_rb`, `need_pass_catcher`, `need_picks`, `team_shape` | counts are derived from canonical tables |
| `manager_behavior_signals` | Deterministic analytics | Scored manager behavior labels | `teams`, `trades`, `waivers`, `manager_profiles`, `roster_players` | `roster_id`, `team_name`, `trade_activity_score`, `pick_buyer_score`, `pick_seller_score`, `faab_aggression_score`, `waiver_activity_score`, `rb_appetite_score`, `pass_catcher_appetite_score`, `plain_language_label`, `evidence` | `evidence` required |
| `manager_valuation_profiles` | Deterministic revealed-preference model | Estimate manager asset-type preferences from observed history | `teams`, `manager_profiles`, `roster_players` | `owner_id`, `roster_id`, `team_name`, `asset_type`, `position_group`, `preference_score`, `evidence_count`, `recency_weighted_score`, `confidence`, `label`, `evidence` | `evidence`, sample size, and confidence required; language must remain estimate-based |
| `liquidity_scores` | Deterministic economics | Asset liquidity estimate | `team_asset_inventory`, `team_needs_matrix` | `roster_id`, `team_name`, `asset_type`, `asset_name`, `position`, `market_value`, `liquidity_score`, `liquidity_tier`, `demand_signal`, `source_trace` | `source_trace` required |
| `asset_market_gaps` | Deterministic economics | Buy/sell/target gap signals | inventory, needs, behavior, strategy config | `target_roster_id`, `target_team`, `asset_type`, `asset_name`, `position`, `market_value`, `market_gap_score`, `opportunity_type`, `timeline_fit`, `evidence`, `risk`, `confidence`, `source_trace` | `evidence`, `risk`, `confidence`, `source_trace` required |
| `opportunity_board` | Deterministic economics | Read-only action preview | `asset_market_gaps`, behavior, strategy config | `action_type`, `target_team`, `asset_in`, `asset_out`, `manager_signal`, `evidence`, `risk`, `confidence`, `source_trace` | `evidence`, `risk`, `confidence`, `source_trace` required |
| `refresh_metadata` | Refresh process | One-row refresh diagnostics | config + refresh run | `generated_at`, `current_season`, `configured_league_ids`, `transaction_week_start`, `transaction_week_end`, `source_scope`, `raw_cache_root`, `raw_external_cache_root`, `browser_is_primary_surface`, `recommendation_packets_status` | must describe generated source scope |

### Transform Signal Tables

| Table | Owner | Purpose | Inputs | Required columns | Trace/evidence requirement |
| --- | --- | --- | --- | --- | --- |
| `player_signal_scores` | Deterministic signal code | Unified player target/sell/watch scoring | projections, market values, roster ownership, news impact, manager behavior | `player_id`, `player_name`, `position`, `roster_id`, `team_name`, `projection_edge_score`, `market_gap_score`, `timeline_fit_score`, `breakout_score`, `sell_score`, `signal_label`, `evidence`, `risk`, `confidence`, `source_trace` | `evidence`, `risk`, `confidence`, `source_trace` required |
| `breakout_candidates` | Deterministic signal code | Ranked breakout/target candidates | `player_signal_scores` | `player_id`, `player_name`, `position`, `current_team_name`, `breakout_score`, `projection_edge`, `market_value`, `evidence`, `risk`, `confidence`, `source_trace` | derived from signal scores |
| `sell_candidates` | Deterministic signal code | Ranked sell/trade-away candidates | `player_signal_scores` | `player_id`, `player_name`, `position`, `current_team_name`, `sell_score`, `projection_risk`, `market_value`, `evidence`, `risk`, `confidence`, `source_trace` | derived from signal scores |
| `projection_market_gaps` | Deterministic signal code | Projection production vs market value gaps | projections, market values | `player_id`, `player_name`, `position`, `projected_fantasy_points`, `projected_ppg`, `market_value`, `gap_score`, `gap_label`, `evidence`, `risk`, `confidence`, `source_trace` | projection and market source traces required |
| `team_fit_scores` | Deterministic signal code | Fit of player assets by selected team timeline and needs | projections, roster ownership, team needs, strategy config | `roster_id`, `team_name`, `player_id`, `player_name`, `position`, `timeline_fit_score`, `need_fit_score`, `liquidity_fit_score`, `fit_label`, `evidence`, `risk`, `confidence`, `source_trace` | works for any selected roster_id |
| `counterparty_trade_edges` | Deterministic counterparty model | Estimate where our projection/market view may diverge from current owner preference | `player_signal_scores`, `manager_valuation_profiles`, `team_needs_matrix`, strategy config | `target_roster_id`, `target_team`, `player_id`, `player_name`, `position`, `our_value_score`, `market_consensus_value`, `estimated_owner_value_score`, `trade_edge_score`, `edge_type`, `evidence`, `risk`, `confidence`, `source_trace` | must say estimate, include evidence/risk/confidence, and never imply a trade was sent or accepted |

## Presentation Artifacts

| Artifact | Owner | Purpose | Rule |
| --- | --- | --- | --- |
| `data/site/index.html` | Browser generation code | Primary browser workflow | Presentation only; reads processed tables |
| `data/reports/weekly_hinkie_report.md` | Report generation code | Markdown strategy report | Presentation only; strategy overlay is allowed |
| `data/processed/sleeper_dynasty.sqlite` | Refresh process | SQLite mirror of processed CSVs | Generated artifact; tables replaced on refresh |
| `action_recommendations` | Deterministic signal code | Consumer-facing action labels from calibrated signal rows | Derived table; must include why, risk, confidence, evidence, and source trace |
| `data/analysis/analysis_context_packets.json` | Analysis layer | Machine-readable context packets for analyst generation | Interpretation input only; built from processed tables |
| `data/analysis/target_theses.json` | Codex analyst layer | Explained target theses from signal outputs | Interpretation only; must cite signal/projection evidence |
| `data/analysis/sell_theses.json` | Codex analyst layer | Explained sell theses from signal outputs | Interpretation only; must cite signal/projection evidence |
| `data/analysis/trade_theses.json` | Codex analyst layer | Manager-aware trade thesis packets | Interpretation only; no transaction execution or outbound messaging |
| `data/analysis/daily_gm_brief.md` | Codex analyst layer | Readable active-team analyst brief | Presentation and interpretation only |
| `data/analysis/manager_dossiers.md` | Codex analyst layer | Plain-language manager behavior summaries | Must be grounded in manager behavior/event tables |
| `data/analysis/news_impact_brief.md` | Codex analyst layer | Readable summary of imported news impact rows | Must not become canonical news truth |
| `data/analysis/analysis_validation.json` | Analysis layer | Artifact validation status and guardrail errors | Generated validation artifact |

## Source Ownership

- Sleeper owns league identity, rosters, users, transactions, drafts, traded picks, and player metadata.
- nflverse owns NFL usage/performance reference data when available.
- DynastyProcess owns imported market value reference data when available.
- User-provided market files may contribute to `market_value_sources` only as `source_access_type=user_provided` or another explicit non-scraped access type.
- KeepTradeCut-like sentiment is manual/permissioned only unless official access changes; do not automate scraping, hidden API calls, or paywall/restriction bypass.
- RotoWire RSS owns attributed player-news rows imported through its published RSS feed.
- Sleeper trending owns public add/drop trend rows imported through the Sleeper trending endpoint.
- Projection code owns deterministic projected stats and fantasy point calculations.
- Transform code owns breakout/sell/watch labels and scores.
- Codex and deterministic analysis templates own explanation of transform outputs only, not projection facts or signal scores.
- Internal proxy values are continuity fallbacks only.
- Config owns selected current team, strategy profile, tracked pick priorities, and source toggles.
- Processed tables own normalized analysis state.
- Browser and markdown own presentation only.

## Internal Proxy Value Rules

Internal proxy values are allowed only when an external source is missing, empty, or cannot match an asset.

Proxy rules:

- Proxy values must be labeled in `source_trace`, such as `internal_proxy_player_value` or `dynastyprocess_pick_value_or_internal_curve`.
- Proxy values must not be described as market truth.
- Source diagnostics must still show whether the external source was cached, refreshed, disabled, or unavailable.
- Decision-support outputs using proxy values must carry at most medium confidence unless later evidence upgrades them.

## Refresh Lifecycle

1. Pull and cache raw Sleeper JSON.
2. Pull and cache open/legal external files.
3. Normalize canonical tables.
4. Build derived analytics.
5. Export CSV and SQLite with replace semantics.
6. Generate markdown and browser surfaces.
7. Run schema, source-trace, browser, and idempotency checks.

Refreshes must be idempotent: generated CSV, SQLite, browser, and report outputs are replaced, not appended.

## Future Recommendation Packet Contract

Recommendation generation remains read-only. Future packets should be structured and auditable:

- `action_type`
- `target_team`
- `assets_in`
- `assets_out`
- `evidence`
- `risk`
- `confidence`
- `source_trace`
- `analyst_note`

The current `opportunity_board` is a read-only preview of this shape. Future packets should cite projection and signal rows when available. It is not a trade executor.

## V-Model Acceptance Checks

- R1/V1: Endpoint coverage and raw cache files exist.
- R2/V2: Open/legal external sources are cached or marked unavailable without breaking the Sleeper-only build.
- R3/V3: Required canonical and derived table columns exist.
- R4/V4: Economic outputs preserve evidence and source traces.
- R5/V5: Browser views respond to arbitrary selected roster IDs.
- R6/V6: Strategy profile can be read from config without changing canonical tables.
- R7/V7: Local browser surface loads and exposes source diagnostics.
- R8/V8: Refresh is idempotent and generated outputs are replaced, not appended.
