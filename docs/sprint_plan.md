# Sleeper Dynasty Front Office Sprint Plan

This document is the project control surface for building the full Sleeper dynasty front office app. It sits above `docs/data_contract.md`: the data contract defines current table/source rules, while this sprint plan defines the ordered path, V-model checks, source boundaries, and contradiction checks for future work.

## Product North Star

Build a browser-first, read-only Sleeper dynasty front office that combines league data, projected fantasy production, market economics, news intelligence, manager behavior, deterministic signal transforms, and Codex-authored analyst interpretation.

The app should help a dynasty manager understand:

- what the league data says
- what the market is mispricing
- what the projected season says a player should be worth
- which players are breakout, miss, buy, hold, or sell candidates
- which managers behave in exploitable ways
- which news items create trade windows
- what the analyst layer thinks, with evidence and confidence

Current writer gate note (2026-08-25): the headquarters reconciles persisted
article models against the configured `gpt-5.6-luna` model before a paid run.
An older run is labeled as requiring regeneration; it is not counted as current
publication without matching bundle receipts.

Current writer configuration note (2026-08-26): the personal newsroom defaults
to `gpt-5.6-luna` with `reasoning.effort=max`; an explicit environment override
is allowed when cost or latency is intentionally prioritized.

Current data lifecycle note (2026-08-25): league data now has an explicit
bootstrap/maintenance boundary. Bootstrap builds the historical evidence base;
maintenance refreshes a bounded current-season scope and merges canonical rows
by exact source keys before rebuilding derived analytics and the browser bundle.
The receipt records which mode ran and whether historical scope was preserved.

## Current implementation note (2026-08-24)

The writing layer is now provider-neutral through `src/llm.py`. OpenAI
`gpt-5.6-luna` is the default production writer, with reasoning effort set
independently; Anthropic remains available only when explicitly configured.
Sprint 13 and Sprint 16 entries below describe the historical Anthropic-first
implementation and its validation lessons. Their provider-specific names do
not override the current adapter or deployment configuration.

Core invariants:

- Sleeper is the league source of truth.
- Raw data is preserved before normalization.
- Deterministic app code owns facts.
- Codex owns interpretation only.
- Projection models and signal transforms are deterministic app code, not analyst prose.
- No trade execution, message sending, or Sleeper mutation.
- Browser is the primary workflow surface.
- CSV, SQLite, JSON, markdown, and raw files are audit artifacts.
- Every meaningful output must be scoped to any selected `roster_id`; team names
  such as the historical Melkor label are mutable presentation labels, not
  identity keys.

## V-Model Master Map

The left side defines requirements before implementation. The right side defines how each requirement is verified after implementation.

| Requirement | Definition | Verification |
| --- | --- | --- |
| R1: Trusted league ingestion | Pull Sleeper league, users, rosters, drafts, picks, traded picks, transactions, and player cache without authentication or mutation. | V1: endpoint/raw-cache tests confirm coverage, raw files, and row counts. |
| R2: External source ingestion | Pull only open/legal external sources such as nflverse, DynastyProcess, RotoWire RSS, Sleeper trending, and LeagueLogs. | V2: source freshness and fail-soft tests confirm unavailable sources do not break refresh. |
| R3: Canonical data hierarchy | Preserve raw sources first, normalize facts second, derive analytics third, generate presentation fourth. | V3: schema/source-trace tests confirm required columns, IDs, timestamps, and source ownership. |
| R4: Economic/manager behavior modeling | Generate market gaps, liquidity, team needs, manager behavior, and asset inventory from canonical facts. | V4: deterministic economics tests confirm stable outputs from fixtures. |
| R5: News intelligence | Convert news/trending/status sources into player-linked and league-aware impact rows. | V5: news fixture/player-match tests confirm source parsing, player matching, and roster impact. |
| R6: Projection data layer | Build a projected season model with fantasy points from open/legal data, league scoring, and traceable projection methods. | V6: projection fixture tests confirm fantasy-point math, player joins, source trace, and missing-data behavior. |
| R7: Transform signal layer | Convert projections, market values, roster context, news, and manager behavior into deterministic target/sell/breakout signals. | V7: signal fixture tests confirm stable labels, scores, risk, confidence, and evidence. |
| R8: Codex analyst layer | Let Codex write briefs, trade theses, and manager dossiers from processed projection and signal outputs only. | V8: analyst artifact validation confirms source trace, evidence, risk, confidence, and no unsupported claims. |
| R9: Automation and hooks | Run refresh, validation, and analyst generation safely on schedules or guarded hooks. | V9: automation dry-run/guardrail tests confirm no destructive actions or external transaction side effects. |
| R10: Browser-first front office | Make the browser the main workflow, with team-scoped pages and diagnostics. | V10: browser smoke and team-scope tests confirm core controls, views, and selected-team behavior. |
| R11: Recommendation packet auditability | Produce read-only recommendation packets with evidence and confidence. | V11: packet tests require action type, assets, evidence, risk, confidence, source trace, and read-only wording. |
| R12: Feedback/market memory | Track what the app believed, what happened later, and which signals were useful. | V12: outcome/history idempotency tests confirm reruns replace outputs without duplicate history rows. |

| R13: Explicit data lifecycle | Separate first-time historical assembly from recurring current-state maintenance without erasing prior evidence. | V13: mode tests prove bootstrap discovers history, maintenance preserves prior canonical rows, exact fresh keys win, and refresh metadata reports the requested scope. |

## Sprint Sequence

### Sprint 1: Data Contract Hardening

Goal: Make the existing data platform harder to accidentally corrupt.

Key deliverables:

- Expand `docs/data_contract.md` with current table contracts and source trace requirements.
- Add schema expectations for every processed CSV/SQLite table.
- Ensure refresh metadata describes source scope, raw roots, external roots, and recommendation status.

Data contracts:

- Current Sleeper and external market/usage tables remain canonical fact tables.
- Existing economic outputs remain derived analytics.
- Internal proxy values must be labeled as proxy values, never external truth.

Browser changes:

- Diagnostics must show row counts and freshness for all active source groups.

Tests:

- Schema tests for every processed table.
- Source trace tests for derived/economic outputs.
- Idempotent refresh regression test.

Acceptance criteria:

- `python scripts/refresh_all.py` can be rerun without duplicated rows.
- Browser diagnostics expose source freshness and table counts.
- Every required table has a documented owner and purpose.

Non-goals:

- No new news ingestion.
- No Codex analyst generation.
- No UI redesign.

### Sprint 2: News Source Ingestion

Goal: Add deterministic news and trend ingestion without using Codex as the news fetcher.

Key deliverables:

- Add RotoWire RSS ingestion as the first fantasy player-news source.
- Add Sleeper trending add/drop ingestion as market reaction data.
- Add LeagueLogs blurbs as an optional attributed status source.
- Cache raw news/source payloads before normalization.

Data contracts:

- Add `news_events`.
- Add `player_news_matches`.
- Add `league_news_impact`.
- Add `news_source_freshness`.

Browser changes:

- Add initial News Desk view with source, timestamp, player, matched roster, and confidence.

Tests:

- RSS fixture parsing.
- Sleeper trending fixture parsing.
- LeagueLogs fixture parsing when enabled.
- Player matching tests by Sleeper ID, then normalized name/team fallback.
- Fail-soft source freshness tests.

Acceptance criteria:

- News refresh can run without Codex.
- Raw news payloads are inspectable.
- Ambiguous player matches are flagged, not silently trusted.

Non-goals:

- No Codex prose.
- No scraping restricted pages.
- No automated trade recommendations from news yet.

### Sprint 3: League Impact Model

Goal: Turn factual news into league-aware impact signals.

Key deliverables:

- Join news events to rosters, managers, team needs, liquidity, and market gaps.
- Generate deterministic impact types: buy window, sell window, hold, churn, monitor, injury risk, depth chart watch.
- Add confidence based on source quality and player-match quality.

Data contracts:

- Extend `league_news_impact` with roster/team/manager context.
- Add `news_impact_signals` if the impact model becomes too wide for one table.

Browser changes:

- Add League Impact section.
- Add Trade Windows section based only on deterministic impact signals.

Tests:

- News item on rostered player creates selected-team impact.
- News item on another manager's player creates target-team impact.
- Ambiguous news item remains flagged and excluded from high-confidence actions.

Acceptance criteria:

- Every impact row has source, player, affected team, evidence, risk, confidence, and timestamp.
- Views work for any selected `roster_id`.

Non-goals:

- No Codex-authored analysis.
- No recommendations that lack deterministic evidence.

### Sprint 4: Projection Data Layer V1

Goal: Build a traceable projected season model before creating stronger recommendations.

Key deliverables:

- Generate season-level player projections from nflverse historical stats, Sleeper player metadata, and league scoring config.
- Calculate projected fantasy points and projected PPG.
- Join projections to Sleeper roster ownership and market values when available.
- Label projection method and missing-data confidence.

Data contracts:

- Add `player_projection_season`.
- Add `player_projection_weekly` as a future-compatible table, even if V1 uses season allocation only.
- Add `projection_source_freshness`.

Browser changes:

- Add Projection Board view.
- Add projection summaries to Today's Board only as factual context, not recommendations.
- Diagnostics must show projection row counts and projection freshness.

Tests:

- Fantasy scoring fixture tests for passing, rushing, receiving, reception, and turnover fields.
- Missing stat fields default safely without breaking refresh.
- Projection rows preserve player IDs, source trace, projection method, and confidence.

Acceptance criteria:

- Every fantasy-relevant rostered player has either a projection row or a clearly labeled missing-data row.
- Projection output is deterministic and auditable.
- Browser can show projected fantasy points and PPG for any selected `roster_id`.

Non-goals:

- No Codex-written player takes.
- No target/sell recommendations from projections yet.
- No paid projection source dependency. (Lifted in Sprint 12 per the Source Policy's "Paid/API-key sources explicitly configured by the user" allowance below — this was a V1-scope boundary, not a permanent ban.)

### Sprint 5: Transform Signal Layer V1

Goal: Transform projections and market context into deterministic player signals.

Key deliverables:

- Compare projected fantasy points/PPG against player market value and liquidity.
- Generate breakout, miss, buy, hold, sell, and watch labels.
- Score team fit by roster timeline, position scarcity, age, projection edge, and manager demand.
- Keep all signals explainable with evidence, risk, confidence, and source trace.

Data contracts:

- Add `player_signal_scores`.
- Add `breakout_candidates`.
- Add `sell_candidates`.
- Add `projection_market_gaps`.
- Add `team_fit_scores`.

Browser changes:

- Add Signal Board view.
- Update Today's Board to use signal outputs instead of raw market-gap rows where available.
- Keep raw signal tables available lower on the page.

Tests:

- Fixture tests for breakout, sell, and projection-market-gap labels.
- Rebuild vs contender fit tests.
- Confidence downgrades when projection confidence or market data is missing.

Acceptance criteria:

- The app can deterministically identify projected mispricing before analyst prose exists.
- Every signal has evidence, risk, confidence, and source trace.
- Signals work for any selected team.

Non-goals:

- No Codex-authored analysis.
- No trade execution or outbound messages.

### Sprint 6: Analysis Layer V1

Goal: Add an auditable analyst layer that explains deterministic projection and signal outputs without changing facts.

This sprint turns the app from "shows signals" into "explains why the signal matters." The core product move is a clean separation between the deterministic model and the analyst voice:

- Data layer says what happened or what is projected.
- Transform layer says what the model flags.
- Analysis layer says why a dynasty manager should care.

The analysis layer must be useful even before fully automated Codex hooks exist. V1 can generate deterministic template-backed analyst artifacts from processed tables, while preserving a contract that later Codex runs can fill or improve the prose. (The "later Codex runs" this section anticipates landed in Sprint 13 -- an automatic Anthropic API call replacing the manual copy-paste operator loop, reusing this sprint's packet/validate contract unchanged.)

Key deliverables:

- Add `data/analysis/` as a separate generated artifact layer.
- Build analyst context packets from projection, signal, news, market, roster, and manager behavior outputs.
- Generate V1 analyst artifacts from deterministic templates, with fields shaped for future Codex-authored prose.
- Add controlled prompt specs for daily GM brief, trade desk, manager dossiers, target theses, sell theses, and news impact memo.
- Validate analyst artifacts before browser display.
- Add browser sections that clearly label analysis as interpretation.
- Keep canonical and derived CSV outputs immutable from analyst generation.

Implementation plan:

1. Create `src/analysis.py`.
2. Read only from `data/processed/` tables.
3. Build compact context packets for the active team and league-wide watchlist.
4. Generate analyst artifacts into `data/analysis/`.
5. Add artifact validation before rendering.
6. Render analysis into the browser from `data/analysis/`, not from ad hoc browser logic.
7. Add tests proving artifacts cite deterministic rows and do not mutate processed facts.

Data contracts:

- Add `analysis_context_packets.json`.
  - Purpose: machine-readable packets built from processed facts for analyst generation.
  - Required fields: `packet_id`, `packet_type`, `roster_id`, `team_name`, `subject_id`, `subject_name`, `source_tables`, `evidence`, `risk`, `confidence`, `created_at`.
- Add `daily_gm_brief.md`.
  - Purpose: readable summary of the active team's best opportunities and risks.
  - Required front matter: `artifact_type`, `generated_at`, `roster_id`, `team_name`, `model_mode`, `source_tables`.
- Add `target_theses.json`.
  - Purpose: explained buy/breakout targets.
  - Required fields: `thesis_id`, `roster_id`, `player_id`, `player_name`, `position`, `team_name`, `signal_label`, `approach`, `evidence`, `risk`, `confidence`, `source_trace`, `analysis_text`, `generated_at`.
- Add `sell_theses.json`.
  - Purpose: explained sell/trim candidates.
  - Required fields: `thesis_id`, `roster_id`, `player_id`, `player_name`, `position`, `team_name`, `signal_label`, `sell_window`, `evidence`, `risk`, `confidence`, `source_trace`, `analysis_text`, `generated_at`.
- Add `trade_theses.json`.
  - Purpose: manager-aware thesis packets combining target/sell assets with manager tendencies.
  - Required fields: `thesis_id`, `roster_id`, `target_manager_roster_id`, `target_manager_name`, `approach_type`, `assets_to_discuss`, `manager_signal`, `evidence`, `risk`, `confidence`, `source_trace`, `analysis_text`, `generated_at`.
- Add `manager_dossiers.md`.
  - Purpose: plain-language manager profiles grounded in behavior tables and event logs.
  - Required front matter: `artifact_type`, `generated_at`, `source_tables`, `manager_count`.
- Add `news_impact_brief.md`.
  - Purpose: readable summary of recent news rows and possible league impact.
  - Required front matter: `artifact_type`, `generated_at`, `source_tables`, `news_event_count`.
- Add prompt/version metadata to each artifact.
  - Required metadata: `analysis_version`, `generation_mode`, `prompt_version`, `source_tables`, `generated_at`.

Analysis rules:

- Every thesis must cite at least one deterministic source row through `source_trace`.
- Every thesis must include `evidence`, `risk`, and `confidence`.
- `analysis_text` may summarize and interpret, but must not invent stats, injuries, offers, accepted trades, messages, or ownership changes.
- Analyst artifacts must be replace-on-refresh generated files.
- Missing analysis artifacts must fail soft in the browser with a diagnostics row, not break Sleeper-generic views.
- If future Codex prompt output is unavailable, deterministic template text is acceptable for V1.

Browser changes:

- Add Analyst Brief section.
- Add Target Thesis and Sell Thesis sections.
- Add Manager Dossiers section.
- Label all Codex-generated content as analyst interpretation.
- Add analysis diagnostics:
  - analysis artifact status
  - generated timestamp
  - target thesis count
  - sell thesis count
  - trade thesis count
  - source tables used
- Add filters:
  - active team vs league
  - thesis type
  - confidence
  - position
- Keep the visual treatment simple and readable: thesis cards with headline, why it matters, evidence, risk, and confidence.

Tests:

- Analyst artifact shape validation.
- Required evidence/risk/confidence fields.
- Guardrail test that analyst output cannot claim a trade was sent, accepted, or executed.
- Context packet tests confirming packets are built from processed tables only.
- Source trace tests confirming every thesis points to deterministic source tables.
- Browser tests confirming Analyst Brief, Target Thesis, Sell Thesis, Manager Dossiers, and analysis diagnostics render.
- Missing-artifact tests confirming the browser still loads when `data/analysis/` is absent.
- Idempotency test confirming regenerated artifacts replace prior output.

Acceptance criteria:

- Codex can regenerate analyst artifacts from processed facts.
- Codex explanations cite signal/projection rows rather than inventing player takes.
- Canonical tables are not mutated by Codex.
- Browser clearly separates facts from interpretation.
- The live app shows usable analysis for the active team after `python scripts/refresh_all.py`.
- Each target/sell thesis has a source trace, risk note, confidence label, and concise explanation.
- The browser remains useful if analysis artifacts are missing or stale.
- Tests pass and production smoke passes after deploy.

Non-goals:

- No autonomous outbound messages.
- No hidden prompt runs that write into canonical data.
- No automated trade proposals.
- No claims that a recommendation was sent, accepted, negotiated, or executed.
- No new external data source ingestion in this sprint.

### Sprint 7: Automation And Hooks

Goal: Safely automate refresh, validation, and analyst generation.

Key deliverables:

- Add one command for daily pipeline execution.
- Add dry-run mode for automation.
- Add hook/automation guardrails for generated artifacts.
- Document scheduling options, including Windows Task Scheduler and Codex hook usage.

Data contracts:

- Add `automation_runs`.
- Add `automation_status`.
- Add validation result artifacts under `data/analysis/` or `data/reports/`.

Browser changes:

- Add Automation Diagnostics section with last run, status, failures, and next intended run if known.

Tests:

- Dry-run test does not write canonical outputs.
- Guardrail test prevents transaction-like side effects.
- Pipeline test validates refresh plus analysis artifact generation.

Acceptance criteria:

- A single local command can refresh, validate, generate analysis, and rebuild the browser.
- Automation failures are visible in diagnostics.
- Hooks never execute trades, send messages, or mutate Sleeper.

Non-goals:

- No always-on service requirement.
- No bypassing Codex trust/approval safeguards.

### Sprint 8: Browser Product Upgrade

Goal: Evolve the browser from a dense table surface into a front-office workspace.

Key deliverables:

- Move toward clear views: Command Center, Team Page, Manager Page, Player Page, News Desk, Trade Desk, Diagnostics.
- Preserve current table access for audit/debugging.
- Keep explicit team selector as the primary control.

Data contracts:

- Browser reads processed facts and analysis artifacts only.
- Browser does not own business logic.

Browser changes:

- Add navigation that matches workflows instead of table names.
- Make team-scoped workflows easy to scan.
- Keep source/evidence/risk visible near every recommendation.

Tests:

- Browser smoke test for each major view.
- Team selector updates team-scoped views.
- Text fit/layout checks for desktop and mobile widths.

Acceptance criteria:

- The browser can be used as the primary weekly workflow.
- A user can answer: what changed, who is vulnerable, what assets matter, and what should I think about today.

Non-goals:

- No visual polish at the expense of missing workflow controls.
- No landing page.

### Sprint 9: Recommendation Packets

Goal: Formalize read-only action packets.

Key deliverables:

- Generate recommendation packets from economics, manager behavior, news impact, and strategy overlay.
- Generate recommendation packets from projection signals, manager behavior, news impact, and strategy overlay.
- Include deterministic packet fields and optional analyst note.
- Add filters for reacquire picks, buy lows, sell windows, churn candidates, and manager-specific offers.

Data contracts:

- Add `recommendation_packets`.
- Required fields: `action_type`, `target_team`, `assets_in`, `assets_out`, `evidence`, `risk`, `confidence`, `source_trace`, `analyst_note`, `created_at`, `strategy_profile`.

Browser changes:

- Add Trade Desk packet view.
- Add evidence drawer or detail table for each packet.

Tests:

- Packet schema validation.
- No packet without evidence/risk/confidence.
- No packet language implying execution.
- Team-scoped packet tests across multiple roster IDs.

Acceptance criteria:

- Packets are auditable, read-only, and useful enough to support manual decision-making.

Non-goals:

- No sending offers.
- No Sleeper auth.
- No negotiation bot.

### Sprint 10: Feedback And Market Memory

Goal: Let the app track whether its reads were useful over time.

Key deliverables:

- Store dated market snapshots and recommendation outcomes.
- Store dated projection snapshots, signal snapshots, market snapshots, and recommendation outcomes.
- Track manager prediction history and analyst decisions.
- Add review views for what changed and whether prior reads were right.

Data contracts:

- Add `market_snapshots`.
- Add `projection_snapshots`.
- Add `signal_snapshots`.
- Add `analyst_decisions`.
- Add `recommendation_outcomes`.
- Add `manager_prediction_history`.

Browser changes:

- Add Market Memory view.
- Add Outcome Review view.

Tests:

- Snapshot idempotency test.
- Outcome update test.
- Historical rows are append-only unless explicitly regenerated by dated key.

Acceptance criteria:

- The app can compare prior beliefs with later market/news/league events.
- The app can compare projected season beliefs and signal labels with later market/news/league events.
- Manager behavior labels become inspectable over time.

Non-goals:

- No opaque self-modifying model.
- No automatic strategy changes without review.

### Sprint 11: Market Lens Lab V1

Goal: Let the user explore different valuation philosophies in the browser without changing canonical facts, generated recommendations, or source-of-truth tables.

This sprint builds on the market-consensus and counterparty-edge foundation. The product thesis is that a dynasty edge often appears when four valuation lenses disagree:

- market consensus
- projection value
- manager revealed preference
- roster/timeline fit

The app should let us ask, "What if this league mate values assets more like DynastyProcess, more like projections, more like short-term roster need, or more like their own past behavior?" That scenario exploration should be fast, readable, and clearly labeled as exploratory.

Key deliverables:

- Add browser-only weighting controls for the four valuation lenses.
- Add deterministic default presets:
  - Balanced Market
  - Projection Contrarian
  - Counterparty Exploit
  - Contender Trade Market
  - Rebuild Asset Bank
  - News Heat Check
- Add a scenario scoring layer in the browser using existing processed component fields.
- Show how selected weights reorder counterparty targets, buy/watch targets, sell candidates, and do-not-chase assets.
- Add sensitivity rows that identify which players move the most when weights change.
- Keep canonical CSV/SQLite outputs unchanged when sliders move.
- Add a clear warning that scenario scores are exploratory and do not replace default model output.

Data contracts:

- No new canonical tables are required for V1.
- Browser scenario state is client-side only.
- Inputs are existing processed outputs:
  - `market_consensus_values`
  - `player_signal_scores`
  - `manager_valuation_profiles`
  - `counterparty_trade_edges`
  - `team_needs_matrix`
  - `league_news_impact`
- Add a documented browser scenario component contract:
  - `market_component`
  - `projection_component`
  - `manager_component`
  - `timeline_component`
  - `news_component`
  - `scenario_score`
  - `scenario_label`
  - `scenario_warning`
- Scenario rows must remain presentation-layer calculations. They must not be written back into `data/processed/` unless a future settings/snapshot sprint explicitly adds that contract.

Browser changes:

- Add **Market Lens Lab** as a Trade Desk subsection.
- Add preset buttons near the top of the section.
- Add sliders or numeric inputs for:
  - Market Consensus
  - Projection Value
  - Manager Preference
  - Timeline / Team Fit
  - News Heat
- Show total weight and require valid weights before ranking.
- Add three result panels:
  - Scenario Targets
  - Scenario Sells
  - Biggest Movers
- Add a compact evidence row for each result:
  - market value
  - projected PPG
  - manager label/confidence
  - edge type
  - risk/confidence
- Add a "canonical model" comparison column so users can see when the scenario disagrees with the default model.
- Do not put this above Today's Board yet; V1 belongs in Trade Desk as an exploratory lab.

Implementation notes:

- Keep all calculations in `src/browser_site.py` JavaScript for V1.
- Use existing table fields only; do not add new external ingestion.
- Normalize component scores to a 0-100 scale before applying weights.
- Treat missing component data as degraded, not zero certainty.
- Cap scenario confidence when:
  - market consensus is missing
  - source disagreement is high
  - manager valuation confidence is low
  - projection confidence is low
  - news match is ambiguous
- Preserve the default model ordering in existing Action Board and Counterparty Edge sections.

Tests:

- Browser HTML contains `Market Lens Lab`.
- Default preset weights sum to 100.
- Each preset produces deterministic client-side configuration data.
- Scenario calculations do not change canonical table payloads.
- Missing market, projection, or manager components produce degraded warnings.
- Browser smoke confirms Market Lens Lab renders with preset controls and result panels.
- Regression test confirms `python scripts/refresh_all.py` still writes the same processed table set and does not add scenario CSVs.

Acceptance criteria:

- A user can change valuation weights in the browser and immediately see target/sell rankings change.
- The app clearly labels scenario output as exploratory.
- Canonical recommendations, processed CSVs, and SQLite tables remain unchanged by slider interaction.
- Scenario results explain which lens drove the ranking.
- The live site passes smoke tests and browser checks after deploy.

Non-goals:

- No saved user preferences.
- No new external market sources.
- No KTC automation.
- No Codex analyst rewriting based on slider state.
- No transaction execution, outbound messages, or Sleeper mutation.

### Sprint 12: Multi-Source Projection Consensus

Goal: Fix the single-source trust gap Sprint 4 deliberately deferred -- `player_projection_season` was nflverse-only, with no cross-source blending, weighting, or accuracy grading. Extends Sprint 4 (paid source allowance, per Source Policy) plus a minimal slice of Sprint 10 (append-only dated snapshot pattern, applied narrowly to projection history rather than the full market/signal/outcome snapshot set).

Key deliverables:

- Fantasy Nerds added as a second live, paid, API-key-gated weekly projection source (`FANTASY_NERDS_API_KEY`; disabled with a clear freshness row, not an error, when absent).
- `player_projection_season`/`player_projection_weekly` become a consensus across whatever sources are present (equal-weighted at cold start, accuracy-weighted once `source_accuracy_scores` has history) -- the column contract is unchanged, so `player_signal_scores` and everything downstream needed zero changes.
- Retrospective accuracy grading for `nflverse_history` (backtested against its own held-out prior-season actuals, no snapshot needed) and for `fantasy_nerds` (graded against `data/processed/projection_snapshot_history.csv`, a new append-only, dated-key-idempotent log -- the minimal Sprint 10 slice).

Data contracts:

- Add `fantasy_nerds_projection_source`.
- Add `projection_source_components`.
- Add `source_accuracy_scores`.
- Add `data/processed/projection_snapshot_history.csv` (append-only; deliberately not part of the overwrite-every-refresh export loop).

Tests:

- Consensus blending flags disagreement and derives confidence from source count/agreement.
- Degrade-to-single-source path is byte-identical to pre-Sprint-12 output when Fantasy Nerds is absent (regression guard).
- Fantasy Nerds fails soft (disabled, not erroring) without an API key.
- Accuracy grading matches a hand-computed mean absolute error against synthetic actuals.
- `player_signal_scores` needs zero code changes against the blended contract (guard test).

Acceptance criteria:

- With only nflverse available, output is unchanged from before this sprint.
- With two sources available, the consensus is a real blend, never silent last-write-wins.
- Numeric accuracy (mean absolute error) stays diagnostic-only; every contract-facing confidence field stays the existing `high`/`medium`/`low` categorical vocabulary, consistent with the rest of this codebase.

Non-goals:

- Multi-league support (config/identity model stays single-league-shaped).
- Position-tier-segmented weighting beyond a simple per-position lookup.
- The rest of Sprint 10 (market/signal snapshots, `recommendation_outcomes`, `manager_prediction_history`).

### Sprint 13: Automated Codex Insight Generation

Goal: Replace the manual copy-paste operator loop (build packet -> paste into an external LLM chat by hand -> paste response back -> validate) with a real, automatic Anthropic API call, so insight generation requires one click instead of four manual steps. Confirmed the manual loop had never actually been used because of this friction.

This is not new interpretation infrastructure -- Sprint 6's packet/schema/validation contract and Sprint 9's operator loop are reused unchanged. This sprint only replaces the human in the middle with a real API call.

Key deliverables:

- `generate_insight_output_via_llm()` in `src/operator.py`: calls the Anthropic Messages API (`claude-haiku-4-5-20251001` by default, overridable via `FRONT_OFFICE_INSIGHT_MODEL`) with a tool-forced request (`tool_choice` pinned to a synthetic `emit_insight_cards` tool matching `required_output_schema` exactly) for reliable structured output, rather than parsing freeform text.
- `generate_insights_automatically()`: orchestrates build-packet -> LLM call -> `import_insight_output()` (Sprint 6's existing validator, unchanged) in one step. Requires `ANTHROPIC_API_KEY`; fails loud (clear `state: "failed"` + message) if the key is missing or the API call errors -- deliberately different from the fail-soft convention used for free read-only sources, since this is an explicit, cost-incurring, user-triggered action.
- `build_chat_context_markdown()`: renders the evidence packet as clean markdown instead of raw JSON, for users who prefer pasting context into their own ad-hoc chat over reading generated cards -- addresses a real, separate value proposition surfaced by the user (a live conversation can be more useful than a canned summary; this makes the hand-off to that conversation effortless instead of building a full in-app chat).
- New routes: `POST /api/operator/generate-insights`, `GET /api/operator/chat-context`. Both token-gated identically to every other operator route.
- Two new browser buttons in the existing Operator Mode section, reusing the existing `runOperatorAction()` JS pattern for the first and a new small clipboard-write function for the second.

Data contracts: none new. Output shape is identical to the existing `validated_insight_cards.json` contract from Sprint 6; `generation_mode` field distinguishes `"automatic_llm"` from the manual `"operator_packet_loop"` mode.

Tests:

- Fails loud (no HTTP call attempted) when `ANTHROPIC_API_KEY` is absent.
- Tool-forced request shape (`tool_choice` pinned, schema matches `required_output_schema`).
- Full pipeline test: mocked LLM response citing real packet evidence IDs -> validated and written correctly.
- Fails loud on API error, with nothing written to the output/validated paths.
- Chat-context markdown includes real evidence content, not raw JSON.

Acceptance criteria:

- One click generates real Claude-authored insight cards, replacing boilerplate template text, with zero manual copy-paste.
- The existing manual loop (`build-packet`/`import-insights`/`validate-insights`) is untouched and still works for debugging or manual use.
- Insight generation stays a separate, explicitly-triggered action -- never folded into the free/automatic data refresh -- so cost is only incurred when the user actually wants fresh insights.
- "Copy Chat Context" produces markdown a person would actually want to paste into a chat, not a JSON dump.

Non-goals:

- No in-app chat UI (a much bigger, separate decision; the markdown export is the deliberately smaller alternative).
- No scheduled/automatic insight regeneration (that is Sprint 7's automation scope, not attempted here).
- No change to the manual operator loop's existing endpoints or validation rules.

### Sprint 14: Signal Calibration And Unified Priority Board

Goal: Fix real calibration bugs found by inspecting the live deployed browser directly, and collapse Today's Board's six overlapping sub-sections into one deduplicated, ranked list. This was scoped after the user called the live browser "noisy" -- inspection showed the noise wasn't just presentation, it was undifferentiated math: manager behavior scores saturated at 100 for any manager past a low activity threshold, and the deterministic "why" text was a fixed string identical across every player clearing the same action threshold, before Sprint 13's LLM path even runs.

Key deliverables:

- `build_manager_behavior_signals()` rewritten to score managers by rank-based percentile within the current league's manager set, replacing the old hard-capped absolute multipliers (`min(100, trade_count * 18)` saturated at just 6 trades, making a 6-trade manager and a 46-trade manager indistinguishable). Reuses the percentile-ranking pattern already established in `profile_intelligence.py` for cross-season profiling, applied here to current-season behavior scores.
- `_classify_action()`'s why-text for every action label now interpolates the player's actual computed numbers (gap score, PPG, age) into the sentence instead of returning one fixed string literal per label. Still fully deterministic -- this is parameterization, not prose generation, which stays Sprint 13's job.
- New `src/priority_board.py`, `build_today_priority_board()`: merges `action_recommendations`, `league_news_impact`, `pick_ownership`, and `manager_behavior_signals` into one ranked list, deduplicated by `(entity_type, entity_id)` so a player who is both an action recommendation and a news item becomes one row, not two (the literal root cause of the same sell candidates rendering three times on one page load -- "Sell Windows" was re-filtering the same `action_recommendations` rows "Action Board" already showed). Priority is a percentile rank across the whole combined candidate pool for the week, not hand-tuned cross-type weights.
- Today's Board in `src/browser_site.py` collapsed from six sub-sections (Action Board, Sell Windows, My Roster News, Trade Target News, Pick Alerts, Manager Angles) into one `today-priority-board` list rendered by one new `priorityCards()` function; the five now-orphaned per-type render functions (`actionCards`, `opportunityCards`, `newsCards`, `pickAlertCards`, `managerCards`) and `actionRecommendationRows()` were removed as dead code.

Data contracts:

- Add `today_priority_board`.

Tests:

- Two managers with clearly different real activity levels produce clearly different scores, neither pinned to the old saturation value.
- Two players clearing the same action threshold by different margins produce different why-text.
- A synthetic player present in both `action_recommendations` and `league_news_impact` collapses to one row in `today_priority_board`.
- Higher-priority synthetic items rank above lower ones.
- Browser HTML no longer contains the retired sub-section markup or render functions.

Acceptance criteria:

- Real production data (not synthetic) confirms two managers with genuinely different trade/FAAB activity no longer both show 100 across every score dimension.
- The same "true buy low" / "sell window" reasoning is never repeated verbatim across different players.
- The same player never appears twice in Today's Board.
- Existing manager/action/news/pick table contracts are unchanged -- this only adds a new merged table and fixes math, it does not restructure `action_recommendations`, `league_news_impact`, `manager_behavior_signals`, or `pick_ownership`.

Non-goals:

- Scheduled/automatic refresh cadence (explicit separate follow-on plan, not bundled here).
- News Desk's own relevance ranking (it's a reference/browse log, not a priority surface; the tables feeding Today's Board already filter correctly).
- Any change to Sprint 11's Market Lens Lab, which was already found to genuinely work as specced.

### Sprint 15: Dense-Terminal Visual System

Goal: fix a presentation problem Sprint 14 didn't touch -- every card and table on the page looked visually identical regardless of meaning (a buy signal, a sell signal, and a news item all rendered the same way; you had to read the title text to tell them apart), and zero player imagery existed anywhere despite `player_id` already being present on nearly every row. Scoped after the user asked for the site to "feel good to use," referencing other fantasy products (KeepTradeCut's rank-forward ranked-list layout, FantasyPros' tiered color-banding, Sleeper's avatar-first identification, ESPN/Yahoo's directional delta arrows, PFF's coarse score-tile treatment) rather than reinventing UI patterns from scratch. Chose "dense pro terminal" posture over a mobile-casual redesign, matching actual usage (desktop, Tuesday/Wednesday decision-making) and preserving the existing "Dynasty Command" brand identity.

Key deliverables:

- Two shared JS rendering primitives (`briefCard()`, `table()`) upgraded once, uplifting all ~19 sections that use them rather than a section-by-section rewrite. `briefCard()` gained three backward-compatible optional fields: `category` (drives a `cat-${bucket}` class and 4px left-border accent color), `rank` (KeepTradeCut-style dominant ordinal number), `playerId` (44px Sleeper headshot via `https://sleepercdn.com/content/nfl/players/thumb/{player_id}.jpg`, with an `onerror` fallback to a text-initials avatar so a missing photo never shows a broken image). `table()` gained an optional per-column `{ field, kind: 'delta' | 'score' }` config for genuinely signed gap/edge columns (directional arrow, colored by sign) and 0-100 level scores (PFF-style color-filled tile, banded at 70/40 against this app's existing high/medium/low confidence vocabulary).
- New `categoryFor(sourceHint, rawValue)` helper normalizes every categorical vocabulary already used across the app (`action_label`, `edge_type`, `signal_label`, `scenario_label`, `dynasty_cycle`, manager tags, player tags) into six consistent buckets (buy/sell/hold/watch/info/alert), reusing the existing brand palette for three of them (`--accent` green = buy, `--accent-2` rust = sell, `--gold` = watch) and adding two new low-saturation tokens for the two buckets with no existing analog (`--hold` steel blue, `--alert` plum).
- All 8 `briefCard`-calling functions and 7 `table` column arrays with meaningful gap/score columns migrated to the new fields; identity/reference tables (roster, picks, trades, waivers, diagnostics, draft) intentionally left as plain tables.

Tests:

- New assertions in `test_browser_surface_contains_workflow_and_diagnostics` guard the new shared helper function names (`categoryFor`, `playerHeadshotUrl`, `renderCell`) and the `cat-${bucket}` class construction, mirroring the existing `"function priorityCards"` pattern.

Acceptance criteria:

- Verified against real production data via live browser DOM inspection (not just HTML-string assertions, per the Sprint 14 lesson that runtime JS bugs are invisible to the test suite): category colors resolve correctly from real rows (a `rebuild`-cycle manager's dossier card renders `cat-sell`, a `true_buy_low` action renders `cat-buy`), rank numbers render sequentially, headshots load real images keyed by real `player_id` values, the broken-image fallback renders initials instead of a broken-image icon, score tiles band correctly, delta arrows point the correct direction, and zero console errors occur on load or after a filter/scope interaction.
- Existing table/card contracts are unchanged -- this is presentation-layer only, no Python data tables were added, removed, or restructured.

Non-goals:

- Scheduled/automatic refresh cadence (still the same standing follow-on from Sprint 14, not touched here either).
- Cleanup of the `todayManagerColumns`/`todayOpportunityColumns`/`todayNewsColumns` dead constants left over from Sprint 14's board consolidation -- unused but harmless, out of scope for a visual-only pass.

### Sprint 16: Section Navigation And Narrative GM Brief

Goal: fix the two problems the user raised after Sprint 15's visual pass -- the side-rail was a table of contents for one endless scroll, not real navigation; and the Sprint 13 LLM pipeline only ever touched Manager Room/Player Room dossier one-liners, leaving the Analyst Brief's Daily GM Brief (the section actually labeled as analysis) 100% deterministic bullet-point boilerplate with zero personality.

Key deliverables:

- Client-side "page-swap" navigation: new `state.activeSection` field, `showSection(sectionId)` toggles the `hidden` property on every `<section>` so only the clicked one is visible, syncs `location.hash` via `history.pushState`, and toggles `.active` on the matching nav link (new `nav a.active` CSS rule mirroring the existing `button.active`). Click handlers bound in `bindControls()` following the file's existing per-element `addEventListener` idiom; a `hashchange` listener keeps browser back/forward working; initial load resolves from the current hash, defaulting to `todays-board`. `render()` is untouched -- this is a pure visibility layer on top of the existing always-computed sections. Fixed two orphan sections (`trade-market`, `waiver-market`) that existed but had no nav link at all, and a `#diagnostics` `<h2>` copy-paste bug ("Data Room" instead of "Diagnostics").
- Narrative Daily GM Brief: a new sibling to the Sprint 13 entity-card pipeline in `operator.py` -- `generate_daily_gm_brief_via_llm()` (same tool-forced request shape as `generate_insight_output_via_llm()`, new `emit_daily_gm_brief` tool and a persona-carrying system prompt distinct from the constraint-only entity-card prompt) and `validate_daily_gm_brief_output()` (same `FORBIDDEN_TERMS` scan and evidence-ID-subset citation check as `validate_insight_output()`, plus a structural check unique to a narrative -- the three required section headers must be present). On success, overwrites `daily_gm_brief.md` directly, the same file the deterministic template already freshly regenerates on every `refresh_all.py` run. `generate_insights_automatically()` extended to run both sub-pipelines in one action (each independently wrapped so one failing never hides the other's result), reporting a three-state outcome (`complete`/`partial`/`failed`) -- no new button, the existing "Generate Insights (LLM)" click now does more.
- Fixed a real latent bug found while wiring the transparency badge: `markdownBrief()`'s front-matter filter hardcoded a literal match against `deterministic_template`'s exact string, so any other `model_mode` value would leak a stray front-matter line into the rendered brief. Now strips the whole `---`...`---` block generically. A small `.tag`-styled badge next to the "Daily GM Brief" heading now shows "LLM-written" vs. "Deterministic" so it's always clear which version is showing.

Tests:

- `test_daily_gm_brief_validates_and_writes_narrative`, `test_daily_gm_brief_rejects_forbidden_language`, `test_daily_gm_brief_rejects_unknown_evidence_ids` -- mirror the existing `validate_insight_output()` test pattern for the new narrative validator.
- `test_generate_insights_automatically_reports_partial_success` -- one sub-pipeline succeeds, one fails, asserts the combined `state` is `partial` and both sub-results are independently present.
- Existing `test_generate_insights_automatically_imports_and_validates_llm_output`/`test_generate_insights_automatically_fails_loud_on_api_error` updated for the new two-pipeline return shape (a dispatching mock `requests.post` returns different tool responses depending on which tool was forced).

Acceptance criteria:

- Verified live: clicking every side-rail link shows only that section, nav `.active` highlight follows, `location.hash` updates, browser back/forward switches sections, a hard reload with an existing hash opens directly to that section, zero console errors throughout -- confirmed via direct DOM inspection (`main > section[hidden]` counts, `nav a.active` href), not just the string-presence test suite, per the same discipline Sprint 14/15 established.
- Existing entity-card pipeline (`generate_insight_output_via_llm`, `validate_insight_output`, `import_insight_output`) is unchanged -- this sprint adds a sibling, it does not modify Sprint 13's working code.

Non-goals:

- Scheduled/automatic refresh cadence (still the same standing follow-on, not touched again).
- Any change to `build_chat_context_markdown()` -- a separate, already-working manual export feature.
- A new landing-page narrative surface or multi-page routing -- deliberately deferred in favor of extending the existing Analyst Brief section and staying with one generated HTML file/one data bundle.

Post-ship hardening (found across the first two real clicks with a real key -- neither problem was caught by mocked tests or local dev, since Sprint 13's entity-card pipeline had never actually been exercised against the live Anthropic API until this sprint):

- Click 1: the entity-card pipeline returned zero cards (likely truncated at the token limit trying to write 10-20 verbose cards). `max_tokens` raised 4096 -> 8192 for entity cards, and both LLM call functions now check `stop_reason == "max_tokens"` and raise a clear, diagnosable error instead of silently returning an incomplete result. The narrative brief was also rejected for the bare word "sent" in a non-transactional sentence.
- Click 2 (after the click-1 fix): the entity-card pipeline actually produced 22 cards this time, but one was rejected for the *same* bare-word false positive originally assumed to only affect long narratives -- a single-sentence card field can just as easily contain "sent" non-transactionally. Both validators now share one `FORBIDDEN_LANGUAGE_PATTERNS` set: phrase-proximity regexes that only flag a transaction verb near trade/offer/deal vocabulary, replacing `FORBIDDEN_TERMS`' bare-word scan everywhere LLM prose gets checked (`FORBIDDEN_TERMS` itself is unchanged and still used as the plain-English list shown to the model in its own prompt). Separately, the narrative cited six evidence IDs and all six were fabricated (small numbers pattern-matching the real `entity_type:entity_id:index` format rather than copied from the real evidence array) -- both system prompts now explicitly instruct the model to copy `evidence_id` character-for-character rather than construct one, and `validate_daily_gm_brief_output()`'s citation check was loosened to reject only when *zero* of the cited IDs are real (a narrative synthesizing dozens of evidence items across four sections can plausibly drop or misformat one citation among several correct ones; a single-entity card citing its own one ID has no such excuse, so `validate_insight_output()`'s full-subset citation requirement is unchanged).

### Sprint 17: Per-Section Article Workflow

Goal: replace the single "generate 10-20 insight cards in one call" LLM step -- the token hog that kept truncating and failing all-or-nothing against the live API -- with a workflow that writes one focused article per meaningful section, plus a daily brief that synthesizes across them. The user's framing: "one call per article with a custom MD/prompt file sent along with the relevant data... really good, specific information, not a huge sprawling article," and "a workflow where the data gets updated and the new articles are created, 1 per section that is meaningful."

Key deliverables:

- `src/articles.py`: an article registry, one entry per section, each with an editable `prompts/{key}.md` template, a scope function selecting only that article's evidence (reusing the deterministic analysis artifacts; the team report reads the full `player_dossiers.csv` and filters to the active roster, since the `player_dossiers.json` artifact is only the top ~120 by team name and excludes the user's own team), and its own output `.md`.
- Starting articles: `team_report` (Team Room), `market_watch` (Signal Board), `trade_desk` (Counterparty Edges), `manager_intel` (Manager Room), and `daily_brief` (Analyst Brief), the summary, generated last with the four section articles' text as part of its input so it genuinely summarizes them.
- `src/operator.py`: generalized `generate_article_via_llm()` + `validate_article_output()` (reusing the Sprint 16 narrative shape -- tool-forced markdown + citations, phrase-proximity forbidden-language scan, lenient citation) and a `generate_articles_workflow()` orchestrator. Each article is generated + validated independently in its own try/except and reports its own state; one failing leaves its deterministic fallback in place and never blocks the others. Aggregate state is complete / partial / failed. The Sprint 13 entity-card mega-call is no longer what the button runs (its code and the manual endpoints stay intact and tested).
- `src/analysis.py`: deterministic fallback builders (`build_team_report`, `build_market_watch`, `build_trade_desk`, `build_manager_intel`) written on every refresh, so each article always has a baseline the LLM overwrites in place.
- `scripts/serve.py`: the generate route is now the full workflow -- refresh data, write articles, then rebuild the browser bundle (the bundle is baked at build time, so writing articles without a rebuild would not surface them; this also fixes a latent Sprint 16 gap where the brief was written but never rebuilt).
- `src/browser_site.py`: a prose-aware `articleBody()` renderer (headers + paragraphs + bullets via a line-based parser, no line cap), each article bundled and rendered at the top of its home section with an "LLM-written / Deterministic" badge, and the button relabeled "Update & Write Analysis (LLM)".

Tests: article registry has exactly one summary with the daily-brief filename and loadable prompts; `validate_article_output` accepts good output, rejects forbidden language / missing headers / all-unknown citations, and keeps partial-citation output with a warning; the workflow reports `partial` when one article's mocked call trips the forbidden-language check while the others succeed, leaving the failed article's `.md` unwritten and a successful one marked `automatic_llm`.

Acceptance criteria: verified locally that each article scopes to real data (team report to the active roster, not the whole league), the deterministic fallbacks write with their headers on refresh, the workflow runs end-to-end against real data with a mocked LLM, and the page renders every article panel with clean headings/paragraphs and no console errors. The real-API run is exercised live via the button (each article's per-section state is visible in the operator status), where partial success is expected and safe.

Non-goals: scheduled/automatic article generation (still the standing cadence follow-on -- article generation stays an explicit, user-triggered workflow and off the LLM-free startup refresh path); per-entity micro-articles; removing the now-unused entity-card generator (kept for its tests and the manual loop).

### Sprint 18: Opportunity-Based Scoring + Verification Backtest

Goal: close the real accuracy gap surfaced by a deep-research report -- our projections were a 2-year per-game *production* average with no *opportunity* lens, even though usage (target share, air yards, carries) is the stickier forward-looking signal. Built the opportunity layer, then verified it on our own data rather than trusting the report.

Key deliverables:

- `src/opportunity.py` (delegated to Codex, reviewed): `build_opportunity_scores` computes five 0-100 percentile-within-position scores (`opportunity_score`, `production_score`, `xfp_regression_score`, `role_trend_score`, `fragility_score`) from the weekly nflverse usage fields already cached (`target_share`, `air_yards_share`, `wopr`, `targets`, `carries`). Senior-engineer fix on review: it joined nflverse GSIS ids to Sleeper roster ids (zero overlap, 0 rows) -- corrected to the codebase's `_normalize_name` join, carrying the Sleeper `player_id` downstream. Shared `score_players_from_weekly` powers both the live table and the backtest.
- `src/backtest.py` + `scripts/backtest.py` (delegated to Codex, reviewed): rolling-origin harness over cached 1999-2024 weekly stats (no leakage: scores from weeks<=W, outcomes from weeks>W). Result on our data (30 snapshots, 12,263 player-snapshots), ROS top-finish AUC: `production_score` 0.846, `opportunity_score` 0.795 (both strong -- opportunity validated as a real predictor); `role_trend` 0.511, `xfp_regression` 0.358, `fragility` 0.267 (weak/inverse standalone). This *corrected* the report on the derived scores: they are value/risk/trend FLAGS, not outcome rankers.
- New `player_opportunity_scores` table wired into `refresh_all.py`; `opportunity_score` blended into `_breakout_score` (a real breakout needs usage to back it) and the four scores surfaced on `player_signal_scores`. New opportunity tags in `build_player_profile_tags` (`buy-low usage`, `rising role`, `fragile usage`) -- used only as flags, per the backtest.
- Polish: the `market_watch` article scope + prompt now feed the writer opportunity-vs-output evidence so it can say "the targets are there, the points haven't followed" in plain English; a static "Model Verification" note in Diagnostics states the backtested AUCs honestly.

Non-goals (explicit v2): the full `ffopportunity` XGBoost expected-points model, snap counts, NGS, red-zone share (all weighted 0.10-0.15 in the report, non-essential, and R-only for ffopportunity); the other 10 report scores (efficiency, asymmetry, liquidity, etc.) -- several already exist in our economics layer, and the backtest did not show they were worth adding yet.

### Sprint 19: Manager Data Correctness + Cross-Article Dedup

Goal: fix the two problems the first successful article run surfaced -- "roster stuff looks wrong" on other managers, and the same content repeating across articles. Both traced to the deterministic layer (the LLM was faithfully writing up bad inputs).

Root causes found and fixed:

- **Trade Desk pairings were round-robin** (`build_trade_theses` paired each manager with the Nth opportunity-board row, attributing players to managers who don't roster them). Now matched by the real `opportunity_board.target_team` linkage (verified 38/38 assets genuinely belong to their listed team); a manager with no matched asset gets a tendency-based angle and never someone else's player. Real-data check: 21/21 named assets owned by the correct manager.
- **11 of 12 managers classified "rebuild"**: `_pick_counts` counted ALL-TIME firsts (league median 10; one roster 52) so the absolute `>= 4` threshold fired for everyone. Now counts FUTURE firsts only (`pick_season >= current_season`) and classifies league-relative (percentile position, Sprint 14 pattern) with one absolute anchor -- zero future firsts is contender-leaning at any league size. Real-data result: 5 contenders / 4 rebuilders / 1 transition / 2 balanced, matching the actual pick-capital distribution. Post-fix hardening: `_percentile_series` returns 0-100 (per `_temperature`'s 75/45 usage), not 0-1 -- the first cut of the thresholds silently classified everyone rebuild again until checked against real data.
- **`likely_sells` was a fixed string per cycle** (11 identical "veteran RBs; short-window scorers" lines). Now roster-grounded: names the manager's actual veteran assets (age >= 28, market >= 20, best first) from player dossiers, so every manager's line is different and verifiable.
- **Cross-article repetition**: new `apply_entity_dedup` in `src/articles.py` -- the first section article to scope a player claims it (by normalized name, threaded through `ArticleContext.claimed_players`); later articles drop that player's evidence and receive one "covered elsewhere" context item instead. Daily brief exempt (it synthesizes by design) but its prompt now demands cross-section connections over recaps; the three later section prompts got matching don't-re-profile guidance. Real-data check: zero player overlap across the four section-article scopes.

Non-goals: dedup against the deterministic UI surfaces (Today's Board etc. showing the same top players as articles is expected -- they are ranked data views, not written analysis); any change to the underlying Sleeper roster ingestion (verified correct -- the wrongness was attribution logic, not data).

### Sprint 20: Task-Based IA -- Entity Pages + View Reorg (checkpoint 1e3ff67)

Goal: reorganize the generated site around user tasks instead of pipeline tables. The 23 data sections became drill-down blocks inside 7 task views (Today / My Team / Players / League / Trade Desk / News / Data Room); element ids stayed stable so `render()` and the string-assertion tests survived. New entity pages -- `#player-{sleeper_id}` and `#team-{roster_id}` hash routes through the extended `showSection` -- assemble the full cross-table read on one player or manager (scores, tags, news, market detail, roster, picks, trade thesis) from the existing client-side bundle, with click-through wiring from every player/team name and a global entity search. Raw tables demoted to data drawers. In v2 this whole surface becomes the per-league drill-down.

### Sprint 21 (v2.0): The Front Office v2 -- Multi-League Triage Product

Goal (per user interview): "run all my fantasy football teams in different leagues" -- login, a cross-league attention queue as the home surface, per-type league experiences, scheduled freshness. Built via four Codex work packages under senior review plus an integration lane.

- **Multi-league data layer** (`src/league_paths.py`, `src/league_registry.py`, Sleeper user/user_leagues endpoints): `LeaguePaths.for_league(id)` namespaces every pipeline artifact under `data/leagues/<id>/`, module path constants stay as legacy defaults; `discover_leagues` + `classify_league` (dynasty / redraft / best_ball from Sleeper settings); `refresh_user` orchestrates per-league refreshes with per-league failure isolation, skipping best ball by design.
- **App server + auth** (`app/`): FastAPI front door with Clerk verify-only auth -- PyJWT RS256 against the Clerk JWKS with pinned issuer, required sub/exp, azp allowlist, throttled kid-refresh; the backend never stores passwords or sessions and never needs the Clerk secret key. SQLite app store (users auto-provisioned by clerk_user_id, user_leagues registry). League sites served at `/league/<id>/` behind ownership-then-containment checks; operator jobs behind the session; open `/healthz` ends the boot-page-satisfies-healthcheck outage class.
- **Attention queue** (`src/attention.py`): typed deterministic emitters per league -- deadline (pending transactions + waiver timing), roster_health (OUT/empty starters), market_window (existing recommendation outputs), quiet (explicit all-clear); severity-sorted cross-league merge; league failures surface as loud items; best-ball leagues emit a quiet "runs itself" card, never a data problem (missing data is their designed state).
- **Phone-first home** (`app/templates/home.html`): the queue as severity-banded cards with house category tokens, league pill strip with type badges + freshness dots, quiet-day divider, Sleeper-link empty state.
- **Scheduler** (`app/scheduler.py`): in-process daemon thread runs refresh_user + queue rebuild on `FRONT_OFFICE_REFRESH_INTERVAL` (default 6h) with status-file observability; LLM articles stay on-demand per league.
- **League-type gating**: `build_browser_site(..., league_type)` emits `<body class="league-{type}">`; redraft hides dynasty-only surfaces via CSS -- one template, no fork.

Verified locally end-to-end before cutover: real multi-league refresh of both dynasty leagues (including one never processed before), 13-item cross-league queue spot-checked against real Sleeper state, authenticated home + drill-downs rendered at 390px in Chrome via a locally-generated-JWKS simulated session (no real secrets), 77 tests green.

Non-goals (deliberate): self-serve signup/billing (Clerk invite-only covers "others someday"); scheduled LLM article generation; redraft/best-ball article scoping beyond the CSS gate (no such league is linked yet).

### Epic 22: Realize the Personal Front Office

The full product-realization plan now lives in
[`docs/front_office_realization_epic.md`](front_office_realization_epic.md).
It supersedes adding isolated presentation features as the next default move.

The ordered vertical slices are:

1. truthful publication receipts and production verification;
2. canonical, fingerprinted evidence packets;
3. structured daily publication driven by generated articles;
4. exact multi-league and roster identity continuity;
5. historical manager dossiers;
6. read-only, counterparty-specific Trade Desk packets;
7. question-led Data Room and entity presentation;
8. versioned responsive media assets;
9. recommendation and editorial outcome feedback.

The first slice is a release gate, not a cosmetic enhancement. Do not run an
expensive content generation cycle until the current bundle can prove which
article artifact it is displaying, whether that artifact is current for its
evidence fingerprint, and whether the selected league and roster are correct.

2026-08-25 checkpoint: the local implementation now has article fingerprints,
content hashes, bundle revisions, generated-article publication cards, reuse
gates, structured manager dossiers, read-only Trade Desk packets, question-led
edition prompts, a versioned responsive masthead manifest, and exact-scope
team-construction presentation reconciled to the economic asset ledger.
The deterministic refresh path also propagates 41 internal proxy market rows
through profiles, signals, and actions with explicit provenance; the local
cross-table mismatch audit is zero.
Production revision `eb9b68d96f40cffa0afec6131547be178d8f1395` passed public
smoke and authenticated browser verification. Revision
`5654d74073656cb3ae225def1572ef74b450d67f` then passed public smoke and an
authenticated scoped league refresh; the private team/player surfaces now
show the proxy market evidence. Release 1 remains open because
production is still in deterministic fallback mode until the
operator-authorized Luna run is completed and its reporter receipts are
verified.

2026-08-25 writer preflight checkpoint: the headquarters now shows the
configured provider, exact Luna model, reasoning effort, API-key readiness,
and separate operator-gate readiness before a generation call. This improves
the protected cost boundary; Release 1 remains open until the operator run
actually produces and verifies all currently registered reporter receipts.

Production acceptance at `f3ea7ce977ae1cd9e42523522ce9a3374f10646e` confirms
the preflight is visible in the authenticated headquarters: OpenAI Luna is
configured, the API key is ready, the operator gate is configured, and the
edition remains honestly at 0/5 until authorization is supplied. The protected
publication run is still the next acceptance boundary.

2026-08-26 manager-depth checkpoint: manager dossier items now include a
deterministic trajectory comparing the latest two observed seasons with the
prior window. The browser exposes distinct snapshot and dossier entry markers,
and the manager article packet receives the same scoped trend object. Activity
and outcome comparisons remain descriptive and carry explicit incomplete-history
and partial-current-season limits.

2026-08-26 newsroom-context checkpoint: Topline Tony's existing `team_report`
scope now includes selected-team players plus current-season league news,
matchup state, and the selected roster's recent trades/waivers. This keeps the
publication at five articles while making the lead reporter's packet capable
of writing the promised weekly topline. The later `horizon_watch` desk expanded
the current contract to six. Tests assert the evidence classes and league/
roster scoping; the protected Luna run remains the paid operational acceptance
step.

## Source And Ownership Contracts

### Layer 0: Raw Sources

Owners:

- Sleeper: league identity, teams, rosters, users, drafts, traded picks, transactions, player cache.
- nflverse: NFL usage, performance, schedules, rosters, depth/snap-style data when available.
- DynastyProcess: open dynasty market values when available.
- RotoWire RSS: player news and article feed if used under RSS terms.
- Sleeper trending: add/drop market reaction.
- LeagueLogs: attributed market/status/blurbs when enabled.
- User-provided files: manually supplied exports with explicit provenance.

Rules:

- Raw payloads must be cached before normalization.
- Raw source shape must remain inspectable.
- Failed sources must create freshness/status rows instead of failing silently.

### Layer 1: Canonical Tables

Owners:

- App normalization code.
- CSV/SQLite in `data/processed/`.

Rules:

- Facts only.
- Preserve IDs, names, timestamps, source names, and source traces.
- No Codex-authored interpretation.

### Layer 2: Derived Analytics

Owners:

- Deterministic app code.

Rules:

- Derived from canonical tables, projection tables, and earlier deterministic transforms only.
- Include evidence and confidence when outputs guide decisions.
- Internal proxies must be labeled.

### Layer 2A: Projection Data Layer

Owners:

- Deterministic projection code.

Rules:

- Converts historical usage/performance and league scoring settings into projected season and weekly fantasy outputs.
- Must preserve projection method, source trace, and confidence.
- Missing or low-confidence projections must be explicit rows or diagnostics, not silent gaps.

### Layer 2B: Transform Signal Layer

Owners:

- Deterministic signal code.

Rules:

- Converts projections, market values, roster context, news, manager behavior, and strategy config into target/sell/watch signals.
- Must produce evidence, risk, confidence, and source trace.
- Must not contain Codex-authored prose.

### Layer 3: Analyst Artifacts

Owners:

- Codex analyst runs.

Rules:

- Interpretation only.
- Must cite projection rows, signal rows, processed facts, or source traces.
- Must include prompt/version metadata.
- Must pass validation before browser display.

### Layer 4: Browser Presentation

Owners:

- Browser generation code.

Rules:

- Views only.
- No hidden source-of-truth changes.
- No transaction execution.
- Must distinguish facts from analyst interpretation.

## Source Policy

Allowed:

- Documented APIs.
- RSS feeds intended for syndication.
- User-provided files.
- Open/legal datasets.
- Paid/API-key sources explicitly configured by the user.

Conditional:

- Paid data sources, if attribution, terms, and access limits are clear.
- Manual exports, if the user supplies them and provenance is recorded.

Disallowed:

- Restricted scraping.
- Hidden/private APIs.
- Paywall bypass.
- Untraceable copied prose.
- Any data source whose terms conflict with local analysis use.

## Contradiction And Risk Register

Run this checklist before every sprint:

- Does this blur source-of-truth ownership?
- Is Codex writing facts instead of interpretation?
- Is a generated artifact being treated as canonical data?
- Does the browser imply a transaction was sent or accepted?
- Is any source missing attribution or access terms?
- Can the sprint still work if one external source fails?
- Does the feature work for any selected `roster_id`, not only Melkor?
- Are raw inputs preserved before transformation?
- Are confidence and risk visible where decisions are suggested?
- Is the refresh path idempotent?

Known current risks:

- Pick values source currently has no successful external feed and may require an internal curve or alternate source.
- News-to-player matching can be ambiguous without Sleeper IDs.
- Analyst prose can overstate confidence unless constrained by validation.
- Hooks and automation need strict guardrails.
- External source terms may change and must be rechecked before deeper integration.
- Browser can become a dense dashboard unless workflows are split into clear front-office views.

## Verification Gate Before Implementation

Before implementing any sprint after this document:

1. Confirm the sprint's requirement and verification pair.
2. Confirm source ownership and layer placement.
3. Confirm table/artifact contract.
4. Confirm browser workflow.
5. Confirm non-goals.
6. Add or update tests before broad implementation.
7. Run the sprint's contradiction checklist.

No sprint should start by adding UI or Codex prose before its data/source contract is clear.

## 2026-08-25 manager outcome depth amendment

The manager dossier foundation now includes an optional Sleeper `matchups`
canonical table and outcome fields in `manager_season_history`. This advances
R12's feedback/history foundation without pretending that a source gap is a
losing record: the deterministic layer reports exact opponent and score
evidence plus `recorded`, `partial`, or `not_recorded` coverage. The browser
renders the receipt and keeps unavailable coverage explicit.

Acceptance checks for the slice are exact roster/opponent normalization,
unplayed and quiet-season handling, dossier source-trace propagation, and a
browser entry-path marker. A scoped production refresh and authenticated
coverage check remain required before counting the outcome layer as live.

Production acceptance amendment (`201c3f7d2d6319dae7bdfc246ebb1f12f9aa3fed`):
public smoke and an authenticated private-browser check passed. The exact
Lulu's Potatoe's / `roster_id=2` manager route rendered `45-37-18` across
108 recorded matchup rows with its source trace. The protected writer remains
a separate pending operator-authorized action.

## 2026-08-26 league-news boundary amendment

The newsroom verification pair now includes a numeric-ID regression: generated
CSV-backed issue rows may represent long league IDs as floats, but the selected
league's News desk must still show its linked rows and exclude another league
with the same roster ID. The source contract carries `league_id` and `season`,
the browser comparison is ID-safe, and local browser verification must report
both the selected-roster count and current-league count before this slice is
considered complete.

## 2026-08-26 publication depth and owner-lineage amendment

The written fallback must remain a useful product before protected Luna
generation: Topline Tony now renders scoped week context and Manager Intel
renders dossier depth rather than only cycle labels. The manager dossier
verification pair also proves that stable Sleeper `owner_id` history survives
a roster-ID change without admitting another owner's repeated roster number.

## 2026-08-26 event-feed identity amendment

`manager_event_log` now preserves `league_id` and `owner_id` from the
canonical `teams` join. The browser Manager Event Log is fail-closed to the
current season, current league, and selected roster, while historical dossier
timelines continue to use stable owner lineage. Acceptance includes repeated
roster IDs across leagues and an owner/league identity regression test.

## 2026-08-26 protected writer scope amendment

The protected team-report packet now applies the same exact league boundary to
news, matchups, trades, and waivers. Long Sleeper IDs that round through a CSV
float remain comparable to their canonical string form, while a repeated roster
ID in another league is excluded. The entry-path test lives beside the article
scope tests and names the identity rule it protects.

## 2026-08-26 matchup calibration amendment

The defensive factor table now includes a later-season holdout receipt, and the
same validation status is visible in player horizons and writer evidence
packets. Limited or non-improving factors remain descriptive context with an
explicit risk rather than being presented as predictive matchup truth.

## 2026-08-26 browser news scope amendment

News impact rows are intentionally repeated across the historical league chain
because one global Sleeper event can affect each league that owns the player.
The player dossier, News Desk, and question-led event pulse now reuse a single
current-league/current-season browser scope instead of filtering by player ID
alone. Acceptance includes a rendered player page with one current signal and
no browser errors after a refreshed bundle.

2026-08-26 four-window market board amendment: the Trade Desk now exposes the
canonical horizon table as a filterable market surface with active-team/league
scope, value-lane filtering, horizon sorting, player dossier routes, and row
level evidence receipts. The browser board is presentation-only and must not
become a second score calculation path.

2026-08-26 horizon receipt amendment: `player_horizon_market_scores` now
includes `horizon_model_version` and `fit_basis`. Writer packets, player
dossiers, and the Trade Desk expose those assumptions so score changes are
versioned rather than disguised as fresh source data.

2026-08-26 horizon scale amendment: `player_horizon_market_scores` now carries
`horizon_score_basis`. Horizon and fit scores are position-relative 0-100
percentiles, not dollar market values or cross-position price rankings. The
browser, fallback analysis, and writer prompts preserve this boundary; market
value and market percentile remain the price-comparison fields.

2026-08-26 counterparty timeline amendment: `counterparty_trade_edges` now
joins the canonical horizon row by exact player and target roster IDs. Each
edge exposes the target team's lens, active team's lens, fit scores, their
spread, the model version, and an explicit read such as
`target_team_timeline_premium`. Trade theses, manager dossiers, fallback
Trade Desk copy, and edge cards/table render this as timeline fit separate
from market price. A missing horizon join remains visible as unavailable and
cannot erase the original counterparty edge.

2026-08-26 dedicated horizon publication amendment: the four-window model now
has its own `horizon_watch` publication packet and deterministic fallback, led by
Market Clock Morgan. The report has separate This Week, Rest of Season, Dynasty
Window, and Contender vs Rebuilder sections. It selects evidence within
position so a position-relative percentile cannot become a misleading
cross-position leaderboard; `market_value` remains the price anchor. The new
desk is additive to Market Watch and Trade Desk, not a replacement for either.

2026-08-26 career-window presentation amendment: the player dossier now
renders `career_projection_score` as its own Career window card with the
five-year projected points, years, blended PPG, status, and age-curve basis.
This is a presentation completion of the existing horizon contract, not a new
score or a claim that the bounded scenario is a lifetime forecast.
2026-08-26 clock-transition amendment: the canonical horizon rows now carry
later-minus-earlier deltas for rest-of-season versus next game, dynasty versus
rest of season, and the five-year career window versus dynasty. The deltas are
not additional scores or prices; they are explicit receipts for market movement
between decision windows. The horizon writer packet, fallback publication,
front-page market panel, board, and player dossier display them, while missing
components remain unavailable rather than becoming zero.

2026-08-26 history-anchored career amendment: the five-year career-window
scenario now blends the current projection with recency-weighted historical
nflverse PPG when a unique normalized-name plus position join resolves to one
source player ID. The horizon receipt exposes the matched source player ID,
join method, status, history depth, latest season, and historical PPG.
Ambiguous or missing history falls back to the age-only scenario with an
explicit limitation. The formula is versioned as `horizon_market_v2`; the
Sleeper player ID remains canonical.

## 2026-08-26 counterparty audience follow-through

The active-asset side of the counterparty workflow is now implemented as the
`counterparty_asset_interest` table. It ranks conversation priorities for
players on the selected roster using an exact historical position lane, current
target-team need, and target-versus-active horizon fit. The score is explicitly
not market value, intent, willingness, or a predicted response. Trade theses,
the Trade Desk, manager dossiers, and the trade writer packet consume the same
rows, keeping this as an evidence join rather than a second browser-only model.

## 2026-08-26 available-market cohort amendment

The Draft Room's available-market clock rows now reuse the current refresh's
deterministic projection cohort when those projection tables are present. A
candidate already represented in the refresh is replaced with its
availability-scoped row before scoring, and the final board is filtered back to
the exact canonical IDs proven absent from the selected league roster. Market
percentiles are calculated from the full market table by position rather than
the filtered available subset. This prevents a thin free-agent pool from
manufacturing a misleading midpoint or from presenting another manager's
player as available. The surface remains a research board, not a waiver
eligibility receipt.

## 2026-08-26 market-clock publication amendment

The available-market table now has a real publication entry path. Waiver Wire
Waverly receives identity- and league-scoped available rows inside Market Watch,
with this-week, rest-of-season, dynasty, and career-window scores plus their
transition deltas, fit coverage, and price anchor. The front page also reserves
one market card for an available clock when the evidence is complete enough to
show, keeping the research lane visible without pretending roster absence is
waiver eligibility. Market Clock Morgan remains the dedicated league-wide
four-window desk; this adds a reader path over the same deterministic table
rather than another scoring engine or a paid generation call.

2026-08-26 horizon trust-gate amendment: the player board now uses comparable
percentile meters for the four clock scores, with explicit unavailable states
and the evidence receipt still one click away. The homepage shelf exposes all
six publication desks. `validate_local_data.py` now fails closed when horizon
scores leave the documented 0-100 scale, clock coverage disagrees with the
row, or a transition delta does not reconcile to its endpoints. These checks
protect the evidence seam but do not substitute for a future outcome-calibration
study based on dated snapshots and realized results.

2026-08-26 horizon feedback amendment: each refresh now appends the deterministic
horizon rows to `horizon_snapshot_history.csv` using a scope/season/week/player/
model key, and builds `horizon_score_accuracy.csv` when later nflverse usage can
be joined unambiguously. The artifact evaluates next-game and active
rest-of-season rank evidence by position, while explicitly leaving dynasty,
career, and contender/rebuilder fit ungraded until their proper longitudinal
labels exist. Initial cold-start output is allowed to be empty and is surfaced
as such; no missing game row is converted into zero, and no rank correlation is
presented as a calibrated probability.

The same refresh also builds `horizon_market_movements.csv`: a deterministic
reader receipt comparing the current four-window row with the latest earlier
exact-scope snapshot. It is intentionally empty on the first run and ignores
same-week reruns. This powers a “what moved?” path without introducing a fifth
score or letting editorial prose stand in for the underlying snapshots.

2026-08-26 horizon repricing-lead amendment: each canonical horizon row now
records next-game, rest-of-season, dynasty, and career-window percentile minus
same-position market-percentile deltas. The fields are explicit same-position
research leads, not dollar gaps or a universal ranking, and the browser and
writer packets keep `market_value` as the cross-position price anchor. The
local validator reconciles each populated delta to its clock score and market
percentile.

2026-08-26 four-window repricing follow-through: the live product label now
matches the four available decision windows, and the deterministic publication
has a dedicated Market vs Clock section. The Trade Desk can sort each
position-scoped board by largest absolute disagreement, strongest clock lead,
or strongest market lead. This keeps the new analysis actionable without
introducing a second valuation formula or implying that a percentile delta is a
dollar mispricing.

2026-08-26 counterparty repricing bridge: `counterparty_trade_edges` and
`counterparty_asset_interest` now carry the four canonical horizon scores,
clock-minus-market deltas, and the largest same-position disagreement window.
The Trade Desk and trade decision packets can therefore connect a manager's
timeline fit to a specific research lead while leaving the existing trade and
conversation scores unchanged. Missing horizon joins stay unavailable rather
than being filled by inference.

## 2026-08-26 personalized fit-weight amendment

Contender and rebuilder fit now accept optional private
`strategy_profile.horizon_fit_weights` maps. The four canonical horizon scores
remain unchanged; only the team's personalized combination is adjusted. Values
are normalized, malformed lanes fail closed to the documented defaults, and
the resulting `fit_basis` receipt records whether the profile was default,
custom, mixed, or invalid. The profile editor exposes the JSON for a league
owner, and the database merges updates so saving this preference cannot erase
other private strategy notes.

2026-08-26 availability receipt follow-through: `availability_scope` now
travels from normalized roster rows into player dossiers and horizon rows, and
the browser shows the current-Sleeper-versus-historical-unavailable boundary
in player and horizon evidence. This preserves provenance without adding a
recovery heuristic or changing the four-window score model.

2026-08-26 market-quality receipt follow-through: the horizon row and its
append-only snapshot now preserve market source count, component disagreement,
and consensus confidence. The Trade Desk, player page, available-market packet,
and fallback horizon publication expose that receipt so a clock-versus-market
lead is read in proportion to the quality of its price anchor. The receipt is
diagnostic context, not a new score or a market rescaling rule.
The local validator accepts only a complete receipt or an explicitly
unavailable one, so malformed or partial market-quality evidence cannot pass
into the reader surface.

2026-08-26 market-input follow-through: optional
`external_sources.market_value_files` entries now provide a documented,
user-supplied canonical market-source seam. The refresh labels each file,
preserves its manual trace, and includes it in component consensus without
scraping restricted sources or rescaling values by magnitude.
2026-08-26 horizon identity/readability checkpoint: every horizon row now
carries its explicit league scope, and the scoped Sleeper roster supplies
roster identity before projection labels are used. Existing horizon snapshots
are migrated additively from their scope key. The Four-Window Market Read now
keeps one representative lead per position and caps its disagreement and fit
queues; complete evidence remains in the data room. Current injury flags
qualify rest-of-season PPG as a conditional baseline rather than a
recovery-adjusted forecast.

2026-08-26 horizon decision-view presentation slice: the browser board now
supports focused views for this week, rest of season, dynasty/career,
contender versus rebuilder, and repricing leads. Each view chooses its useful
default sort and concise card treatment over the same canonical row. The
full evidence receipt remains available, and the view does not imply that
position-relative percentiles are cross-position prices.

2026-08-26 terminology follow-through: Signal Board and trade-table headers
now state whether a number is a position-relative percentile, a horizon
window, a fit/conversation priority, or the cross-position market price
anchor. This closes a second presentation path for the same score-versus-
price confusion without changing the deterministic formulas.

2026-08-26 inspectable writer generation plan: the operator now provides a
protected read-only preview of the six-desk publication run. It uses the
actual evidence scopes and receipt-reuse predicate to show which desks would
generate, reuse, remain deterministic, or be blocked, with no provider call.

2026-08-26 horizon smoke contract amendment: revision-aware authenticated
smoke now requires the static Four-Window Market Board entry markers and the
owned bundle's canonical horizon, available-market, manager-dossier,
manager-season, and asset-ledger tables. This prevents a deployment from
passing generic health and publication checks while serving a structurally
valid but shallow reader shell.

2026-08-26 writer-plan parity amendment: the protected no-cost writer preview
now shares a stable evidence fingerprint with the paid multi-desk workflow.
Peer and previous-edition prose remains bounded editorial context, but it is
excluded from the reuse key because a preview cannot know newly generated peer
copy. The plan replays reused upstream sections and explicitly defers summary
generation when a preceding desk is changing, with an entry-path regression
proving parity after a full newsroom run.

2026-08-26 newsroom packet and retry amendment: complete manager dossiers remain
deep deterministic artifacts, but provider packets are bounded to relevant
history and fit evidence. The explicit generation workflow supports a scoped
desk retry, and the reader persists a first-class source receipt for each LLM
article so the media facade can open the evidence path without regenerating
copy.

2026-08-26 article-boundary gate amendment: the writer validator now checks
the rendered narrative against the same evidence packet for high-risk
availability language. An article is held when it gives a player with no
current NFL team an unqualified projection or PPG claim; injury-sensitive
rest-of-season production receives a visible missing-caveat warning. This is
an editorial seam check, not a new projection model, and it keeps historical
context useful without letting it masquerade as current production.

2026-08-26 projection availability amendment: current Sleeper availability
now travels through source components, season consensus, and weekly allocation
rows. Browser projection labels use `conditional baseline PPG if signed` for a
player with no current NFL team and `if active` for injury-sensitive rows.
The local validator requires this context on every projection contract, so a
stale artifact cannot silently turn historical production into a current
forecast.

2026-08-26 newsroom progress amendment: asynchronous six-desk runs now write
compact per-desk progress receipts and expose the configured model/reasoning
configuration while work is in flight. Browser polling covers the expected
multi-call duration, but completion still requires the durable per-article
writer/editor receipts and revision-aware authenticated production check.

2026-08-26 current-role percentile amendment: the legacy signal layer now
excludes current Sleeper no-team players from the projection percentile cohort
and leaves their own current projection percentile and market-gap signal
unavailable. Their historical baseline remains visible as conditional research
context, while active players are ranked against current-role peers. This
closes a subtle path where a free-agent veteran could distort an otherwise
current projection-versus-market read.

2026-08-26 opportunity-scope amendment: nflverse usage remains a global fact,
but `player_opportunity_scores` now scopes the Sleeper join to the selected
current season and league before attaching roster identity. The output carries
`league_id`, the local validator rejects mixed or duplicate league/player
joins, and the Data Room's usage/output disagreement question uses the exact
selected-roster player set. This keeps a deep historical archive from leaking
an arbitrary team label into a current signal.

2026-08-26 market-price presentation amendment: the Four-Window Market Board
now includes an explicit cross-position Market Price view. It sorts by the
canonical `market_value` anchor, keeps missing prices below priced rows, and
labels the four clock values as secondary position-relative percentiles. This
separates the universal price question from the clock and roster-fit questions
without adding another valuation formula.

2026-08-26 manager-dossier entry-path amendment: the Manager Room now renders
all structured manager dossier items instead of truncating the combined
Markdown artifact to an 18-line preview. Each roster receives an evidence
summary and an exact team-page link; the full structured dossier remains the
depth surface. The Markdown artifact is a complete fallback only when the
structured payload is unavailable.

2026-08-26 manager-intel navigation amendment: the deterministic Manager
Intel fallback now previews five evidence-ranked dossiers as a compact
homepage entry point and links to the complete structured index. This keeps
the media facade readable without discarding the validated manager depth;
current LLM copy remains authoritative when its receipt is current.

2026-08-26 Sleeper-lineage receipt amendment: authenticated user-league rows
now carry the resolved Sleeper user ID into scoped context and the browser
identity receipt. The exact `roster_id` remains the team selector; the added
lineage field makes the promised Clerk -> Sleeper -> league -> roster chain
inspectable at the reader boundary.

The durable-bundle migration check also invalidates a current-SHA bundle when
that linked Sleeper lineage is missing from the manifest or app payload.

2026-08-26 targeted-retry amendment: the protected Writer Desk now exposes a
real entry path for retrying only failed or held reporter desks. The API
validates the selected `article_keys`, requires an owned league, and forwards
them into the evidence-backed workflow. The homepage does not invent targets
when a refresh-stage failure has no per-desk receipt; it falls back to the
normal full-edition action.

2026-08-26 selected-writer launch amendment: the browser now refuses to send
the selected-edition writer request when the exact league selector is empty.
Because the API intentionally interprets a missing `league_id` as an
all-edition run, the previous UI fallthrough could widen an ambiguous click
into a paid aggregate request. Aggregate generation remains available only
through its explicit all-editions control.

2026-08-26 authenticated-shell receipt amendment: the private headquarters
HTML now exposes the deployed source revision as a safe meta tag and body data
attribute. Browser verification can therefore detect a stale open shell in
addition to checking the private edition manifest and content receipts.

2026-08-26 production acceptance amendment: revision-aware public smoke and a
fresh authenticated headquarters navigation matched commit
`bef160de254ca9d28eeef5c55c7f2f3fe067838a`, including the selected-edition
writer guard and current `Lulu’s Potatoe’s` identity. The protected Luna run
has not yet produced article receipts; Release 1 remains open on that paid
publication proof.

2026-08-26 generated-bundle writer receipt amendment: the static league
edition's legacy operator surface now binds polling to the accepted durable
`run_id` and fails closed on a missing or different receipt. This keeps the
league route aligned with the authenticated headquarters and prevents stale
writer status from masquerading as a current run. Local bundle contract tests
pass; production paid-publication verification remains outstanding.

The authenticated smoke gate now requires the direct league shell's run-ID
binding markers, making the duplicate writer entry path part of deployment
verification rather than a manual-only check.
