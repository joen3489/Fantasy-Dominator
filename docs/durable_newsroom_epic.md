# Epic: Durable Newsroom and Editorial Intelligence

Status: in progress — execution slices 1-6 locally implemented; authenticated production acceptance remains
Date: 2026-08-27
Owner: Fantasy Dominator product
Scope: one authenticated manager, one or more private Sleeper league editions

## Execution update — 2026-08-27

The first implementation slice is now in the repository. It adds additive
`edition_runs` and `edition_jobs` tables, records per-desk writer/editor
attempts with safe provider timing/request telemetry, carries the durable run
ID through operator progress and restart recovery, and exposes the ledger in
the authenticated status surface. The homepage now renders a deterministic
conversation spine across the specialist desks, with fallback copy labeled as
Front Office copy while still showing the assigned lens. The roster also now
includes Reality Check Riley as a verification/editorial lens; it is not yet a
seventh paid article call.

The second implementation slice now adds an authenticated same-run resume
action. It reuses the durable `run_id`, selects only unfinished writer/editor
jobs, skips a second refresh when the run already has durable jobs, and
publishes the repaired bundle only after the ledger is terminal. A persisted
`publication_edges` graph carries structured newsroom relationships into the
database, while the reader now renders a visible “The room is talking” rail
with bylines, sequencing, evidence counts, and links into the full reports.
The horizon desk runs before the daily brief so the flagship synthesis can
actually see the long-window specialist output. Persona metadata now includes
an evidence scope, excluded scope, and required counter-signal so the roster
is differentiated by information responsibility rather than only tone.

The current continuation adds a deterministic `reality_check.json` packet to
the analysis artifacts and carries it through preserved shell rebuilds,
Diagnostics, the Data Room, and the front-page Reality Check panel. It records
exact league/season/roster scope, stable evidence IDs, source traces, and
availability, identity, projection, market, dossier, and freshness limitations.
Reporter lenses now travel with scenario, priority, signal, counterparty,
horizon, player, and manager surfaces so a reader can see which desk owns the
question instead of treating every card as anonymous dashboard output.
Unchanged held writer drafts can now be rehydrated for an editor retry without
spending another writer call. The durable ledger also has additive run/job
leases with exclusive claim, heartbeat, expiry, and resume behavior, providing
the seam required for a future Railway worker without pretending SQLite is
already a safe multi-worker queue.

The sixth implementation slice now adds bounded specialist fan-out, a
Railway-compatible `scripts/newsroom_worker.py` entrypoint, API queue mode,
worker-owned run/job leases, cooperative cancellation, bounded retries, and
dead-letter receipts. The daily brief remains a serialized issue-level
synthesis after specialist output; this preserves the room's ordering while
only the independent provider calls fan out. Reality Check limitations now
travel into writer evidence and article receipts, high-severity actionable
claims are held without a local caveat, and the issue summary surfaces
counter-signals and open questions. Authenticated production verification
remains open.

The latest execution slice adds the run-scoped immutable edition packet. It
hashes the exact processed and analysis inputs, records the selected
Clerk/Sleeper/league/roster scope, carries freshness and Reality Check
receipts, and is persisted both beside the run and in the durable edition
ledger. A resume now fails closed when those inputs or the packet itself have
changed instead of mixing completed articles from one snapshot with unfinished
articles from another. The front-page rails also carry their owning desk,
question, and information contract; the Team Pulse rail now includes the
exact latest matchup receipt under Topline Tony. The room summary separately
reports supported handoffs, disagreements, and open questions, while the daily
brief marks prior desk prose as editorial context rather than new evidence.

Slice 0 is now executable locally through `src/newsroom_evaluation.py` and
`scripts/evaluate_newsroom.py`. The fixed regression pack under
`tests/fixtures/newsroom_eval/reference.json` measures required evidence and
source coverage, desk/horizon assignment, information-contract distinctness,
unsupported certainty, and per-run comparison deltas. It intentionally reports
usefulness as `not_scored` until a recommendation outcome is observed. When it
inspects already-published markdown, it reports whether the complete frozen
writer packet is persisted. Each current deterministic fallback and successful
writer/editor publication now carries a bounded privacy-safe
`evidence_manifest_json` receipt containing stable IDs, source IDs, freshness,
availability, horizon, and decision fields while excluding prompt prose and
raw supporting rows. Run/job timing and usage are written separately to
`edition_receipt.json`, so mutable execution telemetry cannot alter the
immutable input packet. The Data Room exposes both receipts, and the
evaluator fails closed on citations outside the persisted article manifest.

The latest data-depth slice preserves Sleeper's nested `players_points` and
`starters` fields as the canonical `matchup_player_points` table. Player pages
and Topline Tony can now answer who supplied a team's points from exact
matchup evidence; placeholder 0-0 rows remain explicitly unplayed. Reality
Check also emits a same-position clock/market warning only when a usable
multi-source market receipt exists, while single-source comparisons are
marked as calibration-limited. The packet now retains the position-relative
comparison basis, source count, confidence, clock window, and delta for each
market warning, plus an issue-level market-quality receipt. This keeps the
market desk useful without turning a WR-vs-QB percentile display into a
universal ranking.

The current continuation adds a bounded structured claim register to every
writer/editor tool contract. Material positions now carry an exact evidence
ID set, decision window, stance, subject, and short summary. The deterministic
issue compiler compares positions only when subject and window match, reports
unresolved or explicitly disputed reads without choosing a fake winner, and
lets a high-severity Reality Check limit the resolution. The front page and
Data Room can therefore show a running conversation with a receipt for each
side of a disagreement.

The execution ledger now also persists a stable, privacy-safe internal client
request ID for each run/article/phase. It is retained across retries and shown
alongside the provider response ID when available. This closes the traceability
gap between a durable desk job and individual provider attempts without
claiming provider-side idempotency.

The writer-room continuity seam now keeps prior specialist articles in a
separate non-evidence context channel. A full run can give each specialist a
bounded view of the last room before fan-out, while the daily brief receives
only specialist outputs completed in the current run. A targeted summary retry
may explicitly reuse prior desk receipts when no current specialist output is
being regenerated. This keeps continuity and disagreement useful without
letting stale prose masquerade as current-run evidence.

The current reader-integration slice adds a bounded `writer_fragment_v1`
projection to each publication. It contains the approved or evidence-led
fallback headline, thesis, action, reporter attribution, status, and stable
evidence/source IDs, but never leaks held draft prose. Front-page panels reuse
that same fragment and link to the full desk report; the newsroom conversation
also reads from it. This spreads the desks through the product without creating
one provider call per placement or letting a template parse prose into a new
fact model.

The issue hero now follows the same rule: when the Daily GM Brief is printable,
its structured fragment supplies the hero headline, thesis, action, and byline.
The hero may fall back to deterministic priority copy only when the publication
is unavailable or held, keeping reporter attribution and copy provenance
aligned.

## Outcome

Fantasy Dominator should feel like a living private newsroom, not a button that
occasionally produces six similar articles. A manager should be able to open a
league edition and see an ongoing, evidence-backed conversation:

```text
validated league packet
  -> independent specialist desks
  -> explicit counterpoints and questions
  -> desk/editor review
  -> front-page synthesis
  -> inline routes to the data room
  -> durable edition and outcome history
```

This epic joins two problems that must be solved together:

1. **Durable execution:** a slow or interrupted provider call must not erase
   progress, strand the run at `1/6`, or require regenerating work that already
   succeeded.
2. **Editorial intelligence:** each desk must answer a different manager
   question using a different evidence slice. Personalities should make those
   answers enjoyable, but personality is not a substitute for information
   design.

The finished slice will let the product show what each reporter believes, what
another reporter disputes, what the editor accepted, and which evidence supports
the disagreement.

## Product laws

These rules extend `AGENTS.md`, `docs/front_office_principles.md`, and
`docs/reporter_personas.md`:

1. **One immutable edition packet.** Every writer and editor receives the same
   selected league, exact roster, validated evidence fingerprint, freshness
   receipt, and scope. A writer may choose emphasis; it may not recalculate or
   replace deterministic facts.
2. **One job per meaningful question.** A new call is justified by a distinct
   decision, audience, or evidence selection—not by a second tone of voice for
   the same answer.
3. **Independent desks, explicit room context.** Writers may receive bounded
   prior or peer excerpts to create continuity and disagreement. Room context
   is editorial context, never evidence.
4. **The editor protects the facade.** Deterministic validation always runs.
   LLM review may repair framing, caveats, horizon confusion, or unsupported
   certainty, but may not add facts, scores, motives, transactions, or sources.
5. **The front page is a synthesis, not a seventh copy of the same article.**
   The daily brief should organize the issue, surface disagreement, and point to
   the best next decision. It should not repeat five desk summaries at length.
6. **A fallback is visible.** Generated, editor-held, deterministic fallback,
   unavailable, and unchanged are separate product states. The UI must never
   make an assigned reporter look like the author of fallback copy.
7. **A run is restartable.** Each article and editor step has its own durable
   status, attempt, provider receipt, timing, and evidence fingerprint. Retrying
   one desk must not rerun the refresh or regenerate completed desks.
8. **The data-room route is part of the story.** Every material claim, counterpoint,
   and disagreement has evidence IDs, source IDs, freshness, and a path to the
   underlying player, team, matchup, transaction, projection, or source receipt.
9. **Publication retains proof.** A printed article must retain a bounded
   evidence manifest, and the edition must retain execution telemetry; a
   self-reported citation list without the persisted boundary is not proof.
10. **Attribution precedes narrative.** Matchup stories may describe player
    contribution only from exact Sleeper player-point receipts. A missing or
    placeholder score is an unavailable/unplayed state, never an implied zero
    performance or a writer-generated explanation.

## Target editorial roster

The current six desks are a good starting point. This target roster changes the
information each desk owns before changing its voice. The proposed addition is
the **Reality Check** desk, which addresses the exact class of regressions that
can make a polished article untrustworthy.

| Desk | Primary manager question | Canonical evidence responsibility | Product placement | Cadence |
| --- | --- | --- | --- | --- |
| **Topline Tony** | What matters for my team this week? | Current availability, next matchup, lineup pressure, recent moves, weekly stakes | Lead story, matchup rail, today view | Every current edition |
| **Waiver Wire Waverly** | What changed in the available market, and who fits my roster? | Available players, role and usage changes, news, roster needs, four-window fit | Waiver rail, available-market board, player cards | On refresh and current-season change |
| **Trade Desk Talia** | Who could be a realistic trade partner, and what could create value? | Counterparty needs, roster construction, manager history, asset fit, open trade theses | Trade rail, opponent cards, trade desk | On material market or roster change |
| **Market Clock Morgan** | Where do market price and decision-window value disagree? | Cross-position market price, next game, rest of season, dynasty, career window, contender/rebuilder spread | Market board, valuation callouts, player dossiers | On market or projection change |
| **Look-Ahead Lonnie** | What should I prepare for before everyone else sees it? | Playoff paths, schedule windows, deadlines, age curves, stashes, future scarcity | Strategy rail, horizon cards, long-view article | Each issue, with reuse when unchanged |
| **Dossier Dana** | What kind of team and manager is this over time? | Stable owner lineage, roster construction, transactions, trade behavior, season trajectory | Manager Room, team cards, counterparty context | Slow update on historical-input change |
| **Reality Check Riley** | Which signal deserves skepticism before I act? | Source freshness, availability conflicts, projection caveats, unresolved joins, market anomalies, model coverage | Data Room alert rail, evidence drawer, editor packet | Every refresh; mostly deterministic |
| **The Desk Editor** | What can be printed, what conflicts, and what deserves the front page? | All validated packets plus draft metadata; no new facts | Editor note, publication status, issue synthesis | After desk drafts |

### Current-to-target migration

The existing keys remain stable during migration:

- `team_report` remains Topline Tony.
- `market_watch` remains Waiver Wire Waverly.
- `horizon_watch` remains Market Clock Morgan.
- `trade_desk` remains Trade Desk Talia.
- `manager_intel` remains Dossier Dana.
- `daily_brief` becomes the issue-level front-page synthesis after the
  specialist desks finish. Look-Ahead Lonnie owns the long-view evidence lane;
  the daily brief should no longer duplicate that lane merely because it has a
  different byline.
- `reality_check` is a proposed new desk. It should begin as a deterministic
  data-quality packet with optional LLM explanation, not as a free-form opinion
  writer.

No proposed desk becomes an active code contract until its evidence scope,
output schema, entry path, and tests exist. This prevents the persona document
from promising writers the implementation cannot actually deliver.

## Call and workflow architecture

### Run phases

1. **Create run.** Persist a run ID, authenticated user, league ID, exact
   `roster_id`, requested mode, and idempotency key.
2. **Refresh and freeze.** Run the appropriate bootstrap or maintenance path,
   validate source freshness and joins, and create an immutable edition packet.
3. **Plan.** Compare evidence fingerprints and current receipts. Mark each desk
   as `reuse`, `generate`, `unavailable`, or `blocked` before spending tokens.
4. **Fan out specialist desks.** Submit one independent job per changed desk.
   Start with bounded concurrency of two or three jobs after evidence scoping is
   deterministic and shared mutable context has been removed.
5. **Checkpoint.** Persist the raw provider receipt, request ID, timing, usage,
   output, validation result, and final desk state before acknowledging the job.
6. **Review.** Run the deterministic gate on every draft. Invoke the paid LLM
   editor only for the configured review policy: all desks for a deliberate
   premium run, or flagged/low-confidence desks for an economical maintenance
   run.
7. **Synthesize.** Generate `daily_brief` after the specialist desks. Supply
   their bounded headlines, theses, counter-evidence, and evidence IDs as room
   context. The synthesis must identify agreement, disagreement, and the next
   manager question rather than rewrite every article.
8. **Publish.** Update the private manifest only after the relevant article and
   editor receipts pass. A partial issue remains readable, but its missing or
   held desks are explicit.
9. **Learn.** Record article opens, manager feedback, recommendation outcomes,
   source limitations, and realized horizon results without treating an open or
   click as proof that a recommendation was correct.

### Provider strategy

- Keep the provider boundary in `src/llm.py` and use strict structured output.
- Use a stable client request ID per `run_id` and `article_key`; record the
  provider request ID and rate-limit metadata when available.
- Keep static system/persona/schema material at the front of the prompt and
  selected dynamic league evidence at the end to improve prompt-cache reuse.
- Compare `max` with `xhigh` or a lower effort on representative article evals.
  The product target remains Luna, but maximum reasoning should be earned by a
  measured quality gain rather than assumed to be better for every desk.
- Consider OpenAI Background Responses for unusually slow individual calls;
  store the response ID and poll it from the durable job rather than holding a
  web request open.
- Use OpenAI Batch only for non-urgent overnight maintenance or evaluation
  work, never for the interactive “write today’s edition” button.

### Durable execution choice

The current in-process daemon runner is acceptable for local iteration but is
not the production end state. It can lose in-flight work when Railway restarts
the web service.

Implement in two steps:

1. **Proportional first step:** make every desk job restartable and idempotent
   using the existing durable application store. Add startup reconciliation that
   resumes unfinished article jobs rather than merely labeling them interrupted.
2. **Production worker step:** separate the API from a Railway worker. The API
   creates a run and returns its ID; the worker consumes article jobs, updates
   durable state, and publishes the manifest. Use Redis plus Postgres if a
   separate worker needs shared queue and state infrastructure. Do not attach a
   second worker to the current private SQLite volume without proving the storage
   semantics.

Temporal is a valid future option if the product grows into many workflows,
generated media, scheduled research, and multi-step approvals. It is not a
 prerequisite for this personal newsroom.

## Product integration: make the page feel like a conversation

The page should not show six isolated article blocks. It should reuse structured
article fields throughout the reader:

### Front page

- A “Question of the day” or “What changed?” lead from the front-page synthesis.
- A visible byline, declared lens, mode, freshness, and confidence badge.
- A compact “The room” rail with one supporting take and one explicit
  counterpoint.
- A “What the editor held back” or “Why this is uncertain” note when applicable.
- A single clear action/question, followed by a link to proof.

### Team and player surfaces

- Inline reporter chips on players, teams, matchups, and trade targets.
- Topline Tony on weekly matchup and lineup cards.
- Market Clock Morgan on four-window valuation cards.
- Trade Desk Talia on counterparty and fit cards.
- Waiver Wire Waverly on available-player cards.
- Look-Ahead Lonnie on stash, schedule, and playoff rails.
- Dossier Dana on opponent/team cards.
- Reality Check Riley on stale, conflicting, or limited data receipts.

### Conversation contract

Represent editorial relationships explicitly rather than fabricating dialogue:

- `supports`
- `disputes`
- `extends`
- `asks`
- `supersedes`
- `held_because`

Each relationship stores the source article, target article, evidence IDs, and a
short editorial explanation. It must be clear whether a reporter is responding
to another reporter or merely reaching the same conclusion independently.

### Writer fragment contract

`writer_fragment_v1` is the only reader-facing excerpt contract for a desk
publication. It is derived after the deterministic publication/editor gate and
may appear in more than one placement. A fragment must retain `article_key`,
`status`, `mode`, reporter and assigned-lens names, a bounded headline/thesis/
action, evidence and source IDs, and the evidence fingerprint. Approved and
deterministic-fallback fragments may carry copy; held, unavailable, and missing
fragments may carry status and lens metadata only. A panel, card, or question
rail may link to a fragment's article, but it must not make a second provider
request for a new paraphrase.

## Durable objects and minimum fields

Use additive, idempotent migrations. Existing `content_artifacts` remains the
publication record; new run/job objects should make the execution seam explicit.

### `edition_runs`

- `run_id`
- `user_id`, `league_id`, `roster_id`
- `edition_fingerprint`
- `requested_mode`
- `state`, `stage`, `started_at`, `completed_at`, `last_heartbeat_at`
- `max_attempts`, `cancel_requested_at`, `lease_until`, `worker_id`
- `source_receipt`, `bundle_revision`
- `failure_class`, `failure_message`

### `edition_jobs`

- `job_id`, `run_id`, `article_key`, `phase`
- `state`, `attempt`, `lease_until`, `started_at`, `completed_at`
- `evidence_fingerprint`, `prompt_version`
- `provider`, `model`, `reasoning_effort`
- `provider_request_id`, `client_request_id`
- `input_tokens`, `cached_tokens`, `output_tokens`
- `editor_decision`, `content_hash`, `error_class`

### `publication_edges`

- `run_id`, `source_article_key`, `target_article_key`
- `relationship`, `summary`
- `source_evidence_ids`, `created_at`
- `status` (`visible`, `held`, `stale`)

The UI can remain bundle-oriented while these objects give the server a durable,
queryable source for status, receipts, and conversation rendering.

## Execution slices

### Slice 0: baseline and evaluation set

- Capture representative historical league packets and current regressions.
- Define scores for factual accuracy, evidence coverage, horizon correctness,
  usefulness, voice distinctness, and unsupported certainty.
- Record current call duration, token usage, failure type, and cost proxy.

Acceptance: the same fixtures can compare prompt, model, effort, and roster
changes without guessing whether an article improved.

### Slice 1: durable run and article job contract

- Add run/job state and per-call heartbeat fields.
- Separate provider timeout, validation failure, editor hold, and process
  interruption.
- Make retries target unfinished desks only.
- Add startup recovery and a visible status timeline.

Acceptance: intentionally interrupt a run after two completed desks; an
authenticated resume action continues the same run, retries only unfinished
writer/editor jobs, and does not regenerate completed desks or publish an
unapproved artifact. Automatic paid work is not started blindly on process
boot; the operator must explicitly resume a cost-incurring run.

### Slice 2: specialist roster and evidence scopes

- Formalize the target roster and add the Reality Check packet.
- Give each desk an explicit `question`, `decision_lens`, `primary_evidence`,
  `excluded_evidence`, and `required_disagreement` field.
- Keep the existing six keys stable while migrating `daily_brief` to synthesis.

Acceptance: a contract test proves that each active desk receives a meaningfully
different evidence scope or decision question, not just a different byline.
The runtime persona catalog now carries this contract for the six active desks
and the verification lens.

### Slice 3: fan-out, selective editor, and synthesis

- Run independent desks with bounded concurrency.
- Persist each draft before the next workflow phase.
- Persist a bounded article evidence manifest with each printed draft; keep
  execution telemetry in a separate mutable edition receipt.
- Run deterministic validation for all; paid editor review according to policy.
- Generate the front-page synthesis after specialist results.

Acceptance: one desk may fail or be held while the other desks and the truthful
partial issue remain available; the synthesis names missing or conflicting
desks. Current code has per-desk deterministic/editor gates, partial publication
receipts, editor-only retry for unchanged held drafts, a bounded specialist
fan-out, a final daily-brief ordering after specialist desks, deterministic
issue-level agreement/disagreement/open-question synthesis, and a validated
claim-level conflict ledger. Claim conflicts remain visibly unresolved until
the editor or manager supplies a supported resolution.

### Slice 4: conversation surfaces

- Add structured editorial edges and reusable story fragments.
- Place voices in the front-page lead, rails, player/team cards, market board,
  trade surfaces, and data-room alerts.
- Add an evidence drawer and freshness receipt to every material fragment.

Acceptance: a reader can start at the homepage, follow a reporter’s claim to a
player/team decision surface, open the evidence, and see the relevant
counterpoint without leaving the selected league. The current reader now has
the conversation rail, publication-edge receipts, inline reporter chips across
the major decision surfaces, Reality Check evidence receipts, explicit
 counter-signal blocks, and open-question blocks. The League standings surface
 now names Topline Tony's matchup question and the selected Team Pulse includes
 the exact latest matchup receipt. Player and lineup attribution now come from
 exact nested Sleeper player-point rows, reconcile to the aggregate team score
 when complete, and remain explicitly partial or unplayed when they cannot.

The article evidence manifest and separate writer execution receipt are now
part of the Data Room payload and local evaluation path.

The current continuation also projects `writer_fragment_v1` from each gated
publication into the front-page panels and newsroom rail. The panel and full
article tests assert that these are the same bounded structured read, and that a
held article exposes no unapproved thesis or action copy.

### Slice 5: persistent dossiers and Reality Check

- Treat manager and team dossiers as slow-changing assets with their own
  fingerprints and update cadence.
- Add deterministic anomaly checks for no-team players, injury-sensitive
  projections, stale source rows, unavailable clocks, market outliers, and
  unresolved identity joins.
- Let Reality Check explain important anomalies without becoming a second source
  of facts.

Acceptance: known Hill/Mixon/Nailor-style regressions create a visible data
limitation or corrected current-role label before an article can present the
signal as an action. The current deterministic Reality Check packet covers
no-team and injury-sensitive roster rows across both the exact roster and the
league actionable player universe, missing dossier joins, uncalibrated market
proxies, missing projection inputs, and limited freshness receipts. It is
persisted as an analysis artifact, attached to writer evidence, and exposed in
the Data Room. Matched high-severity availability and market limitations now
hold an actionable article unless its local language is conditional or
explicitly unavailable. Market warnings now also retain their comparison basis
and source-quality summary, so the remaining calibration question is correctly
identified as an outcome-learning problem rather than hidden inside a score.
Observed multi-source market outcomes and historical hit-rate calibration
remain future work.

The provider-control slice now carries an explicit effort profile per desk.
The global Luna/max default remains unchanged, while an optional
`FRONT_OFFICE_LLM_REASONING_EFFORT_<ARTICLE_KEY>` override is included in the
plan, job, provider, and artifact receipts and invalidates reuse when it
changes. OpenAI requests also carry a hashed scope cache key and user safety
identifier; actual cache hits are measured from provider `cached_tokens`
telemetry rather than assumed from the request hint. The API contract remains
provider-neutral for Anthropic compatibility.

### Slice 6: production worker and cost control

- Move long-running execution to a separate Railway worker and queue.
- Add idempotent leases, dead-letter handling, cancellation, and retry budgets.
- Add prompt-cache metadata and per-desk effort profiles.
- Reserve Batch for non-urgent maintenance/evaluation runs.

Acceptance: a Railway web deploy during an active run does not lose the run; the
worker resumes or the UI reports a recoverable terminal state with no false
publication claim. The local worker entrypoint, API queue mode, lease-owner
guards, cancellation, and retry-budget contracts are implemented and tested;
the health surface now distinguishes queue configuration from a recent worker
heartbeat; the Railway acceptance still requires a real shared durable volume
and a restart exercise.

### Slice 7: authenticated acceptance

- Run the strict six-desk or target-roster publication gate.
- Verify current Clerk user, linked Sleeper user, exact roster ID, source
  freshness, article receipts, editor receipts, bundle revision, and visible
  conversation entry points.
- Amend dated docs and the decision log with the actual deployed revision and
  publication result.

Acceptance: a fresh authenticated browser session can prove which edition is
  shown, which team owns it, which desks wrote it, what was held or reused, and
  how every important claim reaches evidence.

## Non-goals

- Adding many personalities before each desk has a distinct information job.
- Generating a second paid commentary call for every article.
- Letting an editor or reporter invent projections, market prices, manager
  motives, injuries, or transactions.
- Using a single blended score to answer next-game, season, dynasty, and career
  questions.
- Making generated imagery or prose a substitute for data correctness.
- Automatically sending trades, messages, or league communications.
- Adopting Temporal, Redis, Postgres, or OpenAI Batch before the measured
  workflow requires them.

## Definition of done

This epic is complete when the personal newsroom can:

- run a selected league edition through durable, restartable article jobs;
- show a current and exact user/league/roster identity receipt;
- generate independent specialist perspectives and a bounded front-page
  synthesis;
- make agreement, disagreement, uncertainty, and editor holds visible;
- reuse unchanged dossiers and articles without paid regeneration;
- place reporter fragments across the page while preserving evidence links;
- expose source freshness, provider/model metadata, timing, and failure state;
- survive a worker restart without losing completed work or publishing a false
  success;
- pass the local tests, data trust gate, and authenticated production smoke.

## Research basis

- [Railway: Choose Between Cron Jobs, Background Workers, and Queues](https://docs.railway.com/guides/cron-workers-queues)
- [Railway: Deploy an AI Agent with Async Workers](https://docs.railway.com/guides/ai-agent-workers)
- [OpenAI: Background mode](https://developers.openai.com/api/docs/guides/background)
- [OpenAI: Batch API](https://developers.openai.com/api/docs/guides/batch)
- [OpenAI: Model guidance and reasoning-effort tradeoffs](https://developers.openai.com/api/docs/guides/latest-model)
- [Temporal: Workflow Execution](https://docs.temporal.io/workflow-execution)
- [Temporal: Activities](https://docs.temporal.io/activities)
