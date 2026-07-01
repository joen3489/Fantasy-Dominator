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

Core invariants:

- Sleeper is the league source of truth.
- Raw data is preserved before normalization.
- Deterministic app code owns facts.
- Codex owns interpretation only.
- Projection models and signal transforms are deterministic app code, not analyst prose.
- No trade execution, message sending, or Sleeper mutation.
- Browser is the primary workflow surface.
- CSV, SQLite, JSON, markdown, and raw files are audit artifacts.
- Every meaningful output must be scoped to any selected `roster_id`, not only Melkor.

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
