# Fantasy Dominator front-office principles

Last reviewed: 2026-08-28

## North star

Fantasy Dominator is a personal fantasy headquarters: a private, league-aware
decision product backed by a deep, inspectable data room and explained through
a focused media facade. It should feel like a small front office that knows the
manager, the league, the opponents, and the history better than the manager can
hold in memory—while leaving the decision with the human.

The governing question is: **given this exact roster, this league, and what
changed recently, what should the manager do next, what should it cost, and
why?** Publication is a presentation method, not the product's output quota.

The product has three layers:

```text
Personal context  ->  deterministic data room  ->  editorial publication
user/team/league      facts/signals/receipts       stories/personas/dossiers
```

The layers are connected, but they have different responsibilities. A writer
can interpret a signal. A writer cannot silently create or alter the signal.

## Guiding principles

### 1. Personalized by default

The first question is not “what is happening in fantasy football?” It is “what
matters to this team in this league?” A manager should be able to move between
leagues quickly and see the correct roster, strategy, opponents, and private
editorial context every time.

### 2. Identity before insight

Every team-scoped output must be anchored to a stable `roster_id`, linked to a
Sleeper user and the authenticated Clerk user. Names are useful labels, not
identity keys. If identity cannot be proven, the UI should say so and avoid
presenting a personalized edition as authoritative.

The current Sleeper team label is source-backed presentation data for the
exact league, season, and roster. A private Front Office label may supplement
it, but a historical Sleeper name must never hide a current rename.

### 3. Data before drama

The app earns the right to tell a story by importing, normalizing, validating,
and timestamping its evidence. Freshness, source, confidence, and limitations
are product features. A polished article built on stale or ambiguous data is a
regression, not a success.

### 4. Analysts are lenses, not authorities

Distinct reporters make the publication fun and useful because they ask
different questions:

- Topline Tony explains the week’s stakes and the important league story.
- Waiver Wire Waverly hunts role changes, risers, fallers, and team fit.
- Trade Desk Talia studies incentives, counterparties, and value gaps.
- Look-Ahead Lonnie searches for playoff windows, stashes, and deadlines.
- Dossier Dana maintains the long-memory view of teams and managers.

The voices can disagree. The evidence cannot be silently rewritten to make the
voices agree.

An assigned desk is not the same thing as a published byline. Before an
accepted LLM receipt exists, the deterministic evidence-led fallback is owned
by The Front Office and may show the intended reporter as an assigned lens.
Only an accepted generated receipt may say that a named reporter wrote the
section.

### 5. Persistent intelligence beats disposable prose

Manager and team dossiers should accumulate durable understanding across
seasons. Recompute the deterministic evidence as data changes, but regenerate
expensive interpretation only when its relevant inputs or evidence fingerprint
changes. Readers should be able to tell what is new, updated, unchanged, or
limited.

### 6. A story should open the data room

The publication surface should be engaging enough to use every day, but every
material claim should lead to the underlying matchup, roster, transaction,
projection, news item, manager signal, or source receipt. The best interface
does not force a choice between a media product and a spreadsheet; it gives the
reader a clear route from headline to proof.

### 7. Recommendations are decision support

An opportunity is not an instruction. Trade and waiver views should explain the
proposed action, counterparties, assets, evidence, risk, confidence, and what
would change the recommendation. Fantasy Dominator never sends a trade or
message on the manager’s behalf.

### 8. Private by league

Strategy profiles, manager trade profiles, custom editor notes, generated
articles, and team dossiers belong to their user/league/team scope. Shared
external facts can be reused; private interpretation cannot be served from a
shared legacy fallback unless the identity and roster receipt match.

### 9. Cost is a product constraint

Use deterministic computation for repeatable facts and reserve LLM calls for
interpretation that benefits from language and judgment. Use the configured
OpenAI `gpt-5.6-luna` model for efficient high-volume work, tune
`reasoning.effort` by task, and preserve provider/model/reasoning metadata in
receipts. Do not spend tokens to restate unchanged data.

### 10. Trust is visible

The interface should make it obvious when the edition is current, when a source
is unavailable, which team is selected, who wrote a section, and whether an
identity or storage check is incomplete. A clear limitation is more valuable
than a confident empty shell.

### 11. Questions organize the data room

The data room should begin with decisions and questions—what changed, what
matters, where signals disagree, and what deserves investigation—then open
into the raw rows and receipts. A chart or interaction earns its place by
advancing the question; decorative density is not analytical depth.

### 12. Structure content before styling it

Articles, evidence packets, dossiers, media assets, ownership, readiness,
history, and dependencies are durable objects with explicit contracts. The
interface may feel like a publication, but the content must remain queryable,
versioned, attributable, and independently verifiable.

### 13. Generated media is atmosphere, not evidence

Illustration can create a memorable newsroom identity, but it must never carry
statistics, factual text, team identity, or unsupported claims. Generated media
is versioned, scoped, accessible, responsive, and optional; a missing asset
must not block the truthful text and data experience.

## Decision-product convergence rules

These rules prevent useful intelligence from drifting back into dashboard
sprawl, repetitive articles, or confident but non-actionable copy.

### A publishable recommendation is a complete decision packet

Every primary recommendation must identify:

- the exact league and `roster_id` it serves;
- a concrete action: add, drop, bid, offer, hold, start, bench, watch, or pass;
- the current roster alternative or opportunity cost;
- the likely acquisition cost, offer range, or resource at risk;
- why the action matters now;
- the expected team-specific benefit;
- confidence, material risks, and the condition that would change the read;
- deterministic evidence, freshness, and source trace.

A waiver rank without a drop and bid is research, not a recommendation. A trade
target without a counterparty rationale, opening offer, settlement range, and
walk-away price is scouting, not a trade plan. Research can remain available in
the Data Room, but it does not earn primary-page attention.

The product may explicitly conclude that there is no worthwhile move. It must
not manufacture recommendations or prose to make a quiet day appear busy.

### One route has one manager job

- **Today:** the three most important decisions now, plus no more than three
  watch items.
- **Waivers / Draft Room:** who to acquire, who to release or deprioritize, and
  what the move should cost. Show no more than five serious candidates before
  a deliberate "see all" action.
- **Trade Desk:** no more than five obtainable targets, each with counterparty
  fit, an executable offer structure, and a walk-away boundary.
- **My Team:** the three largest lineup, depth, fragility, or planning problems
  and the next action for each.
- **Players:** search and investigate a specific player; do not compete with
  Today as another undifferentiated recommendation feed.
- **League:** standings, scarcity, manager behavior, and market context that
  can change a decision.
- **News:** events affecting the selected roster, active targets, or relevant
  competitors; the full feed is secondary.
- **Data Room:** evidence, diagnostics, model inspection, and longer research
  inventories.

These are attention budgets, not data-deletion rules. Deeper inventories stay
available behind progressive disclosure instead of competing with the leading
decision.

### One recommendation has one canonical identity

Today, task views, dossiers, and articles should reuse the same structured
recommendation rather than independently inventing summaries of the same
situation. A stable recommendation identity and evidence fingerprint should
support:

- deduplication across routes and articles;
- a truthful changed / unchanged / invalidated state for returning readers;
- contradiction checks before publication;
- private acted / watching / dismissed / not-interested feedback;
- later outcome and calibration review without implying that an action was
  executed.

When two pipelines disagree about the leading action, resolve the conflict
before publication, show the bounded disagreement explicitly, or withhold the
recommendation. Contradictory hero and detail sections are not acceptable.

### Copy must earn its space

Every sentence on a primary manager surface must do at least one job:

1. state evidence;
2. explain why it matters to this team;
3. recommend an action;
4. describe risk or uncertainty; or
5. identify freshness or provenance.

If it does none of those things, remove it. Desk names and editorial flavor may
orient the reader, but decorative language gets at most a short label or line;
it does not justify another card, preview, article shelf, or repeated summary.
Terms such as "edge," "signal," "intel," and "market" should name a measurable
condition rather than act as atmosphere.

### Persistent intelligence must improve the recommendation

The durable personal model should remember the team's competitive window,
lineup strengths and weaknesses, replacement-level roster spots, age and injury
concentration, pick inventory, bench flexibility, and expressed risk tolerance.
The league model should remember manager activity, trade and waiver behavior,
roster surpluses, positional scarcity, observed prices, and which assets are
realistically obtainable. User feedback should tune future prioritization
without overwriting canonical facts.

An insight is personalized only when these facts materially affect its action,
price, rank, or confidence. Merely inserting the team name into generic copy is
not personalization.

### Primary surfaces have a publication gate

A recommendation reaches Today only when it:

- proves the selected league and roster scope;
- proposes a concrete, team-specific action;
- compares the action with the current alternative;
- includes cost and timing;
- is fresh enough for the claim;
- distinguishes observed facts from estimates;
- is materially new, changed, or newly urgent;
- clears a meaningful impact threshold;
- does not duplicate or contradict another visible recommendation.

Items that fail this gate may remain as research or evidence, but they should
not be promoted by additional prose. The first verified 390-pixel viewport must
show the question, leading recommendation, action, and trust state without
horizontal clipping.

### Keep the operating room out of the front office briefing

Writer stages, durable job receipts, storage audits, generation controls, and
packet terminology remain necessary operational evidence. They belong in a
separate authenticated operator surface. The manager-facing status vocabulary
should stay small and truthful: Ready, Updating, Stale, Limited, or Unavailable.

## Lessons to carry forward

These are the recurring failure modes that should remain visible while the
product grows. They are product rules, not just implementation notes.

- A green server, a healthy API, or a matching Git SHA does not prove that the
  authenticated reader is seeing the intended private bundle. Verify the
  rendered revision, selected league, exact roster receipt, and visible entry
  markers together.
- Team names and display names are mutable labels. The durable identity path is
  Clerk user -> Sleeper user -> league -> `roster_id` -> private team profile.
  If that chain cannot be proven, fail closed or show the limitation instead
  of guessing from a name.
- A fallback article is still a product state. Preserve per-article mode,
  reporter, evidence fingerprint, provider result, and failure reason so a
  reader can distinguish generated analysis, deterministic interpretation, and
  unavailable content.
- The publication facade must be computed from the same normalized evidence as
  the data room. Counts, freshness labels, and source badges must use stable
  dataset identity rather than friendly display text that can drift.
- Depth means a decision path, not more cards. A meaningful slice connects a
  question to deterministic evidence, an uncertainty-aware interpretation, and
  a next investigation or decision. Decorative UI without that path is not
  progress.
- LLM generation is a bounded editorial step. Send only the selected scope's
  validated context, use the configured Luna model through `src/llm.py`, skip
  unchanged work, and never let a writer invent facts or perform an action.
- Generated artwork should strengthen recognition and mood while remaining
  optional and clearly separate from evidence. It must not become a substitute
  for missing data, analysis, or product structure.

When a proposed feature conflicts with one of these lessons, update the
decision log and the relevant contract in the same change. Do not rely on a
future cleanup to reconcile contradictory doctrine.

## Product quality bar

Before calling a slice complete, ask:

1. Does it make a real weekly decision faster?
2. Is it scoped to the correct user, league, and roster?
3. Can the claim be traced to deterministic evidence?
4. Is the freshness and confidence understandable?
5. Does it avoid unnecessary generation cost?
6. Does it survive refresh, logout/login, and deployment?
7. Does it still work when an optional source or provider is unavailable?
8. Does the first screen state a concrete decision rather than describe a desk?
9. Does every prominent recommendation include action, alternative, cost,
   timing, risk, confidence, and evidence?
10. Are unchanged, duplicate, lower-impact, and contradictory items suppressed?
11. Could any sentence or section be removed without losing evidence, relevance,
    action, uncertainty, or provenance? If so, remove it.
12. Does a rendered 390-pixel viewport expose the leading decision without
    clipping, overflow, or an operator control blocking it?
