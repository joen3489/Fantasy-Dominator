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

### Layer 4: Private Decision Ledger

The SQLite `content_interactions` store is private, user/league/roster-scoped
state, not canonical Sleeper data. Article usefulness/outcome signals use
`artifact_type=article` and `interaction_type=outcome`. Actionable target,
sell, and trade theses use `artifact_type=recommendation` and
`interaction_type=decision_outcome`, keyed to the thesis and bundle revision.
Manager dossier trade-fit hypotheses use the same recommendation lane with a
`manager-fit:<roster_id>:<player_id>` artifact key, so the direct manager page
does not create a second learning ledger.
The ledger records what the manager later reports happened; it does not infer
an outcome from a page view, execute a trade, or rewrite deterministic facts.
Open, confirmed, missed, and unclear remain separate states, and article
learning rates must not be blended with recommendation rates.

## Table Contracts

### Canonical Sleeper Tables

| Table | Owner | Purpose | Source of truth | Required columns | Trace requirement |
| --- | --- | --- | --- | --- | --- |
| `leagues` | Sleeper normalization | League metadata and settings | Sleeper `/league/{league_id}` | `season`, `league_id`, `name`, `status`, `scoring_settings`, `roster_positions`, `playoff_week_start`, `settings` | `season` + `league_id` identify source payload |
| `teams` | Sleeper normalization | Roster/user identity map | Sleeper users + rosters | `season`, `league_id`, `roster_id`, `owner_id`, `display_name`, `team_name`, `waiver_position`, `waiver_budget_used`, `total_moves` | `season`, `league_id`, `roster_id`, `owner_id` |
| `players` | Sleeper player cache | Player metadata and current availability context | Sleeper `/players/nfl` | `player_id`, `full_name`, `position`, `team`, `age`, `years_exp`, `fantasy_positions`, `status`, `injury_status`, `injury_body_part` | `player_id`; missing injury fields are unknown, not an injury clearance; a blank current NFL `team` is an explicit no-current-team state, not evidence that the player is available for a current role |
| `roster_players` | Sleeper normalization | Player ownership, roster status, and current-season availability context | Sleeper rosters + player cache | `season`, `league_id`, `roster_id`, `owner_id`, `player_id`, `player_name`, `position`, `nfl_team`, `age`, `years_exp`, `availability_scope`, `injury_status`, `injury_body_part`, `roster_status`, `is_my_team`, `team_name` | `season`, `league_id`, `roster_id`, `player_id`; `availability_scope` is `current_season_snapshot` for the configured current season and `historical_unavailable` for older or boundary-less rows; current Sleeper injury fields are populated only for the configured current season; historical roster rows leave them blank rather than presenting today's status as a dated observation; a blank `nfl_team` in a current snapshot becomes `current_availability_status=no_current_nfl_team`; historical production may remain as conditional evidence, but it is not a current-role or next-game forecast |
| `drafts` | Sleeper normalization | Draft metadata | Sleeper league drafts | `season`, `league_id`, `draft_id`, `status`, `type`, `settings` | `draft_id` |
| `draft_picks` | Sleeper normalization | Completed draft picks | Sleeper draft picks | `season`, `league_id`, `draft_id`, `pick_no`, `round`, `roster_id`, `picked_by`, `player_id`, `player_name`, `position`, `nfl_team` | `draft_id`, `pick_no`, `player_id` |
| `traded_picks` | Sleeper normalization | Sleeper traded pick state | Sleeper traded picks | `season`, `league_id`, `original_roster_id`, `original_team_name`, `round`, `pick_season`, `current_owner_roster_id`, `current_owner_team_name`, `previous_owner_roster_id`, `previous_owner_team_name`, `is_my_original_pick`, `is_currently_owned_by_me` | original/current/previous roster IDs |
| `transactions_raw` | Sleeper normalization | Raw transaction audit rows | Sleeper transactions by week | `season`, `league_id`, `week`, `transaction_id`, `type`, `status`, `created`, `raw` | `transaction_id`, `raw` |
| `transactions_normalized` | Sleeper normalization | Human-readable transaction facts | Sleeper transactions by week | `season`, `league_id`, `week`, `transaction_id`, `type`, `status`, `created_datetime`, `roster_ids_involved`, `manager_team_names_involved`, `adds`, `drops`, `draft_picks_moved`, `waiver_bid`, `faab_moved`, `failure_reason` | `transaction_id` |
| `trades` | Sleeper normalization | Two-team trade ledger | Sleeper trade transactions | `season`, `league_id`, `week`, `transaction_id`, `created_datetime`, `team_a_roster_id`, `team_a_name`, `team_a_players_received`, `team_a_player_ids_received`, `team_a_picks_received`, `team_a_faab_received`, `team_b_roster_id`, `team_b_name`, `team_b_players_received`, `team_b_player_ids_received`, `team_b_picks_received`, `team_b_faab_received`, `raw` | `transaction_id`, `raw`; player ID lists preserve Sleeper identity for each received side |
| `waivers` | Sleeper normalization | Waiver claim ledger | Sleeper waiver transactions | `season`, `league_id`, `week`, `transaction_id`, `roster_id`, `team_name`, `player_added`, `player_added_ids`, `player_dropped`, `player_dropped_ids`, `waiver_bid`, `status`, `failure_reason` | `transaction_id`, `roster_id`; player ID lists preserve Sleeper identity |
| `matchups` | Sleeper normalization | One roster/week outcome receipt with exact opponent and score state | Sleeper `/league/{league_id}/matchups/{week}` | `season`, `league_id`, `week`, `matchup_id`, `roster_id`, `team_name`, `opponent_roster_id`, `opponent_team_name`, `points_for`, `points_against`, `margin`, `result`, `source_trace`, `evidence` | `season` + `league_id` + `week` + `roster_id`; missing scores remain `unplayed`, absent rows remain not recorded |

`teams.team_name` and `display_name` are current Sleeper labels for the exact
`league_id` + `season` + `roster_id` row. They are mutable source data, not
identity keys. A private team profile may add a Front Office label, but a
profile value that matches a known historical Sleeper label for the same
owner/roster lineage follows the current source label (for example, Melkor
Lord of Light -> Lulu's Potatoe's); an intentionally different private label
is preserved separately.

### Canonical External Tables

| Table | Owner | Purpose | Source of truth | Required columns | Trace requirement |
| --- | --- | --- | --- | --- | --- |
| `player_usage_weekly` | External source normalization | Weekly NFL usage/performance context | nflverse player stats | `source`, `season`, `week`, `player_id`, `player_name`, `position`, `team`, `targets`, `carries`, `receptions`, `passing_attempts`, `fantasy_points_ppr`, `source_trace` | `source`, `source_trace` |
| `market_value_sources` | External source normalization | Component-level player market value rows before consensus | DynastyProcess plus user-provided/manual market files when configured | `source`, `source_access_type`, `source_player_id`, `player_id`, `player_name`, `position`, `raw_value`, `normalized_value`, `market_rank`, `value_format`, `source_confidence`, `source_trace`, `checked_at` | `source`, `source_access_type`, `source_confidence`, `source_trace`, `checked_at`; DynastyProcess `value_2qb` is stored in x100 units and must normalize as `raw / 100`; KTC-like data is manual/permissioned only |
| `market_consensus_values` | Deterministic market normalization | Consensus player market value derived from component sources | `market_value_sources` | `player_id`, `player_name`, `position`, `consensus_value`, `source_count`, `disagreement_score`, `best_source`, `confidence`, `source_trace` | source count, disagreement, confidence, and component traces required |
| `player_market_values` | External source compatibility view | Legacy player market values for existing transforms | `market_consensus_values` | `source`, `source_player_id`, `player_id`, `player_name`, `position`, `market_value`, `market_rank`, `value_format`, `source_trace` | `source`, `source_trace`; should be treated as compatibility output, not the only market model |
| `pick_market_values` | External source normalization | Pick market values when source is available | DynastyProcess or configured pick value source | `source`, `pick_label`, `pick_season`, `round`, `market_value`, `source_trace` | `source`, `source_trace`; empty table is valid when source unavailable |
| `source_freshness` | External source normalization | Source status and row-count diagnostics | Refresh process | `source`, `dataset`, `status`, `source_url`, `cache_path`, `checked_at`, `row_count` | rows must explain available, cached, disabled, or unavailable source state |
| `news_events` | News source normalization | Raw news/trending items normalized into rows | RotoWire RSS and Sleeper trending | `source`, `event_id`, `event_type`, `published_at`, `title`, `summary`, `url`, `player_id`, `player_name`, `team`, `position`, `source_trace` | `event_id`, `source`, `source_trace` |
| `player_news_matches` | News source normalization | Match news items to Sleeper player IDs | `news_events` + Sleeper player cache | `event_id`, `source`, `input_player_name`, `player_id`, `matched_player_name`, `match_method`, `match_confidence`, `is_ambiguous`, `source_trace` | match method and confidence required |
| `league_news_impact` | Deterministic news analytics | League- and roster-scoped news impacts | `news_events`, `player_news_matches`, `roster_players`, `teams` | `event_id`, `source`, `published_at`, `player_id`, `player_name`, `league_id`, `season`, `roster_id`, `team_name`, `impact_type`, `evidence`, `risk`, `confidence`, `source_trace` | `league_id`/`season` preserve the Sleeper league boundary when roster IDs repeat; `evidence`, `risk`, `confidence`, `source_trace` required |
| `news_source_freshness` | News source normalization | News source status and row-count diagnostics | Refresh process | `source`, `dataset`, `status`, `source_url`, `cache_path`, `checked_at`, `row_count` | rows must explain cached, refreshed, disabled, or unavailable source state |

News is current-state evidence. `league_news_impact` may fan one current event
out to multiple leagues that own the player, but it must not attach that event to
a completed season's historical roster row. Blank-season legacy rows remain
explicitly unscoped; identified rows are limited to the configured current
season before they reach the reader or writer packets.

Optional user market exports are configured at
`external_sources.market_value_files` in `config/leagues.yml`. Each entry may
be a path or `{path, source, confidence, value_format}` object. Relative paths
are resolved under the configured data root and may include `{season}`. CSVs
must provide `player_name`, `position`, and `market_value` already on the
canonical scale; `sleeper_id`/`player_id`, `market_rank`, `confidence`, and
`source_trace` are optional. The refresh labels these rows
`source_access_type=user_provided`, preserves a `manual_file:` trace, and
includes them as separate consensus components. It never rescales values by
magnitude, scrapes restricted providers, or treats a missing/ambiguous name
bridge as a canonical Sleeper identity.

### Available-Market Horizon Table

`available_player_horizon_scores` is a separate derived table for market-ranked
players who are not rostered in the selected league. It requires a unique
canonical Sleeper identity and a proven current-league roster snapshot before
it can label a player available. It reuses the `horizon_market_v2` columns for
next game, rest of season, dynasty market, five-year career window, and
contender/rebuilder fit, while adding `league_id`, `availability_status`,
`identity_status`, `market_rank`, `market_source_count`, and
`market_disagreement_score`, and `market_source_confidence`. The table is an availability research board, not a
waiver-eligibility or claim receipt; missing projection, schedule, or history
remains unavailable rather than becoming a zero forecast.

When the refresh projection tables are available, candidates are scored inside
that same deterministic projection cohort and candidate rows replace duplicate
projection identities before scoring. Their market percentiles use the full
current market table by position, not only names that survived the selected
league availability filter. This keeps an available player's clock scores
comparable to the refresh's rostered cohort while the league-absence and
waiver-eligibility limitations remain explicit.

### Projection Tables

| Table | Owner | Purpose | Inputs | Required columns | Trace/evidence requirement |
| --- | --- | --- | --- | --- | --- |
| `player_projection_season` | Deterministic projection code | Season-level projected fantasy production | `player_usage_weekly`, `players`, league scoring config, roster ownership | `season`, `player_id`, `player_name`, `position`, `team`, `availability_scope`, `current_availability_status`, `availability_note`, `projected_games`, `projected_passing_yards`, `projected_passing_tds`, `projected_interceptions`, `projected_rushing_yards`, `projected_rushing_tds`, `projected_receptions`, `projected_receiving_yards`, `projected_receiving_tds`, `projected_fantasy_points`, `projected_ppg`, `projection_method`, `projection_confidence`, `source_trace` | `availability_scope`, `current_availability_status`, and `availability_note` are copied from the current Sleeper snapshot when available; `no_current_nfl_team` preserves the historical baseline but qualifies it as conditional on signing, while actionable next-game/rest-of-season lanes remain unavailable. `projection_method`, `projection_confidence`, and `source_trace` are also required |
| `player_projection_weekly` | Deterministic projection code | Weekly projected fantasy allocation | `player_projection_season`, schedule/weekly allocation rules | `season`, `week`, `player_id`, `player_name`, `position`, `team`, `availability_scope`, `current_availability_status`, `availability_note`, `projected_fantasy_points`, `projected_snap_or_usage_note`, `projection_method`, `projection_confidence`, `source_trace` | availability fields preserve the same current-Sleeper boundary as the season row; the weekly allocation is not a usable game forecast when the player has no current NFL team. `projection_method`, `projection_confidence`, and `source_trace` are required |
| `nfl_schedule` | nflverse schedule normalization | Regular-season game identity, opponent, home/away, and scheduled-versus-played status | preserved nflverse `games.csv` | `season`, `week`, `game_id`, `game_type`, `gameday`, `away_team`, `home_team`, `schedule_status`, `source_trace` | missing or unmatched teams remain explicitly unavailable; this table is the only source for future NFL opponent and bye context |
| `nfl_team_defense_factors` | Deterministic matchup code | Historical position-specific PPR points allowed per game, relative matchup factor, and out-of-sample calibration receipt | normalized nflverse player usage/game IDs | `team`, `position`, `games_sample`, `fantasy_points_allowed_per_game`, `league_position_average`, `matchup_factor`, `confidence`, `validation_seasons`, `validation_games`, `validation_mae`, `validation_baseline_mae`, `validation_mae_delta`, `validation_direction_accuracy`, `validation_status`, `source_trace` | historical context is clamped and sample-counted; validation uses later seasons than the factor evidence and is descriptive, not a full defensive projection or a claim about future game script |
| `player_horizon_market_scores` | Deterministic horizon market code (`horizon_market_v2`) | Separate next-game, rest-of-season, dynasty-market, and five-year career-window lenses plus contender/rebuilder fit | `player_projection_season`, `player_projection_weekly`, `player_signal_scores`, `roster_players`, `player_usage_weekly`, `nfl_schedule`, `nfl_team_defense_factors`, current refresh week | `season`, `league_id`, `as_of_week`, `horizon_model_version`, `horizon_score_basis`, `next_game_week`, `player_id`, `player_name`, `position`, `age`, `roster_id`, `team_name`, `availability_scope`, `current_availability_status`, `injury_status`, `availability_note`, `projection_ppg`, `projection_confidence`, `market_value`, `market_percentile`, `next_game_baseline_points`, `next_game_expected_points`, `next_game_market_score`, `next_game_minus_market_delta`, `next_game_status`, `next_game_opponent`, `next_game_home_away`, `next_game_schedule_status`, `next_game_matchup_factor`, `next_game_matchup_validation_status`, `next_game_matchup_validation_games`, `next_game_matchup_validation_mae_delta`, `next_game_matchup_adjustment_status`, `rest_of_season_weeks`, `rest_of_season_games`, `rest_of_season_bye_weeks`, `rest_of_season_baseline_points`, `rest_of_season_ppg`, `rest_of_season_market_score`, `rest_of_season_minus_market_delta`, `rest_of_season_minus_next_game_delta`, `rest_of_season_status`, `schedule_status`, `dynasty_market_score`, `dynasty_minus_market_delta`, `dynasty_minus_rest_of_season_delta`, `dynasty_status`, `career_projection_years`, `career_projection_points`, `career_projection_ppg`, `career_projection_score`, `career_minus_market_delta`, `career_minus_dynasty_delta`, `career_projection_status`, `career_projection_basis`, `career_history_join_method`, `career_history_source_player_id`, `career_history_status`, `career_history_seasons`, `career_history_games`, `career_history_ppg`, `career_history_latest_season`, `contender_fit_score`, `rebuilder_fit_score`, `fit_coverage`, `fit_basis`, `rebuilder_contender_spread`, `value_lane`, `evidence`, `risk`, `confidence`, `source_trace` | each row is scoped to the selected Sleeper league before roster identity or mutable team labels are attached; next-game values use schedule/opponent and historical defensive context when available, with the holdout calibration receipt visible; otherwise remain opponent-neutral; rest-of-season counts scheduled games and byes when schedule coverage is present; dynasty is an external-market-plus-timeline lens, while the career fields are a history-anchored internal five-year age-curve scenario when a unique source join exists, never a lifetime or guaranteed career-points forecast; `availability_scope` identifies whether injury fields come from the current Sleeper player snapshot or are intentionally unavailable for historical rows; `current_availability_status=no_current_nfl_team` withholds actionable next-game and rest-of-season scores while preserving a conditional historical baseline and lowers confidence; every horizon and fit score is a position-relative 0-100 percentile, not a dollar market value or cross-position price ranking; `market_value` is the canonical cross-position price anchor and `market_percentile` is its position-relative rank; the four clock-versus-market deltas are same-position percentile repricing leads and remain unavailable when either endpoint is unavailable; the three adjacent transition deltas are later-window minus earlier-window percentiles and remain unavailable when either component is unavailable; `fit_coverage` reports how many of the four clock scores are present, and missing components are omitted with remaining fit weights renormalized; ambiguous or absent career history remains explicit and falls back to the age-only scenario; the model version and fit-basis receipt make weighting changes explicit; all statuses and evidence/risk/confidence/source trace are required |
| `horizon_snapshot_history` | Append-only deterministic belief log | Dated horizon score snapshots used to evaluate next-game and rest-of-season rank evidence later | `player_horizon_market_scores`, refresh scope | `snapshot_at`, `snapshot_scope`, `season`, `league_id`, `as_of_week`, `player_id`, `player_name`, `position`, `horizon_model_version`, `market_value`, `market_percentile`, four horizon scores, four clock-versus-market deltas, contender/rebuilder fit scores, `fit_coverage`, `value_lane`, `source_trace` | keyed idempotently by scope + season + as-of week + player + position + model; `league_id` is retained as a row-level identity receipt and older rows are backfilled from their existing `league:<id>:` scope key; a later week creates a new observation; this preserves deterministic beliefs only and never stores generated prose or overwrites the current horizon table |
| `horizon_score_accuracy` | Deterministic outcome evaluation | Descriptive rank evidence for next-game and rest-of-season horizon scores once later realized usage exists | `horizon_snapshot_history`, `player_usage_weekly` | `horizon_model_version`, `horizon`, `score_field`, `position`, `outcome`, sample counts, rank correlation, cohort/top-quartile outcomes, lift, `evaluation_status`, `confidence`, `evidence`, `source_trace` | joins Sleeper-named snapshots to nflverse usage by normalized name + position and withholds ambiguous joins; missing future rows are not treated as zero; `descriptive_evaluation` is not a calibrated probability; dynasty, career, and contender/rebuilder fit remain ungraded until their appropriate longitudinal labels exist |
| `horizon_market_movements` | Deterministic longitudinal receipt | Compare the current four-window horizon row with the latest earlier exact-scope snapshot so the reader can see what moved | `horizon_snapshot_history`, current `player_horizon_market_scores` | exact scope/season/player/position/model, prior/current snapshot and week, market value and percentile deltas, four clock score deltas, contender/rebuilder fit deltas, spread delta, value-lane change, largest clock movement, `movement_status`, `evidence`, `source_trace` | only later snapshots in the same league/season/roster scope are compared; same-week reruns do not create a movement; missing endpoints remain unavailable; deltas describe observed model/market movement and are not a new valuation score or proof of mispricing; first-run output may be empty |
The horizon table also carries the market-quality receipt fields
`market_source_count`, `market_disagreement_score`, and
`market_source_confidence`. They describe the evidence behind
`market_percentile` without changing the score formula: a clock-versus-market
lead is less actionable when the market is thin or internally divided. Blank
receipt fields mean the horizon builder did not receive a canonical consensus
row; they are unavailable, not zero.
The validation gate accepts only a complete three-field receipt or an entirely
unavailable receipt; partial, malformed, or unsupported values fail closed.

The receipt is sourced from the canonical `market_consensus_values` input,
which is itself built from `market_value_sources`. The horizon builder may
bridge a provider row by a unique normalized player-name plus position when
the provider has no Sleeper ID; duplicate or unresolved bridges remain blank
and carry an explicit risk. The append-only `horizon_snapshot_history`
preserves these same fields so later evaluation can distinguish a change in
the price anchor from a change in the horizon model.

The append-only `horizon_snapshot_history` table preserves the same three market
receipt fields so a later calibration or audit can distinguish a change in the
market evidence from a change in the horizon model.

| `projection_source_freshness` | Projection refresh process | Projection source status and diagnostics | Refresh process | `source`, `dataset`, `status`, `source_url`, `cache_path`, `checked_at`, `row_count` | rows must explain available, cached, disabled, or unavailable projection inputs |
| `fantasy_nerds_projection_source` | External source refresh | Raw Fantasy Nerds weekly projection rows (paid, API-key gated) | Fantasy Nerds API | `source`, `fn_player_id`, `player_name`, `normalized_name`, `position`, `team`, `projected_fantasy_points`, `source_confidence`, `source_trace`, `checked_at` | disabled without `FANTASY_NERDS_API_KEY`; empty when unset, never errors |
| `projection_source_components` | Deterministic projection code | Pre-blend per-(player, source) projection detail | nflverse per-game history, `fantasy_nerds_projection_source` | `season`, `player_id`, `player_name`, `position`, `team`, `roster_id`, `team_name`, `availability_scope`, `current_availability_status`, `availability_note`, `source`, `projected_fantasy_points`, `projected_ppg`, `projected_games`, `source_confidence`, `source_trace`, `projection_method`, `detail_stats_json`, `checked_at` | one row per contributing source; availability fields are the exact current Sleeper decision boundary carried into every component before blending; feeds `player_projection_season` consensus, never consumed directly by signal code |
| `source_accuracy_scores` | Deterministic accuracy grading | Per-source, per-position historical accuracy grade | `projection_source_components` history, nflverse actuals | `source`, `position`, `season`, `mean_absolute_error`, `sample_size`, `accuracy_confidence`, `source_trace`, `checked_at` | `mean_absolute_error` is diagnostic-only (numeric alongside categorical `accuracy_confidence`, same precedent as `market_consensus_values.disagreement_score`); feeds consensus weighting, never overwritten with a bare "current weight" |

`player_projection_season` is now a **consensus** of `projection_source_components` (weighted by `source_accuracy_scores` once history exists, equal-weighted at cold start) rather than a single-source read. Its availability fields are carried through the blend so every consumer can distinguish a usable current baseline from historical evidence that is conditional on a signing or active return; `player_signal_scores` and everything downstream retain their existing scoring boundary. `data/processed/projection_snapshot_history.csv` is a deliberate, documented exception to the CSV-overwrite-every-refresh rule: an append-only, dated-key-idempotent log (season, week, source, player_id) of live-source projections, needed to grade sources (like Fantasy Nerds) that have no retrospective actuals to backtest against. This advances the `projection_snapshots` pattern from the Sprint Plan's Sprint 10 (Feedback And Market Memory) in minimal form.

The horizon table is deliberately not a replacement for `projected_ppg`. That field remains a season production baseline. The next-game lane may adjust expected points for a current availability flag because it is the immediate decision window; the rest-of-season baseline is not recovery-adjusted when no recovery timeline is modeled. A current Sleeper row with no NFL team is a stronger boundary: historical PPG remains visible as conditional evidence, but actionable next-game and rest-of-season scores are withheld until a current team/role exists. The four-window rows make the consumption boundary explicit: a player can be a contender edge because of immediate/season utility while simultaneously being a rebuilder edge because of dynasty market and timeline value. Every `*_score` and fit score is a position-relative percentile within the current season cohort; it must not be read as a dollar value or used to compare prices across positions. Use `market_value` and `market_percentile` for that cross-position price question. Writers may explain the spread and clock-versus-market disagreement; they may not collapse it into one universal ranking.

The four `*_minus_market_delta` fields are same-position repricing leads: each clock percentile minus the player's same-position `market_percentile`. They are not dollar gaps, and a positive delta is not proof that the player is mispriced. They let a writer explain which decision window is ahead of or behind the current market view while the reader still sees the canonical cross-position `market_value` anchor. Missing clock or market evidence leaves the corresponding delta unavailable. The four-window publication uses these fields to surface a market-versus-clock discovery queue without creating a second valuation model.

`horizon_snapshot_history` is the feedback seam for this comparison. Each refresh records the deterministic scores with an idempotent dated key, and `horizon_score_accuracy` evaluates only observed next-game and active rest-of-season PPR outcomes when the later usage rows exist. An absent usage row is not silently scored as zero because it may be a bye or a source gap. The resulting rank correlation and top-quartile lift are descriptive evaluation receipts, not probabilities or proof that the dynasty/career lenses are calibrated. Those longer lenses need multi-season realized labels before their weights can be tuned from outcomes.

`horizon_market_movements` is the reader-facing longitudinal seam over that same
history. It compares the current row with the latest earlier snapshot in the
same exact league, season, roster scope, position, and model version. It is
therefore a change receipt, not a fifth market score: a changed row tells the
writer that a clock, price anchor, fit, spread, or lane moved, while the source
rows remain the evidence for why. A first run, a same-week rerun, or a missing
prior endpoint produces no fabricated movement.

The horizon contract's `next_game_matchup_adjustment_status` is `applied`
only when the defensive factor has a holdout status of
`validated_improvement`. Limited, unavailable, or
`validated_no_improvement` factors remain descriptive context and leave the
weekly points at the unadjusted baseline.

The horizon percentiles are currently structural comparisons over the refresh
cohort, not outcome-calibrated forecasts. Dated horizon snapshots and realized
weekly or multi-year outcomes are required before the application may describe
any horizon score as calibrated predictive performance. Until that evidence
exists, the browser and writers must retain the model version, score basis,
confidence, and source/risk receipt.

`strategy_profile.horizon_fit_weights` is optional, private league/team
configuration. It may provide complete `contender` and/or `rebuilder` maps
with the four keys `next_game`, `rest_of_season`, `dynasty`, and
`career_window`; values are non-negative and normalized before use, so either
fractions or percentage-like numbers are accepted. A malformed lane, unknown
key, missing component, non-finite value, or all-zero lane falls back to the
documented default and is recorded as `invalid_custom_fallback` in `fit_basis`.
This changes only the personalized fit lens; it never changes the canonical
four horizon scores, the market value anchor, or the writer evidence contract.

### Derived Analytics Tables

| Table | Owner | Purpose | Inputs | Required columns | Trace/evidence requirement |
| --- | --- | --- | --- | --- | --- |
| `manager_profiles` | Deterministic analytics | Summarize manager trade/waiver tendencies across current and discovered historical Sleeper leagues | `teams`, `trades`, `waivers`, `roster_players` | `owner_id`, `roster_id`, `display_name`, `team_name`, `seasons_covered`, `roster_ids_by_season`, `team_names_by_season`, `total_trades`, `trades_by_season`, `players_acquired`, `players_sold`, `picks_acquired`, `picks_sold`, `future_1sts_acquired`, `future_1sts_sold`, `future_2nds_acquired`, `future_2nds_sold`, `faab_spent_on_waivers`, `number_of_waiver_claims`, `average_waiver_bid`, `max_waiver_bid`, `most_common_transaction_partners`, `qb_count`, `rb_count`, `pass_catcher_count`, `contender_rebuilder_indicator`, `notes` | owner ID is cross-season identity when available; roster ID remains current-season label |
| `manager_season_history` | Deterministic profile intelligence | Per-manager, per-season activity, roster-shape, and observed outcome ledger for historical dossiers | `teams`, `trades`, `waivers`, `roster_players`, `matchups` | `owner_id`, `season`, `roster_id`, `team_name`, `trades`, `waiver_claims`, `faab_spent`, `transaction_count`, `first_transaction_week`, `last_transaction_week`, `peak_transaction_week`, `active_weeks`, `trade_weeks`, `waiver_weeks`, `players_acquired`, `players_sold`, `picks_acquired`, `picks_sold`, `trade_partners`, `roster_player_count`, `qb_count`, `rb_count`, `pass_catcher_count`, `matchup_weeks`, `played_weeks`, `wins`, `losses`, `ties`, `points_for`, `points_against`, `point_diff`, `win_rate`, `outcome_status`, `source_trace`, `evidence` | `season` + exact `roster_id` identify the historical slice; matchup rows preserve exact opponent/score state; missing endpoint or offseason rows remain `not_recorded`, not 0-0; evidence and source trace required; quiet seasons remain represented |
| `league_standings` | Deterministic outcome analytics | League-wide standings and matchup coverage for the selected season | `matchups`, `teams` | `season`, `league_id`, `roster_id`, `team_name`, `matchup_rows`, `played`, `wins`, `losses`, `ties`, `points_for`, `points_against`, `point_diff`, `win_rate`, `record`, `outcome_status`, `source_trace`, `evidence` | exact `season` + `league_id` + `roster_id`; scores and records come only from matchup rows; teams with no scored rows remain `not_recorded` and do not receive a fabricated 0-0 |
| `pick_ownership` | Deterministic analytics | Human-readable traded pick ownership | `traded_picks`, `teams` | `original_roster_id`, `original_team`, `pick_season`, `round`, `current_owner_roster_id`, `current_owner`, `previous_owner_roster_id`, `previous_owner`, `is_my_original_pick`, `is_currently_owned_by_me`, `i_currently_own_it` | original/current/previous roster IDs |
| `team_asset_inventory` | Deterministic economics | Unified player/pick asset ledger | roster, pick, market value tables | `roster_id`, `team_name`, `asset_type`, `asset_id`, `asset_name`, `position`, `age`, `market_value`, `liquidity_tier`, `timeline_fit`, `source_trace` | `source_trace` required; proxy values must be labeled |
| `manager_event_log` | Deterministic analytics | Traceable manager event feed | `trades`, `waivers`, `teams` | `season`, `league_id`, `owner_id`, `event_type`, `week`, `created_datetime`, `transaction_id`, `roster_id`, `team_name`, `counterparty`, `players_in`, `picks_in`, `faab_in`, `players_out`, `picks_out`, `faab_out`, `evidence` | `season` + `league_id` + `transaction_id` + `roster_id`, `evidence`; owner and league are required to prevent repeated roster numbers from mixing histories |
| `team_needs_matrix` | Deterministic economics | Team roster-shape and pick-capital needs | `teams`, `roster_players`, `pick_ownership` | `roster_id`, `team_name`, `qb_count`, `rb_count`, `wr_count`, `te_count`, `pass_catcher_count`, `future_firsts_owned`, `need_qb`, `need_rb`, `need_pass_catcher`, `need_picks`, `team_shape` | counts are derived from canonical tables |
| `manager_behavior_signals` | Deterministic analytics | Scored manager behavior labels | `teams`, `trades`, `waivers`, `manager_profiles`, `roster_players` | `roster_id`, `team_name`, `trade_activity_score`, `pick_buyer_score`, `pick_seller_score`, `faab_aggression_score`, `waiver_activity_score`, `rb_appetite_score`, `pass_catcher_appetite_score`, `plain_language_label`, `evidence` | `evidence` required |
| `manager_valuation_profiles` | Deterministic revealed-preference model | Estimate manager asset-type preferences from observed history | `teams`, `manager_profiles`, `roster_players` | `owner_id`, `roster_id`, `team_name`, `asset_type`, `position_group`, `preference_score`, `evidence_count`, `recency_weighted_score`, `confidence`, `label`, `evidence` | `evidence`, sample size, and confidence required; language must remain estimate-based |
| `manager_transaction_preferences` | Deterministic transaction-lane model | Preserve identity-resolved player acquisitions/disposals by position and attach current four-window context where the historical player ID is present in the current horizon table | `manager_profiles`, `player_transaction_history`, `players`, `roster_players`, `player_horizon_market_scores` | `owner_id`, `roster_id`, `team_name`, `position_group`, `trade_acquired_count`, `waiver_acquired_count`, `draft_acquired_count`, `trade_sold_count`, `waiver_sold_count`, `acquired_count`, `sold_count`, `net_acquired_count`, `unique_acquired_players`, `unique_sold_players`, current-roster overlap counts, observed seasons, acquired/sold horizon scores and deltas, horizon coverage, `transaction_read`, `history_status`, `confidence`, `evidence`, `source_trace` | exact `season` + `roster_id` lineage maps events to stable `owner_id`; unresolved player identity remains in `UNKNOWN` rather than being guessed; horizon scores are current context for historically moved players, never historical prices or proof of intent; insufficient rows remain sparse/low confidence |
| `counterparty_asset_interest` | Deterministic counterparty audience model | Find possible audiences for active-roster player assets using observed manager position lanes, current need, and horizon fit | `team_asset_inventory`, `manager_transaction_preferences`, `team_needs_matrix`, `player_horizon_market_scores` | `active_roster_id`, `active_team`, `asset_id`, `asset_name`, `asset_type`, `position`, `market_value`, `target_roster_id`, `target_team`, `target_team_lens`, transaction lane counts/status, `target_need`, `target_need_fit_score`, target/active horizon fit and edge, four horizon scores, four clock-minus-market deltas, transition deltas, `horizon_market_disagreement_window`, `horizon_market_disagreement_delta`, `horizon_market_disagreement_read`, `observed_acquisition_signal`, `conversation_fit_score`, `conversation_fit_label`, `evidence`, `risk`, `confidence`, `source_trace` | only active player assets and identity-resolved historical lanes are emitted; `conversation_fit_score` is a research-priority signal, not market value, intent, willingness, or predicted acceptance; sparse lanes and missing horizon context remain explicit; clock-to-market fields are copied from the canonical horizon row and are discovery context, not a new price; market value remains the cross-position price anchor |
| `manager_profile_tags` | Deterministic profile intelligence | Evidence-backed manager tendency tags | `manager_profiles`, `manager_event_log`, `manager_valuation_profiles`, `team_needs_matrix`, `pick_ownership` | `entity_id`, `entity_name`, `tag`, `score`, `confidence`, `evidence`, `risk`, `source_trace`, `generated_at` | tags are deterministic estimates; evidence/risk/confidence/source_trace required |
| `manager_cycle_profiles` | Deterministic profile intelligence | Manager dynasty-cycle and posture summary | `manager_profiles`, `manager_event_log`, `team_needs_matrix`, `pick_ownership` | `owner_id`, `roster_id`, `team_name`, `dynasty_cycle`, `trade_temperature`, `pick_posture`, `waiver_posture`, `likely_needs`, `likely_sells`, `confidence`, `evidence` | cycle labels are estimates from observed behavior, not known intent |
| `liquidity_scores` | Deterministic economics | Asset liquidity estimate | `team_asset_inventory`, `team_needs_matrix` | `roster_id`, `team_name`, `asset_type`, `asset_name`, `position`, `market_value`, `liquidity_score`, `liquidity_tier`, `demand_signal`, `source_trace` | `source_trace` required |
| `asset_market_gaps` | Deterministic economics | Buy/sell/target gap signals | inventory, needs, behavior, strategy config | `target_roster_id`, `target_team`, `asset_type`, `asset_name`, `position`, `market_value`, `market_gap_score`, `opportunity_type`, `timeline_fit`, `evidence`, `risk`, `confidence`, `source_trace` | `evidence`, `risk`, `confidence`, `source_trace` required |
| `opportunity_board` | Deterministic economics | Read-only action preview | `asset_market_gaps`, behavior, strategy config | `action_type`, `target_team`, `asset_in`, `asset_out`, `manager_signal`, `evidence`, `risk`, `confidence`, `source_trace` | `evidence`, `risk`, `confidence`, `source_trace` required |
| `today_priority_board` | Deterministic signal code | One deduplicated, ranked list merging `action_recommendations`, `league_news_impact`, `pick_ownership`, and `manager_behavior_signals` for Today's Board | those four tables | `item_type`, `item_type_label`, `entity_type`, `entity_id`, `entity_name`, `roster_id`, `team_name`, `priority_score`, `why`, `evidence`, `risk`, `confidence`, `source_trace` | deduplicated by `(entity_type, entity_id)`; `priority_score` is a percentile rank across the combined candidate pool, not a hand-tuned cross-type weight |
| `refresh_metadata` | Refresh process | One-row refresh diagnostics | config + refresh run | `generated_at`, `current_season`, `configured_league_ids`, `transaction_week_start`, `transaction_week_end`, `matchups_status`, `matchup_rows`, `source_scope`, `raw_cache_root`, `raw_external_cache_root`, `browser_is_primary_surface`, `recommendation_packets_status` | must describe generated source scope and whether optional matchup evidence was available |

### Transform Signal Tables

| Table | Owner | Purpose | Inputs | Required columns | Trace/evidence requirement |
| --- | --- | --- | --- | --- | --- |
| `player_signal_scores` | Deterministic signal code | Unified player target/sell/watch scoring | projections, market values, roster ownership, news impact, manager behavior, opportunity scores | `player_id`, `player_name`, `position`, `roster_id`, `team_name`, `projection_edge_score`, `market_gap_score`, `timeline_fit_score`, `breakout_score`, `sell_score`, `opportunity_score`, `xfp_regression_score`, `role_trend_score`, `fragility_score`, `signal_label`, `projection_percentile`, `market_percentile`, `market_gap_status`, `evidence`, `risk`, `confidence`, `source_trace` | `market_gap_score` is signed position-relative projection percentile minus external market percentile; status distinguishes aligned/disagreement, missing, proxy, and sparse cohorts; missing/proxy markets are not calibrated as observed disagreement; single-source market evidence downgrades confidence; `evidence`, `risk`, `confidence`, `source_trace` required |
| `player_opportunity_scores` | `src/opportunity.py` (Sprint 18) | Opportunity-based 0-100 scores from nflverse weekly usage, percentile-ranked within position | cached nflverse weekly `player_stats`, roster players (joined by normalized name) | `player_id`, `player_name`, `position`, `roster_id`, `team_name`, `games_sample`, `opportunity_score`, `production_score`, `xfp_regression_score`, `role_trend_score`, `fragility_score`, `opportunity_evidence`, `source_trace` | opportunity/production are validated ROS predictors (backtest AUC ~0.80/0.85); xfp_regression/role_trend/fragility are flags only, never rankers |
| `breakout_candidates` | Deterministic signal code | Ranked breakout/target candidates | `player_signal_scores` | `player_id`, `player_name`, `position`, `current_availability_status`, `current_team_name`, `breakout_score`, `projection_edge`, `market_value`, `evidence`, `risk`, `confidence`, `source_trace` | derived from signal scores; `no_current_nfl_team` rows are excluded from the actionable queue |
| `sell_candidates` | Deterministic signal code | Ranked sell/trade-away candidates | `player_signal_scores` | `player_id`, `player_name`, `position`, `current_availability_status`, `current_team_name`, `sell_score`, `projection_risk`, `market_value`, `evidence`, `risk`, `confidence`, `source_trace` | derived from signal scores; `no_current_nfl_team` rows are excluded from the actionable queue and remain conditional context in the player signal/horizon tables |
| `projection_market_gaps` | Deterministic signal code | Calibrated projection-vs-market disagreement leads | projections, market values | `player_id`, `player_name`, `position`, `current_availability_status`, `projected_fantasy_points`, `projected_ppg`, `market_value`, `projection_percentile`, `market_percentile`, `market_gap_status`, `gap_score`, `gap_label`, `evidence`, `risk`, `confidence`, `source_trace` | percentiles and status show the position cohort behind the signed gap; `no_current_nfl_team` retains a zeroed, `availability_conditioned_gap` context row rather than an actionable ranking; projection and market source traces required |
| `news_market_edges` | Deterministic signal code | Current league news catalysts paired with a meaningful market or sell-pressure gap | `league_news_impact`, `player_signal_scores` | `player_id`, `player_name`, `position`, `roster_id`, `league_id`, `season`, `team_name`, `news_direction`, `edge_type`, `news_impact`, `news_event_count`, `market_value`, `projected_ppg`, `market_gap_score`, `sell_score`, `news_market_edge_score`, `evidence`, `risk`, `confidence`, `source_trace` | fail-closed to the selected league/season when identified news rows exist; a row is a research lead, never proof of mispricing; event evidence and source trace required |
| `team_fit_scores` | Deterministic signal code | Fit of player assets by selected team timeline and needs | projections, roster ownership, team needs, strategy config | `roster_id`, `team_name`, `player_id`, `player_name`, `position`, `timeline_fit_score`, `need_fit_score`, `liquidity_fit_score`, `fit_label`, `evidence`, `risk`, `confidence`, `source_trace` | works for any selected roster_id |
| `counterparty_trade_edges` | Deterministic counterparty model | Estimate where our projection/market view may diverge from current owner preference, then expose the target and active team's time-horizon fit | `player_signal_scores`, `manager_valuation_profiles`, `team_needs_matrix`, `player_horizon_market_scores`, strategy config | `target_roster_id`, `target_team`, `player_id`, `player_name`, `position`, `target_team_lens`, `target_horizon_fit_score`, `active_horizon_fit_score`, `horizon_fit_edge`, `horizon_fit_read`, `horizon_fit_basis`, `horizon_model_version`, four horizon scores, four clock-minus-market deltas, transition deltas, `horizon_market_disagreement_window`, `horizon_market_disagreement_delta`, `horizon_market_disagreement_read`, `our_value_score`, `market_consensus_value`, `estimated_owner_value_score`, `trade_edge_score`, `edge_type`, `evidence`, `risk`, `confidence`, `source_trace` | must say estimate, include evidence/risk/confidence, and never imply a trade was sent or accepted; horizon fit and clock-to-market disagreement are separate research lenses, not a trade price or cross-position score; the original `trade_edge_score` remains unchanged |
| `player_dossiers` | Deterministic profile intelligence | Player profile join across ownership, availability, market, projection, news, signal, and league history | `roster_players`, `market_consensus_values`, `player_projection_season`, `league_news_impact`, `player_signal_scores`, `player_transaction_history` | `player_id`, `player_name`, `position`, `age`, `roster_id`, `team_name`, `roster_status`, `availability_scope`, `current_availability_status`, `injury_status`, `injury_body_part`, `availability_note`, `market_value`, `projected_fantasy_points`, `projected_ppg`, `projection_confidence`, `signal_label`, `breakout_score`, `sell_score`, `news_impact`, `transaction_count`, `last_transaction`, `source_trace` | factual profile join; no analyst prose; `availability_scope` preserves whether the injury fields came from the current Sleeper player snapshot or are intentionally unavailable for historical rows; `current_availability_status` is the shared decision-layer classification from the current Sleeper row; `projected_ppg` is a baseline production estimate and `availability_note` must remain visible when an injury flag exists |
| `player_transaction_history` | Deterministic profile intelligence | League-specific player transaction history with acquired/sold direction | `trades`, `waivers`, `draft_picks`, `roster_players` | `player_id`, `identity_method`, `player_name`, `event_type`, `season`, `week`, `created_datetime`, `roster_id`, `team_name`, `counterparty`, `direction`, `evidence`, `source_trace` | source IDs are preferred; name fallback must be labeled `normalized_name`, `ambiguous_name`, or `unmatched_name`; transaction evidence and source table trace required |
| `player_profile_tags` | Deterministic profile intelligence | Evidence-backed player archetype tags | `player_dossiers`, `player_signal_scores`, `league_news_impact` | `entity_id`, `entity_name`, `tag`, `score`, `confidence`, `evidence`, `risk`, `source_trace`, `generated_at` | tags are deterministic prompts for research, not guarantees |

### Team construction presentation contract

Team entity pages must use the current-season `roster_players` rows scoped by
exact `roster_id`, and must use `team_asset_inventory` for aggregate economic
values. `player_dossiers` remains the source for projection coverage and
player-level signal joins. The reader must show market-row coverage and count
`internal_proxy_player_value` rows separately; a proxy value is useful for
ranking but is not equivalent to an externally sourced market observation.
The market total shown in the construction panel must therefore reconcile to
the manager dossier's inventory total, while missing inventory rows remain
unavailable rather than falling back to a different roster or table.

Player entity pages follow the same boundary: for a rostered player, market
value is joined by exact `owner roster_id + asset_id` from
`team_asset_inventory`. The page labels the ledger/proxy source and fails to
an unavailable market value when that scoped asset row is missing. A profile
market value may be shown only for an unrostered player, where no owned asset
ledger row exists.

The deterministic signal and profile pipelines use the same precedence:
external market values win, and missing player values may be filled from the
exact player asset ledger only as `internal_proxy_player_value`. Downstream
rows must carry that trace and lower confidence/risk language; they may not
silently turn a proxy into an external market observation.

## Presentation Artifacts

`app_bundle.json.dataRoomDelta` is a deterministic reader receipt, not a
strategy or editorial artifact. It compares the current `league_news_impact`,
`trades`, and `waivers` tables with the prior durable reader bundle by their
source event IDs. A complete prior scope yields `status=verified`, per-table
added/updated/removed counts, and bounded added-event views. A first build or
incomplete prior scope must yield `status=not_available` with a visible reason;
the current event pulse remains useful but must not be described as historical
change. This receipt is not allowed to infer importance, intent, or a manager
decision from row presence alone.

Team entity pages may present a bounded construction snapshot from the exact
current-season `roster_players` rows for the selected `roster_id`, joined to
`player_dossiers`, `team_needs_matrix`, and roster-scoped
`action_recommendations`. Position mix, market/projection coverage, need
lanes, and action mix are presentation aggregates with an evidence drawer;
they are not a new valuation model or a lineup recommendation. A missing join
must remain `n/a` or explicitly unavailable rather than being filled from a
display-name or another roster.

| Artifact | Owner | Purpose | Rule |
| --- | --- | --- | --- |
| `data/site/index.html` | Browser generation code | Primary browser workflow | Presentation only; reads processed tables |
| `data/reports/weekly_hinkie_report.md` | Report generation code | Markdown strategy report | Presentation only; strategy overlay is allowed |
| `data/processed/sleeper_dynasty.sqlite` | Refresh process | SQLite mirror of processed CSVs | Generated artifact; tables replaced on refresh |
| `action_recommendations` | Deterministic signal code | Consumer-facing action labels from calibrated signal rows | Derived table; must include why, risk, confidence, evidence, and source trace |
`player_signal_scores` also carries `current_availability_status` from the
current Sleeper roster snapshot. A `no_current_nfl_team` row is deliberately
reduced to a `conditional_watch` action: its historical production can support
research, but it cannot create a current buy, sell, or start prompt without a
confirmed team and role.
| `data/analysis/analysis_context_packets.json` | Analysis layer | Machine-readable context packets for analyst generation | Interpretation input only; built from processed tables |
| `data/analysis/target_theses.json` | Codex analyst layer | Explained target theses from signal outputs | Interpretation only; must cite signal/projection evidence |
| `data/analysis/sell_theses.json` | Codex analyst layer | Explained sell theses from signal outputs | Interpretation only; must cite signal/projection evidence |
| `data/analysis/trade_theses.json` | Codex analyst layer | Manager-aware trade thesis packets | Interpretation only; no transaction execution or outbound messaging; distinguish target-owned assets from selected-roster `offer_candidates`, which must carry observed valuation-lane evidence and must not imply current intent |
| `data/analysis/daily_gm_brief.md` | Codex analyst layer | Readable active-team analyst brief | Presentation and interpretation only |
| `data/analysis/manager_dossiers.md` | Codex analyst layer | Plain-language manager behavior summaries | Must be grounded in manager behavior/event tables |
| `data/analysis/manager_dossiers.json` | Codex analyst layer | Machine-readable manager dossier items | Interpretation only; must cite manager profile tags and cycle evidence; `transaction_timeline` is a bounded owner-linked projection of `manager_event_log`, not an inferred motive; historical season rows follow stable Sleeper `owner_id` across roster-ID changes and current assets remain exact-roster scoped; `trade_fit_evaluation.fit_alignment` compares each current fit to a historical lane or emits `no_direct_lane`; `transaction_profile` projects identity-resolved acquisition/disposal lanes and current horizon context without claiming historical prices or intent; `trajectory` compares the latest observed season window with the prior window and must remain descriptive, scoped, and explicit when history is insufficient; `outcome_summary.scored_matchups` is the scored denominator, while scheduled matchup rows remain separately labeled |
| `data/analysis/player_dossiers.json` | Codex analyst layer | Machine-readable player dossier items with the canonical four-window context | Interpretation only; must cite player dossier/tag evidence and preserve the separate position-relative horizon scores, fit coverage, and model receipt |
| `data/analysis/news_impact_brief.md` | Codex analyst layer | Readable summary of imported news impact rows | Must not become canonical news truth |
| `data/analysis/analysis_validation.json` | Analysis layer | Artifact validation status and guardrail errors | Generated validation artifact |

The `team_report` article scope is the Topline Tony newsroom packet. In
addition to selected-roster player rows, it may carry league-scoped `news`,
`matchup`, and `transaction` evidence rows from the current season. Those
rows are context for interpretation, never canonical facts invented by the
writer; the scope must filter by the exact `league_id` and `roster_id` where
the source table supports those keys, and missing context remains absent.

## Source Ownership

- Sleeper owns league identity, rosters, users, transactions, drafts, traded picks, and player metadata.
- nflverse owns NFL usage/performance reference data when available.
- DynastyProcess owns imported market value reference data when available.
- User-provided market files may contribute to `market_value_sources` only as `source_access_type=user_provided` or another explicit non-scraped access type.
- KeepTradeCut-like sentiment is manual/permissioned only unless official access changes; do not automate scraping, hidden API calls, or paywall/restriction bypass.
- RotoWire RSS owns attributed player-news rows imported through its published RSS feed.
- Sleeper trending owns public add/drop trend rows imported through the Sleeper trending endpoint.
- Projection code owns deterministic projected stats and fantasy point calculations.
- Fantasy Nerds owns paid, API-key-gated weekly fantasy point projections when explicitly configured by the user (Source Policy: "Paid/API-key sources explicitly configured by the user"). Disabled, not erroring, when the key is absent.
- Source accuracy grading code owns historical mean-absolute-error and confidence per (source, position); it is a deterministic input to consensus weighting, never a stored opinion about which source is "best" beyond what the numbers show.
- Transform code owns breakout/sell/watch labels and scores.
- Codex and deterministic analysis templates own explanation of transform outputs only, not projection facts or signal scores. The provider boundary in `src/llm.py` supports OpenAI and Anthropic structured calls; the current production default is OpenAI `gpt-5.6-luna` behind `OPENAI_API_KEY`, while Anthropic remains an explicit compatibility option. Calls are paid, explicit, user-triggered, fail loud on provider errors, and only produce validated interpretation artifacts, never facts.
- Internal proxy values are continuity fallbacks only.
- Config owns selected current team, strategy profile, tracked pick priorities, and source toggles.
- Processed tables own normalized analysis state.
- Browser and markdown own presentation only.

## Profile Tag Taxonomy

Manager profile tags are limited to: `rebuilder`, `contender`, `pick accumulator`, `pick spender`, `waiver aggressor`, `trade grinder`, `depth churner`, `veteran buyer`, `pass-catcher collector`, and `low-signal manager`.

Player profile tags are limited to: `franchise cornerstone`, `breakout candidate`, `post-hype sleeper`, `hype train`, `emerging role`, `declining asset`, `liquidity chip`, `roster clogger`, `injury discount`, and `market overheat`.

Every tag is a deterministic Layer 2 estimate. Codex may explain tags in Layer 3 artifacts, but Codex must not create canonical tags or write generated facts into processed tables.

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

## 2026-08-26 Career History Receipt Amendment

`player_horizon_market_scores` uses `player_usage_weekly` as an additional
deterministic input for the career-window scenario. Because that table carries
nflverse player IDs rather than Sleeper IDs, the bridge is allowed only when a
normalized player name plus position resolves to one nflverse source ID. The
row must expose `career_history_join_method`,
`career_history_source_player_id`, `career_history_status`,
`career_history_seasons`, `career_history_games`, `career_history_ppg`, and
`career_history_latest_season`. Ambiguous or absent joins remain explicit and
fall back to the age-only scenario; they never overwrite the canonical Sleeper
player ID or create a silent cross-source identity claim. The model version is
`horizon_market_v2`.
## 2026-08-26 Horizon identity and publication boundary

Every player_horizon_market_scores row now carries league_id. When a
league-scoped roster frame is available, the builder filters it before
attaching roster_id or team_name; the selected Sleeper roster is
authoritative and projection labels are fallback context only. The same
receipt is retained in horizon_snapshot_history, with an additive backfill
from the existing league scope key for older snapshots.

The public Four-Window Market Read is intentionally a concise decision layer:
one representative lead per position and a capped disagreement/fit queue.
The complete cohort, transition deltas, PPG baseline, availability status, and
source trace remain in the data room and evidence drawer. Rest-of-season PPG is
described as a conditional baseline when a current injury flag exists; it is
not silently converted into a recovery-adjusted forecast.

## 2026-08-26 Manager Horizon Coverage Amendment

`manager_transaction_preferences` retains the aggregate
`horizon_acquired_matches` and `horizon_sold_matches` fields for compatibility,
but those counts are not evidence that every clock is covered. The table also
emits field-specific acquired/sold match counts for next game, rest of season,
dynasty, career window, contender fit, and rebuilder fit, along with
`horizon_coverage_detail` for the reader surface. These counts describe how
many identity-resolved transaction events have a current horizon value; they
do not reconstruct historical prices, manager intent, or willingness.

## 2026-08-26 Desk editor publication receipt

Generated article markdown may carry an `editorial_review_json` front-matter
receipt. The deterministic publication gate remains mandatory for every mode:
it checks body presence, the structured story spine, article-level evidence
IDs, source IDs, and the writer mode. An optional explicit second pass is
enabled only with `FRONT_OFFICE_EDITOR_MODE=llm` and uses the configured Luna
model. Its decision is one of `approve`, `modify`, or `hold`; an approved
modification must be a complete article replacement that passes the writer
validator and the deterministic gate. A persisted LLM hold suppresses the
article body on the reader facade, while the review note, errors, and provider
receipt remain inspectable. The editor is an evidence-bound repair layer, not a
new source of player facts, projections, scores, manager motives, or actions.
When a deterministic article passes the evidence checks without a reporter
artifact, its publication status is `fallback` with decision `keep_fallback`:
the content remains readable and linked to evidence, but the reader must not
label it editor-approved or count it as a current reporter article.

The writer validator also runs an evidence-aware claim-boundary check. A
generated article is held if it uses unqualified projection or PPG language
for a player whose current Sleeper status is no current NFL team. Injury-
sensitive rest-of-season production produces a warning when the article omits
the not-recovery-adjusted limitation. These checks protect the publication
seam without changing the underlying deterministic score or historical
baseline.
