# Sleeper Dynasty Front Office Sprint Plan

This document is the project control surface for building the full Sleeper dynasty front office app. It sits above `docs/data_contract.md`: the data contract defines current table/source rules, while this sprint plan defines the ordered path, V-model checks, source boundaries, and contradiction checks for future work.

## Product North Star

Build a browser-first, read-only Sleeper dynasty front office that combines league data, market economics, news intelligence, manager behavior, and Codex-authored analyst interpretation.

The app should help a dynasty manager understand:

- what the league data says
- what the market is mispricing
- which managers behave in exploitable ways
- which news items create trade windows
- what the analyst layer thinks, with evidence and confidence

Core invariants:

- Sleeper is the league source of truth.
- Raw data is preserved before normalization.
- Deterministic app code owns facts.
- Codex owns interpretation only.
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
| R6: Codex analyst layer | Let Codex write briefs, trade theses, and manager dossiers from processed data only. | V6: analyst artifact validation confirms source trace, evidence, risk, confidence, and no unsupported claims. |
| R7: Automation and hooks | Run refresh, validation, and analyst generation safely on schedules or guarded hooks. | V7: automation dry-run/guardrail tests confirm no destructive actions or external transaction side effects. |
| R8: Browser-first front office | Make the browser the main workflow, with team-scoped pages and diagnostics. | V8: browser smoke and team-scope tests confirm core controls, views, and selected-team behavior. |
| R9: Recommendation packet auditability | Produce read-only recommendation packets with evidence and confidence. | V9: packet tests require action type, assets, evidence, risk, confidence, source trace, and read-only wording. |
| R10: Feedback/market memory | Track what the app believed, what happened later, and which signals were useful. | V10: outcome/history idempotency tests confirm reruns replace outputs without duplicate history rows. |

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

### Sprint 4: Codex Analyst Layer

Goal: Add Codex as an interpretation layer over processed facts.

Key deliverables:

- Add `data/analysis/` as a separate generated artifact layer.
- Build analyst context packets from processed CSV/SQLite data.
- Add controlled prompts for daily GM brief, trade desk, manager dossiers, and news impact memo.
- Validate analyst artifacts before browser display.

Data contracts:

- Add `daily_gm_brief.md`.
- Add `trade_theses.json`.
- Add `manager_dossiers.md`.
- Add `news_impact_brief.md`.
- Add prompt/version metadata to each artifact.

Browser changes:

- Add Analyst Brief section.
- Add Manager Dossiers section.
- Label all Codex-generated content as analyst interpretation.

Tests:

- Analyst artifact shape validation.
- Required evidence/risk/confidence fields.
- Guardrail test that analyst output cannot claim a trade was sent, accepted, or executed.

Acceptance criteria:

- Codex can regenerate analyst artifacts from processed facts.
- Canonical tables are not mutated by Codex.
- Browser clearly separates facts from interpretation.

Non-goals:

- No autonomous outbound messages.
- No hidden prompt runs that write into canonical data.

### Sprint 5: Automation And Hooks

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

### Sprint 6: Browser Product Upgrade

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

### Sprint 7: Recommendation Packets

Goal: Formalize read-only action packets.

Key deliverables:

- Generate recommendation packets from economics, manager behavior, news impact, and strategy overlay.
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

### Sprint 8: Feedback And Market Memory

Goal: Let the app track whether its reads were useful over time.

Key deliverables:

- Store dated market snapshots and recommendation outcomes.
- Track manager prediction history and analyst decisions.
- Add review views for what changed and whether prior reads were right.

Data contracts:

- Add `market_snapshots`.
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
- Manager behavior labels become inspectable over time.

Non-goals:

- No opaque self-modifying model.
- No automatic strategy changes without review.

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

- Derived from canonical tables only.
- Include evidence and confidence when outputs guide decisions.
- Internal proxies must be labeled.

### Layer 3: Analyst Artifacts

Owners:

- Codex analyst runs.

Rules:

- Interpretation only.
- Must cite processed facts or source traces.
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
