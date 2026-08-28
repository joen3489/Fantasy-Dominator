# Epic: Single-Brain Decision Product Convergence

Status: in implementation; local packages 1-4 verified, production acceptance open
Date: 2026-08-28
Owner: Fantasy Dominator product

## Objective

Converge the existing Fantasy Dominator data, recommendation, editorial, and
browser capabilities into one useful personal front office without adding a
second source of truth or another layer of product sprawl.

The finished loop is:

```text
approved source
  -> preserved raw payload
  -> canonical facts
  -> deterministic analysis and recommendations
  -> fingerprinted evidence packet
  -> one canonical LLM interpretation per decision or entity
  -> route-specific views and excerpts
  -> human decision and recorded feedback
```

Codex and the configured API writer are interchangeable editorial workers over
the same validated packet. Neither is a fact source. Sleeper and approved
external inputs enter through the data layer before they can affect an article,
profile, recommendation, or UI label.

## User outcome

For a selected league and exact roster, the product should answer:

- What are the three decisions that matter now?
- Who should I add, who should I drop, and what should I bid?
- Which player is an obtainable trade target, what should I offer, and where
  should I walk away?
- What does the product know about this player, team, or manager that changes
  my decision?
- What changed since the last edition, and which prior advice is still valid?

Rich player and manager profiles are desirable. They belong behind entity
drill-downs and must strengthen the decision path rather than compete with it
on primary pages.

## Epic constraints

1. **One data brain.** No browser article, search result, model memory, API
   response, or prior prose becomes a publishable fact until the information is
   preserved, normalized, validated, and assigned a source/evidence receipt.
2. **One interpretation per entity or decision.** Today, Waivers, Trade Desk,
   articles, and dossiers reuse one canonical profile or recommendation object;
   they do not generate independent factual summaries.
3. **No feature expansion by default.** Reorder, remove, collapse, rename, and
   connect existing capabilities before adding a source, model, writer, page,
   chart, or scoring system.
4. **Decision-first attention budgets.** Today promotes at most three primary
   decisions. Waiver and trade views promote at most five serious candidates
   before progressive disclosure.
5. **No filler requirement.** "No worthwhile move" is a successful result.
6. **Generation follows evidence changes.** Unchanged fingerprints reuse the
   existing interpretation. A changed source does not automatically require
   every article or profile to be rewritten.
7. **Operator work stays separate.** Generation controls, durable jobs, storage
   diagnostics, and packet receipts remain inspectable without occupying the
   manager briefing.

## Existing capabilities to organize

This epic deliberately builds on the current implementation:

- `src/articles.py`: six registered article scopes and bounded evidence
  selection;
- `src/operator.py`: structured article schema, evidence fingerprints,
  validation, Reality Check, reuse, editorial review, and artifact recording;
- `src/analysis.py`: deterministic daily brief, target/sell/trade theses,
  player dossiers, manager dossiers, and fallback articles;
- `src/priority_board.py`: deduplicated, ranked Today candidates;
- `src/browser_site.py`: Today, Draft Room, My Team, Players, League, Trade
  Desk, News, Data Room, entity search, and evidence drawers;
- `src/editorial.py` and `src/editorial_ui.py`: publication composition and
  presentation;
- `app/main.py`, `app/templates/home.html`, and `app/db.py`: authenticated
  league ownership, operator actions, durable artifacts, feedback, and the
  multi-league headquarters;
- the scheduled Luna Codex task: three daily evidence and editorial review
  passes, with the in-app API writer retained as a fallback.

An implementation must enumerate consumers before retiring or relocating any
of these artifacts. A label such as "legacy" is not proof that the path has no
runtime effect.

## Canonical editorial artifacts

### Decision interpretation

Each promoted recommendation reuses the deterministic recommendation identity
and adds an editorial interpretation containing:

- league ID, roster ID, season, and recommendation ID;
- action and current alternative;
- expected cost, bid, offer range, or resource at risk;
- why now and expected team-specific benefit;
- risk, confidence, and reconsideration trigger;
- exact evidence IDs, source IDs, and freshness;
- evidence fingerprint, generated time, writer mode, model, and status;
- optional short and long rendering fields derived from the same object.

The editorial artifact may explain the recommendation. It may not replace the
deterministic action, cost, ranking, identity, or source fields.

### Entity profile

Each relevant player or manager may have one current LLM profile per
league/roster scope. The profile contains:

- exact entity identity and scope;
- current role or roster position;
- usage, production, availability, and market context supported by the packet;
- fit for the selected team and competitive window;
- recommended action or watch condition;
- risk, confidence, counter-evidence, and reconsideration trigger;
- exact evidence and source receipts;
- a stable fingerprint and explicit changed/unchanged/limited state.

Profiles are analyst artifacts, not columns added to canonical fact tables.
Browser surfaces join them by exact entity ID and scope. Route excerpts come
from the profile's structured summary fields instead of being separately
generated prose.

### Eligible profile cohort

Do not generate a profile for every cached NFL player. The first eligible
cohort is:

- players on the selected roster;
- the highest-ranked current waiver/free-agent candidates;
- active trade targets and shop candidates;
- players with a material scoped news, role, availability, projection, or
  market change;
- managers who are counterparties in an active recommendation or whose
  validated behavior materially changed.

The cohort is deterministic and recorded in the generation receipt. A profile
leaving the cohort is retained as history but is not presented as current
advice.

## Vertical slice 1: Freeze the single-brain contract

### Work

- Trace each approved news source from fetch through raw preservation,
  normalization, evidence packet, generated artifact, and browser rendering.
- Add or tighten validation so an unsourced browser/Codex discovery can only be
  stored as an `unverified_investigation` lead and cannot enter recommendation
  or profile packets.
- Define the stable identity and fingerprint inputs for decision interpretations
  and entity profiles.
- Add a read-only per-desk and per-entity packet export that contains the exact
  evidence a Codex or API writer is allowed to use.
- Keep private user, league, and roster scope in every export and receipt.

### Acceptance

- A source URL or prose fragment without a normalized row and evidence ID
  cannot support a published sentence.
- The same packet can be given to Codex or the API writer and passes the same
  validator.
- Changing unrelated evidence does not invalidate an unaffected profile.
- An exact `roster_id` mismatch fails closed.
- Tests name this epic as the design source for the enforced boundary.

## Vertical slice 2: Add the Codex draft seam

### Work

- Add an authenticated operator export for one article, recommendation, or
  entity profile packet.
- Accept a structured Codex draft through an authenticated import path; do not
  accept arbitrary Markdown as a published artifact.
- Reuse the current article validator, Reality Check, evidence-ID checks,
  forbidden-language checks, and content hashing.
- Keep an imported Codex response out of the printed facade until the existing
  evidence, Reality Check, structured-output, and publication gates accept the
  complete scoped batch.
- Store accepted final output as `codex_task`, with its model, packet
  fingerprint, validation receipt, and scope. Do not label it
  `automatic_llm`.
- Treat the configured API writer as a fallback consumer of the same packet
  only when Codex cannot complete or repair the batch. It does not revise a
  separate recommendation or create a second editorial state.

### Acceptance

- A valid Codex response can enter the same final article/profile pipeline
  without being mislabeled `automatic_llm`.
- A draft with an invented evidence ID, wrong roster, stale fingerprint,
  unsupported transaction claim, or missing availability caveat is rejected.
- The API fallback consumes the same packet; it is not a second recommendation
  engine.
- No provider call occurs when the accepted final artifact and fingerprint are
  unchanged.
- Operator and browser receipts distinguish deterministic fallback, Codex seed,
  approved final, held, stale, and unavailable states truthfully.

## Vertical slice 3: Publish canonical player and manager profiles

### Work

- Build the deterministic eligible-profile cohort from existing roster,
  available-market, target/sell, trade, news, projection, and manager tables.
- Export bounded evidence packets per entity.
- Generate or import one structured profile per eligible entity.
- Store profile history and current status through the durable content-artifact
  boundary rather than writing interpretation into processed CSVs.
- Join the current profile into existing player and manager entity pages.
- Preserve the current deterministic dossier and evidence drawers underneath
  the LLM interpretation.

### Acceptance

- A selected-roster player page explains role, market, availability, team fit,
  action, risk, confidence, and evidence without inventing a fact.
- A waiver candidate profile includes the deterministic add/drop/bid context
  when those fields exist; missing price evidence stays visibly missing.
- A trade-target profile names only a correctly joined owner/counterparty and
  reuses the canonical offer boundaries.
- The same profile supplies excerpts to every route without contradictory copy.
- A second unchanged run reuses all eligible profiles and reports zero rewrites.
- A single changed player packet invalidates only that player's profile and the
  directly dependent recommendations/articles.

## Vertical slice 4: Recompose existing routes around decisions

### Work

- **Headquarters:** lead with league selection, the attention queue, and source
  trust. Move writer controls, publication ledgers, storage audits, and repeated
  article shelves to the operator/Data Room surface.
- **Today:** render the three highest-priority canonical recommendations. Put
  supporting article/profile excerpts and evidence inside those decisions.
- **Waivers / Draft Room:** lead with no more than five complete add/drop/bid
  decisions; keep rookie and long-horizon research behind the appropriate
  drawer or subview.
- **Trade Desk:** lead with no more than five obtainable targets containing
  counterparty fit, opening offer, settlement range, and walk-away boundary.
- **My Team:** lead with the three largest lineup, depth, fragility, or planning
  problems and their next actions.
- **Players and League:** keep search and entity investigation; remove competing
  generic feeds.
- **News:** show decision-relevant events first and retain the complete feed as
  reference.
- **Data Room:** own raw tables, diagnostics, evidence receipts, writer status,
  and operational controls.
- Fix the headquarters' real 390-pixel horizontal clipping before considering
  the route reorganization complete.

### Acceptance

- The first viewport identifies the selected league/team and a concrete action
  or explicit all-clear.
- No player, recommendation, or article is presented twice as a separate top
  story on the same route.
- Today never exceeds three primary decisions.
- Long entity copy remains available without lengthening the primary route.
- The manager can return to the multi-league headquarters from every edition.
- Rendered desktop and 390-pixel entry-path tests assert visible content,
  viewport, exact revision, league, and roster preconditions.

## Vertical slice 5: Operationalize the scheduled Luna editor

### Work

- Run the dedicated Luna Codex task three times daily against the saved project.
- Refresh approved sources and deterministic artifacts before editorial work.
- Export only changed packets and import only validated Codex drafts.
- Use the configured API writer/editor only when Codex cannot produce or repair
  a valid artifact.
- Rebuild the affected browser bundles and publish through the authenticated
  operator path.
- Record a run receipt containing source changes, affected fingerprints,
  generated/reused/held artifacts, validation results, and publication state.
- Preserve the explicit human boundary: no waiver claims, lineup changes,
  trades, offers, or manager messages are executed.

### Acceptance

- An unchanged scheduled run refreshes trust receipts, performs zero editorial
  rewrites, and does not create a new issue merely to appear active.
- A supported news change updates the normalized data before any profile or
  recommendation copy changes.
- A blocked source, auth session, operator token, or publication seam produces
  a truthful blocked receipt rather than a success message.
- The API fallback produces an artifact that passes the same packet, identity,
  evidence, and browser entry-path checks.
- An authenticated production check proves the intended revision, selected
  league, exact roster, current profile, and current recommendation are visible.

## Vertical slice 6: Close the learning loop without creating another brain

### Work

- Reuse existing acted/watching/dismissed/not-interested feedback controls for
  canonical recommendation and profile identities.
- Record explicit outcomes separately from page views and article reactions.
- Use feedback to prioritize or suppress future interpretations, never to
  overwrite Sleeper facts or deterministic scores.
- Report recommendation coverage, confirmation, invalidation, and calibration
  separately from article engagement.

### Acceptance

- Dismissing a recommendation suppresses its presentation without deleting the
  underlying evidence.
- A changed deterministic action can reopen a previously dismissed entity with
  a clear "what changed" receipt.
- No page view, generated sentence, or model agreement is counted as a correct
  recommendation outcome.

## Ordered work packages

Execute these as reviewable, releasable packages:

1. **Contract and packet export:** single-brain boundary, entity fingerprints,
   adversarial tests, and no UI changes.
2. **Codex import and review:** structured seed import, durable receipts, API
   editor reuse, and no new consumer surface.
3. **Canonical entity profiles:** eligible cohort, durable profile artifacts,
   entity-page rendering, and unchanged-reuse verification.
4. **Decision composition:** Today, Waivers, Trade Desk, My Team, homepage, and
   Data Room reordering using existing data and components.
5. **Scheduled production loop:** Luna task, authenticated publication,
   browser verification, and blocked-state receipts.
6. **Feedback and antagonistic pass:** outcome reuse, contradiction audit,
   mobile audit, empty/quiet-day audit, and provider/source failure audit.

Do not combine packages 1-4 into one UI rewrite. Each package must pass its
entry-path and contract tests before the next package relies on it.

## Implementation checkpoint: 2026-08-28

Local implementation now includes:

- authenticated, exact-scope editorial packet export and atomic structured
  Codex import using the existing article validation and publication gates;
- a truthful `codex_task` writer mode in the reader, artifact ledger, normal
  authenticated smoke contract, and durable content status;
- deterministic player/manager profile eligibility, isolated evidence
  fingerprints, structured profile import, current/history storage, and exact
  entity-page joins while preserving deterministic dossiers underneath;
- three visible front-page decision lenses, five primary waiver/draft names,
  five primary trade counterparties, and secondary research behind closed
  drawers;
- a two-row mobile navigation grid that exposes every primary destination
  without an inner horizontal scroller;
- the active Luna heartbeat at 08:00, 13:00, and 18:00 using the packet,
  validation, import, reuse, browser-rebuild, and blocked-receipt workflow, with
  the API writer explicitly retained as fallback;
- fail-closed availability language for historical move-ledger mentions and a
  corrected matchup player receipt that treats observed scoring as played even
  when Sleeper omits a playoff/consolation opponent identity;
- an idempotent deterministic desk-review receipt for Codex imports, explicit
  full-versus-partial profile cohort semantics, and canonical profile excerpts
  on the five manager-facing waiver cards.

Local verification at this checkpoint:

- 431 repository tests pass;
- the refreshed deterministic data audit passes with a 35.5-hour freshness
  margin, 3,101 resolved player-history rows, and zero structural horizon
  errors;
- the verified local league/roster scope publishes six Codex desk reports and
  19 current Codex player/manager profiles; an unchanged rerun reports zero
  rewrites and reuses all 19 profiles;
- the rendered waiver room shows one canonical action and risk on each of its
  five primary cards while preserving the deterministic rank and evidence
  drawer;
- a rendered mobile edition has zero document or navigation overflow, three
  hydrated front-page panels, five waiver cards, five trade-counterparty cards,
  one roster decision board, and all secondary editorial/research drawers
  closed by default.

This is not epic completion. No code was committed or deployed in this local
implementation pass. A current authenticated production revision still must
prove the Clerk -> Sleeper -> league -> roster chain, one imported Codex player
profile and manager profile, unchanged reuse, direct-dependent invalidation,
the current recommendation surfaces, and the scheduled task's publish-or-block
receipt. Until then, the production acceptance items below remain open.

## Epic completion criteria

The epic is complete only when one authenticated production league proves all
of the following in the same current revision:

1. The exact Clerk -> Sleeper -> league -> `roster_id` chain is visible.
2. Today contains no more than three non-contradictory decisions.
3. One waiver decision includes add, drop, bid, fit, risk, confidence, and
   evidence—or the product truthfully reports that no supported waiver move
   exists.
4. One trade decision includes target, real owner/counterparty, opening offer,
   settlement range, walk-away boundary, risk, confidence, and evidence—or the
   product truthfully reports that no supported trade exists.
5. A rich LLM player profile and manager profile reuse deterministic facts and
   exact evidence IDs.
6. Route excerpts match the canonical profile/recommendation rather than
   competing with it.
7. An unchanged rerun performs zero unnecessary profile/article generation.
8. A changed packet invalidates only its direct dependents.
9. Unsupported news cannot reach a recommendation or profile.
10. The headquarters and edition work at a verified 390-pixel viewport.
11. Operator controls and receipts remain available without dominating the
    manager experience.
12. The scheduled Luna task publishes or reports a truthful blocker, and the
    API fallback passes the same gates.

## Non-goals

- Adding another projection model, valuation formula, news source, writer
  persona, or primary route.
- Generating profiles for every player in the Sleeper cache.
- Allowing Codex or the API to browse news and bypass ingestion/provenance.
- Treating LLM prose as a canonical fact table.
- Executing trades, claims, lineup changes, or outbound messages.
- A brand redesign, new illustration campaign, or chart expansion.
- Replacing the current deterministic fallback before the Codex/API path has a
  verified production entry route.
- Committing, deploying, or mutating production as an implicit side effect of
  drafting or validating content.

## Verification gate

Each package runs the smallest relevant tests while iterating and the full gate
before handoff:

```powershell
python -m unittest discover -s tests -p "test*.py"
python scripts\validate_local_data.py
git diff --check
```

Production acceptance additionally requires `python scripts\smoke_live.py`
with the expected revision plus authenticated browser verification of the
selected league, exact roster, current artifact receipts, and rendered mobile
surface. A healthy server or matching Git SHA alone is not completion.
