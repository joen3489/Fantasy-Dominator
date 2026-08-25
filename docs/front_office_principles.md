# Fantasy Dominator front-office principles

Last reviewed: 2026-08-25

## North star

Fantasy Dominator is a personal fantasy headquarters: a private, league-aware
publication backed by a deep, inspectable data room. It should feel like a
small newsroom whose analysts know the manager, the league, the opponents, and
the history—while leaving the decision with the human.

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
