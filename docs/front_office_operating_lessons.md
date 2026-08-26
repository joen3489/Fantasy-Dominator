# Front Office operating lessons

Last reviewed: 2026-08-26

This is the short, durable memory for Fantasy Dominator. It exists so future
work does not rediscover the same product and development lessons in chat.
The detailed requirements remain in `AGENTS.md`,
`docs/front_office_principles.md`, `docs/data_contract.md`, and
`docs/front_office_realization_epic.md`.

Current publication note (2026-08-26): six desks are in the local contract.
Older five-desk and `0/5` receipts in this historical log predate the
Four-Window Market Read and are not current status claims.

## 2026-08-26 - A running writer needs more than a spinner

The durable operator receipt is part of the product contract, not merely a
debug aid. Refresh, six provider calls, optional editor calls, and browser
rebuild can exceed a short browser watch window or be interrupted by a daemon
restart. Preserve the run ID, stage, model, timeout, active desk, and safe
per-desk states. If a wrapper fails, carry that checkpoint into the terminal
failure so the reader can distinguish no progress, partial work, and a
published issue. The reader must remain deterministic fallback until the
manifest and article receipts prove that copy is current.

## Product model

Fantasy Dominator is a private personal headquarters with a media facade over
a trustworthy data room. It is not a generic fantasy dashboard and it is not a
collection of AI articles.

## 2026-08-25 - setup and maintenance are different products

Historical league assembly and recurring upkeep have different cost and
freshness contracts. Bootstrap may traverse discovered historical seasons and
their configured week range; the current season is bounded by Sleeper's
observable leg so future placeholder rows cannot become evidence. Maintenance
is bounded to the current league and current-season window, then merges fresh
canonical rows into the prior snapshot by exact source keys before rebuilding
derived analytics. Its receipt must say what was requested and what history was
preserved. A maintenance run must never make omitted historical rows look
freshly fetched.

```text
Clerk user
  -> linked Sleeper user
  -> league
  -> exact roster_id
  -> private team context
  -> validated evidence
  -> deterministic insight
  -> bounded reporter lens
  -> readable story and decision packet
```

The three product layers have distinct jobs:

- Personal context selects the manager, league, roster, strategy, and private
  notes.
- The data room owns facts, joins, projections, signals, freshness,
  confidence, limitations, and source traces.
- The publication turns selected evidence into engaging stories, dossiers,
  and visual explanations without hiding the path back to proof.

## Lessons that must survive implementation changes

1. **Identity is an ID chain, never a label.** Team and manager names are
   mutable display values. A `roster_id` linked through the authenticated Clerk
   and Sleeper identities is the only safe team boundary. If the chain cannot
   be proven, the app must show a limitation instead of guessing.

   The current Sleeper label still matters after identity is proven: resolve it
   from the exact league/season/roster source row. Keep a separate optional
   Front Office alias, and treat a persisted value matching a known historical
   Sleeper label as stale source presentation rather than a deliberate alias.

2. **Depth comes from reusable evidence objects.** A manager dossier should
   be built from season history, transaction timing, roster construction,
   counterparties, and outcomes—not from career totals or a longer paragraph.
   Build the deterministic ledger once, then let the Data Room, dossiers,
   Trade Desk, and writers consume it.

3. **Writers are lenses, not fact engines.** Topline Tony, Waiver Wire
   Waverly, Trade Desk Talia, Look-Ahead Lonnie, and Dossier Dana may ask
   different questions and disagree about emphasis. They may not invent
   events, infer motives as facts, execute trades, or overwrite deterministic
   labels. Every article must show why, risk, confidence, and evidence scope.

4. **Fallback is a product state, not an empty state.** If Luna is unavailable,
   deterministic fallback should still have the same inspectable receipt shape:
   reporter, schema version, evidence fingerprint, evidence IDs, source IDs,
   limitation, story spine, and Data Room path. It must be visibly labeled as
   fallback and must never masquerade as generated editorial.

5. **Content generation is a deliberate, paid operation.** Use deterministic
   code for repeatable facts. Generate or regenerate interpretation only when
   the relevant evidence fingerprint or writer inputs change. Keep provider,
   model, reasoning effort, prompt/input scope, cost boundary, and result in a
   receipt. Protected writes require the operator boundary.

6. **A media surface must open the data room.** A headline is successful only
   when the reader can quickly understand what changed, why it matters, what
   the counter-signal is, and what decision is available—then inspect the
   underlying rows and source freshness. Presentation is a translation layer,
   not a replacement for organized data.

7. **Generated imagery is atmosphere, not evidence.** Image assets should be
   scoped to a reporter or section, carry prompt/model/hash/status metadata,
   have responsive variants and meaningful alt text, and fail without blocking
   the article. They must not contain factual player, score, or transaction
   claims unless those claims are separately rendered from validated data.

8. **Production truth requires entry-path verification.** A healthy endpoint,
   a Railway deployment, or a current source SHA is not enough. Verify a clean
   authenticated browser load, the exact roster receipt, the rendered story,
   the embedded bundle revision, the durable article payload, and freshness.
   If code is current but a preserved bundle is stale, treat that as a
   migration defect and fix the seam rather than declaring success.

9. **A decision packet must be two-sided at the entry point.** Trade analysis
   needs the target side and the selected roster's possible conversation side,
   plus price guardrails, timing risks, alternative counterparties, evidence,
   and explicit read-only limits. If those fields exist only in an artifact or
   only on one route, the product still feels shallow. Reuse one renderer and
   show unsupported alternatives as an honest empty state.

10. **A newsroom needs a deliberate learning ledger.** Join feedback to the
    current article receipt and reporter identity before evaluating a voice.
    Count only explicit signals, keep open calls separate from resolved calls,
    and show small samples honestly. Attention is not usefulness, and a
    confirmed rate is not meaningful until there are resolved calls.

11. **Absence is a data result.** A manager dossier or trade packet must say
    when no supported fit exists, with the evidence boundary visible. An
    omitted card looks like a broken pipeline and encourages prose to fill the
    gap; an explicit none-supported state preserves trust.

12. **A snapshot is not automatically a delta.** When the data room lacks a
    prior comparable receipt, show the latest event pulse and say what it is.
    Do not turn retained news, trade, or waiver rows into a claim that they
happened since the reader's last visit.

13. **Coverage is not feedback.** Seed newsroom coverage from the current
    publication receipts so the full lineup remains visible, then overlay
    only explicit user signals. A desk with no interactions is neither useful
    nor unuseful yet.

## Anti-recursive change protocol

Before adding a feature or “cleaning up” an old artifact:

- trace browser entry -> action -> durable store -> generated artifact ->
  browser response;
- identify all runtime consumers before deleting or renaming anything;
- make migrations additive, idempotent, and safe when some generated inputs
  are absent;
- test the user-facing entry path and the failure seam, not only a helper;
- make contracts fail closed at their boundary;
- report freshness and proximity to failure, not only PASS/FAIL;
- amend dated claims in the same change that makes them stale; and
- run local gates independently and record when authenticated production
  verification was not possible.

14. **A manager dossier needs the fit comparison, not just the fit card.** A
    current counterparty edge should be compared with the manager's
    recency-weighted historical valuation lanes and the number of seasons in
    scope. Show overlap and non-overlap explicitly; historical preference is
    a conversation prioritizer, never proof of intent or a predicted response.

15. **Preserve the prior bundle before overwriting it.** A return visit can
    only explain what changed when the reader compares the current event rows
    with a durable prior scope keyed by source IDs. Compute that receipt before
    writing the new bundle, keep added/updated/removed counts separate, and
    show a visible unavailable state when the prior scope is incomplete. Never
    convert the first full snapshot into a list of supposedly new events.

16. **A blocked operator action is not a provider failure.** When a write
    control is pressed without the required operator token, overlay the blocked
    message on the existing live status instead of replacing it with a small
    object. Provider, model, publication, and reader-contract receipts must
    remain visible so an authorization problem cannot masquerade as a missing
    API key or an unsuccessful writer run.

15. **A current revision does not prove a current reader.** Durable bundles
    must be checked for both the fields and the generated shell markers that
    the new entry path requires. If a manager dossier or the reader shell is
    old, trigger an additive migration before serving it; do not stamp or trust
    a healthy bundle merely because its source SHA matches.

16. **A stale private bundle must not mask a current fallback.** Bundle
    selection must apply freshness and contract checks before preferring a
    user-scoped root over a legacy migration root. Identity correctness alone
    is not enough if the selected shell or payload is older than the current
    reader contract.

17. **A configured strategy must change the decision surface.** A saved
    strategy profile is not useful if the UI only repeats its name and
    direction. Join the exact active roster to deterministic fit, need,
    liquidity, and action rows; show the resulting alignment and evidence.
    Missing joins must say `not_scored`, never be filled with a generic value
    tag or a name-based match.

## Current open boundary

As of 2026-08-26, the latest exact revision is recorded by the revision-aware
Railway health/public smoke check. That check reports the production
configuration as deployment-ready, with durable storage/database continuity,
protected operator writes, and OpenAI `gpt-5.6-luna`; the authenticated reader
and writer receipt are still an open verification boundary in this work session
because no current Fantasy Dominator Clerk session is available in the
connected browser. The current-role writer-scope and availability-editor fixes
are included in the deployed `main` revision. Do
not turn public health or smoke into a claim that the user's private league
identity, exact roster, or latest article publication was verified.

The protected Luna publication is a separate open boundary: deterministic
fallback remains the honest reader state until the operator-authorized run
produces current per-article writer receipts. This is an explicit cost and
authority boundary, not a reason to weaken the receipt contract. When a run is
available to inspect, verify refresh completion, exact `roster_id` continuity,
model/reasoning receipt, each desk state, editor decision, bundle revision, and
the rendered article before closing this boundary. Browser freshness remains
an explicit precondition because an already-open tab can retain an older shell
until it is reloaded.

The article-specific media slice was previously verified on `e830e05`: the
signed-in edition loaded four 1536px desk illustrations, kept the exact
`roster_id=2` identity for Lulu’s Potatoe’s, and exposed media metadata beside
the evidence receipt. That media proof is a separate acceptance slice from
reader-bundle selection. Lazy artwork must be checked after it enters the
viewport; an initial DOM presence check is not proof that the browser loaded
the asset.

## 2026-08-25 production reader selection checkpoint at `0c7b052`

The stale-private-root regression test is now in the code path and the
current-bundle preference fix is deployed as `0c7b052`. The live browser
result shows why this seam needs a stronger receipt: `/healthz` can report the
new source revision while the authenticated league route still serves an old
embedded manifest and old shell markers. Bundle selection, migration outcome,
and the final served revision therefore belong in one observable contract.
The contract is now proven on the later `acd8c3a` deployed signed-in route.
Preserve the old
bundle as a recoverable migration candidate, but never present it as current
content; a browser reload is part of verification when an earlier cached
navigation reports an old embedded revision.

## 2026-08-25 reader-serving gate implementation

The serving seam now has a safe per-league reader receipt with selected root,
served revision, contract booleans, and bounded reason codes. After recovery,
the route rechecks completeness, exact identity, shell markers, and the
current durable payload before returning HTML. If the old shell remains, the
user receives a branded 503 recovery state instead of silently reading stale
content. The deployed verification now closes this boundary for `acd8c3a`: a
fresh reload and repeat direct entry both returned the current private reader,
exact roster identity, and the rendered cross-season lane section.

## 2026-08-25 player transaction identity and direction

The first substantive re-audit after the reader migration found that
`player_transaction_history.csv` had names but not the Sleeper player IDs that
make a historical row joinable to a dossier. It also emitted only acquired
trade rows, which made the evidence asymmetric. The normalized trade and
waiver tables now preserve source player IDs, the history ledger emits both
acquired and sold directions, and every row carries an `identity_method`.

The current six-season refresh produced 3,101 history rows: all resolved by
`source_id`, with 505 acquired and 505 sold trade rows. This is a local
artifact receipt, not a claim that every future source will resolve. The
unresolved states remain explicit as `normalized_name`, `ambiguous_name`, or
`unmatched_name`; no display-name match is allowed to silently become a
canonical identity.

The local validator now carries a compact identity receipt for this seam:
method counts, resolved and unresolved rows, unresolved rate, and acquired vs
sold trade counts. A green freshness check without this semantic receipt is
not enough to call historical player depth trustworthy.

## 2026-08-25 Data Room semantic receipt

If a validator can detect a semantic limitation, the reader should expose the
same limitation at the point where a manager consumes the evidence. The Data
Room now renders `dataQuality.player_history_identity` from the exact history
rows in the bundle. Freshness, join coverage, identity method, and trade
direction balance are separate facts. A partial or contract-error receipt must
remain visible instead of being converted into a reassuring green badge.

## 2026-08-25 strategy overlay entry-path slice

The My Team surface now joins the exact active roster to deterministic
`team_needs_matrix`, `team_fit_scores`, and `action_recommendations` rows. It
shows team shape, need lanes, fit coverage, action mix, and top aligned roster
evidence; the roster table carries the same fit, action, timeline, and
liquidity fields. Missing joins remain `not_scored`. A configured strategy is
not complete until it changes the decision surface, not merely the profile
label.

## 2026-08-25 recommendation outcome ledger

Article usefulness is not recommendation accuracy. The private ledger now
keeps article outcomes and target/sell/trade decision outcomes in separate
lanes, keyed to the recommendation and the bundle revision that produced it.
Only an explicit manager report can move a call from open to confirmed,
missed, or unclear; page views and generated prose never count as outcomes.

## 2026-08-25 recommendation-learning shell migration

The first deployment of the recommendation outcome ledger exposed a durable
artifact seam: Railway and `/healthz` reported the new source revision, while
the authenticated league route still served the previous shell because its
manifest and older dossier markers looked otherwise healthy. A source SHA and
payload receipt are not enough to prove that a new user-facing capability is
reachable. New entry-path capabilities must add a semantic shell marker to the
reader contract, and stale durable shells must rebuild or fail closed before
HTML is returned. The browser proof must check the exact control and the
reader's learning summary after migration.

## 2026-08-25 production verification at `375bed1`

The semantic reader contract fix is deployed and verified on the authenticated
owned route for Joanie Loves Dynasty Football. The bundle reports the full
`375bed1368b9f2706af44138bbe6e23ee79663b8` source revision, `current · private`
reader state, and the exact `roster_id=2` identity for Lulu’s Potatoe’s. The
Trade Desk exposes 25 recommendation outcome controls with only `open`,
`confirmed`, `missed`, and `unclear`; Data Room exposes the separate
recommendation-learning ledger and the verified 3,101-row historical identity
receipt. Public revision smoke also passed. This closes the stale-shell slice;
future capability slices must add an equivalent semantic marker and browser
entry proof.

## 2026-08-25 event grain must reach the manager dossier

The manager data room already contained event-level trades and waivers, but the
manager entry page primarily showed career totals, season aggregates, and fit
labels. That made a deep source table feel disconnected from the dossier a
manager actually reads. The structured dossier now carries a bounded,
roster-scoped transaction timeline and the browser renders the event details
with an explicit evidence and motive boundary. The reusable rule is to promote
the exact evidence grain needed for a decision into the dossier object before
adding more interpretation or more cards.

## 2026-08-25 direct dossiers must share the decision ledger

The main Trade Desk already recorded outcomes for target, sell, and trade
recommendations, but a reader arriving through a manager dossier saw the same
fit hypothesis without a way to evaluate it. Direct entity pages must reuse
the canonical recommendation interaction with a stable, scoped key; adding a
second manager-only feedback lane would split learning and invite
contradictory rates. The manager-fit control records an explicit human report,
never a completed trade inferred from the page.

## 2026-08-25 compare fits at the candidate level

A dossier-level statement that some fit overlaps a historical position lane is
not enough for a decision. The current fit list now carries its own alignment
object, including the matching lane and evidence or an explicit no-direct-lane
state. The UI can explain one candidate without making every candidate inherit
the strongest historical signal in the dossier.

## 2026-08-25 team construction must be exact-scope presentation

An entity page is deeper when it translates the selected roster into a
construction snapshot: position mix, market/projection coverage, need lanes,
and action mix. Those values must come from the current-season `roster_id`
scope and retain an evidence drawer. Missing joins stay unavailable; a
neighboring team must never fill the blank merely to make the card look rich.

Production proof at revision
`db6c71e34eb18c7069f7cd35361c83be65d39f48` rendered the panel for Moose
Caboose roster 4 while the authenticated edition remained Lulu’s Potatoe’s.

## 2026-08-25 economic totals must use one canonical ledger

When two dossier surfaces show a market total, they must consume the same
`team_asset_inventory` rows. `player_dossiers` is a player-profile join and
may omit internal proxy valuations that the economic ledger intentionally
retains. The reader should reconcile totals across surfaces and label proxy
coverage instead of silently dropping values or pretending a proxy is an
external observation. This is a data-contract issue, not a cosmetic card
choice.

Production proof at `eb9b68d96f40cffa0afec6131547be178d8f1395` confirmed the
repair in Chrome: Moose Caboose's Team construction and Manager dossier both
showed 835.54, while the construction evidence showed 30/30 market rows and
four internal proxy values.

## 2026-08-25 player dossiers need the same market provenance

The team-total repair revealed a second-order version of the same problem:
player pages can be wrong even when the team total is right if they read a
profile join instead of the exact owned asset. For rostered players, join
`team_asset_inventory` by `roster_id + asset_id`, label proxy values, and show
unavailable when the owned asset row is missing. Keep profile market values
only for unrostered player-pool pages.

## 2026-08-25 proxy economics must reach the decision layer

Finding a proxy value in the asset ledger is not enough if dossiers, signals,
and actions still store zero. External market values should win; missing
values may inherit the exact asset-ledger proxy only with its source trace and
lower-confidence risk language. After a model change, regenerate the local
tables and compare all proxy assets across every downstream consumer before
claiming the data room is coherent.

## 2026-08-25 writer preflight must separate secrets

The OpenAI provider key and the browser's operator authorization are different
controls. The Writer Desk now states both readiness states and the exact
provider/model configuration before a user spends a generation attempt. It
reports only configured/missing state, never values; a failed preflight must
remain a no-call condition.

Production receipt at revision
`f3ea7ce977ae1cd9e42523522ce9a3374f10646e`: the authenticated headquarters
showed `openai / gpt-5.6-luna`, medium reasoning, API key ready, and the
operator gate configured without exposing values. The visible 0/5 fallback
is now diagnosable as “operator authorization not supplied,” rather than
being confused with a provider outage.

Production receipt: revision
`5654d74073656cb3ae225def1572ef74b450d67f` was publicly smoke-verified and
then refreshed through the authenticated league surface. The private
identity remained Lulu’s Potatoe’s; team construction showed 30/30 market
coverage at 835.54; Jimmy Horn showed the 43-point internal proxy with its
trace. The repeatable lesson is to verify the refreshed private bundle, not
only the deployed code revision.

## 2026-08-25 prior writer runs need model reconciliation

A run completed before the configured model changed is historical evidence, not
proof that the current model was used. The Writer Desk now compares the
persisted, user-scoped article receipts with the configured model and reports
when a prior run needs regeneration. This keeps the cost boundary legible and
prevents an old artifact from masquerading as current Luna output. It remains a
receipt, not permission to rerun; the operator token and the five-article
publication proof are still required.

Production proof at code revision
`92ae655ede886f601001101dd4c4850d332c1223` passed public smoke and
authenticated Chrome. The live Writer Desk identified Lulu’s Potatoe’s,
showed `gpt-5.6-luna` and API-key readiness, and reported the persisted prior
run as model-aligned. Because the operator key was not supplied, the reader
correctly remained at 0/5 fallback; model alignment is not the same thing as a
fresh generation receipt.

## 2026-08-25 - Manager outcomes must be source-backed, not implied

Manager history had transaction depth but no observed season result seam. The
refresh now keeps Sleeper matchup payloads raw, normalizes exact weekly
opponents and scores, and joins them into the per-season manager ledger. The
dossier reports `recorded`, `partial`, or `not_recorded`; an empty/offseason
source cannot become a fabricated 0-0 record. The browser also uses `n/a` for
matchup coverage when outcomes are unavailable, so the absence remains visible
at the point of decision.

This is the reusable pattern for future analyst depth: create an evidence
object with stable IDs, source trace, and explicit coverage first; then let
the dossier and writers explain it. A production refresh is still required
before claiming that the durable private bundle contains the new historical
outcomes.

Production proof at revision
`201c3f7d2d6319dae7bdfc246ebb1f12f9aa3fed` passed public smoke and the
authenticated private route. Lulu's Potatoe's remained linked to exact
`roster_id=2`; the live dossier rendered `45-37-18` across 108 recorded
matchup rows and exposed the `manager_season_history;matchups` trace. The
operator-gated writer remained visibly at `0/5`, so deployment verification
did not get confused with a paid Luna publication.
## 2026-08-25 - Market values and baseline PPG must carry their limits

The market audit found a scale seam in DynastyProcess `values.csv`: the
`value_2qb` field is stored in x100 units. A conditional divide made a raw
value of `93` render as `93.0`, while `7592` became `75.92`; that could rank
Jalen Nailor above Jayden Daniels. The normalization now divides every
DynastyProcess value by 100, records the scale in `value_format`, and leaves
the trace `value_2qb/100` beside the source URL. This is a deterministic
contract and must be regression-tested with values below 100.

The projection number has a separate boundary. `projected_ppg` is a baseline
production estimate, not a start forecast or availability guarantee. Sleeper
injury status and body part now survive the player and roster joins, appear in
player dossiers, and are included in signal evidence/risk. An injury flag does
not rewrite the baseline, but the reader must not mistake a healthy-looking
number for current availability. Missing injury metadata means unknown, not
cleared.

## 2026-08-26 - Canonical market values cannot be heuristically rescaled

The first scale fix exposed a second seam downstream: signal code divided any
canonical market value above 100 by 100. A legitimate `102.32` asset therefore
became `1.0232`, inflating the projection-market gap and making the newspaper
headline look more confident than the evidence warranted. Source-unit
conversion belongs at ingestion; signal code must consume canonical values
without guessing from their magnitude.

The signal layer now preserves high-end values, caps only the display-oriented
liquidity component, and adds a role-uncertainty discount when an old player has
a very low market value. Those rows become `role_uncertain_watch` with a
`role_check` action, not a breakout claim. The front page calls these rows
model disagreements or research leads, never guaranteed mispricing.

## 2026-08-26 - A newspaper front page needs connected rails

The editorial facade now exposes four deterministic front-page panels: the
selected roster pulse, news linked to that roster with market context, model
disagreement candidates, and manager dossier previews. Each item retains an
entity anchor, source trace, uncertainty copy, and route into the relevant
data-room or dossier view. This keeps the media layer useful before a Luna run
and gives generated writers a durable front-page context to interpret rather
than inventing a second data model.

## 2026-08-26 - Publication bodies need a semantic template contract

An article receipt and a markdown file are not yet a media product. The issue
now exposes a desk-specific publication template plus semantic content blocks
for headings, paragraphs, and lists. Markdown remains the operator/writer
interchange format; the browser renders the same blocks through reusable
feature, wide, and rail layouts. This lets each reporter feel distinct while
keeping the evidence packet and fallback body shared.
## 2026-08-25 - Three clocks, three market questions

A dynasty front office cannot use one player grade for every decision. The next
game asks who can help immediately; the rest-of-season lane asks how much
current-season production remains; the dynasty lane asks what the asset is worth
through the career window. These are related but not interchangeable questions.

The deterministic `player_horizon_market_scores` table now makes those clocks
explicit and adds contender/rebuilder fit scores plus a spread. The next-game
lane is labeled opponent-neutral while weekly data is only a flat allocation,
and Sleeper availability can reduce expected points without rewriting the
underlying season baseline. The dynasty lane is a market/timeline lens, not a
career-points forecast. Every writer packet should carry all three lanes when
making a player case so the human manager can choose the weight that matches the
team's current objective.

## 2026-08-26 - Schedule context must be evidence, not decoration

The next-game clock is useful only when the data room can answer who the team
plays and whether it is on a bye. The normalized `nfl_schedule` table now owns
that answer, while `nfl_team_defense_factors` supplies a bounded historical
position-level context. The player card can therefore say “at opponent” and
show the factor without pretending it has a complete defensive model. Partial
or missing schedule coverage remains visible as opponent-neutral, and the
rest-of-season clock counts scheduled games rather than silently treating every
calendar week as a game.

The long clock needs the same discipline. A five-year age-curve scenario can
make future production comparable across assets, but it is not the market and
it is not a lifetime total. Keep its score, assumptions, status, and confidence
separate so the reader can value a young player for future output without
mistaking a model scenario for a fact.

## 2026-08-26 - Matchup adjustments need calibration receipts

Historical matchup factors should earn their place in the next-game read. The
deterministic factor table now compares later-season game totals with both the
factor-adjusted expectation and the position baseline, carrying holdout sample,
MAE delta, direction accuracy, and a clear validation status into the player
horizon and writer packet. A limited or non-improving receipt is a visible
qualification, not a hidden confidence boost.

## 2026-08-26 - A score is not useful until it has a decision surface

Three-clock scores buried in a player dossier still leave the reader to perform
the league-wide comparison manually. The Trade Desk therefore exposes the same
canonical horizon rows as a filterable Active Team/League market board, with
contender/rebuilder lanes, explicit sorting, player routes, and row-level
evidence drawers. Browser controls are presentation-only: they may change scope
and ordering, but never alter the source rows or create a new recommendation
model.

The same rule applies to the score itself: every horizon row carries a model
version and fit-weight receipt. A refresh may update evidence while preserving
meaning; a formula change must be visible as a new version.

## 2026-08-26 - Availability is not a recovery timeline

The next-game clock can incorporate a current availability flag because the
manager is making an immediate lineup decision. The rest-of-season clock is a
production baseline unless the data room contains a defensible recovery and
availability timeline. Every receipt and reader-facing template therefore says
that the rest-of-season baseline is not recovery-adjusted. A current injury
flag must not be silently stretched into a season-long forecast.

## 2026-08-26 - Percentile scores are not trade prices

The horizon market uses position-relative percentiles so that next-game,
rest-of-season, dynasty, and bounded career-window evidence can share a stable
0-100 analytical language. That creates a hard presentation boundary: a 90 at
one position is not a 90-unit trade value and is not directly comparable with a
90 at another position. The reader needs the separate market value and market
percentile fields for cross-position pricing. Keep the score basis in the
deterministic row, article packet, and evidence drawer so writers cannot turn a
peer-relative signal into a fake universal market.

## 2026-08-26 - A career scenario needs a production receipt

The five-year career clock is more useful when it is anchored to observed
production, but the source identity is not the same as Sleeper identity. The
model now uses a unique normalized-name plus position match to one nflverse
player ID, blends recency-weighted historical PPG with the current projection,
and shows the depth of that history. If the bridge is missing or ambiguous,
the model says so and falls back to the age-only scenario. This keeps more
signal without disguising a name match as a canonical entity join.

## 2026-08-26 - Historical production must not impersonate current availability

Historical nflverse production is useful evidence, especially for a dynasty
front office, but it answers a different question from whether an asset has a
current NFL role. A current Sleeper player row with no NFL team is therefore a
`no_current_nfl_team` availability state. Preserve the historical PPG baseline
so a writer can discuss a conditional signing or career case, but withhold
actionable next-game and rest-of-season scores, lower confidence, and label the
baseline as conditional on signing. This prevents a free-agent veteran from
appearing like an active weekly starter merely because the historical sample is
large.

The newsroom can then choose the relevant clock deliberately: the next-game
desk prioritizes current role and availability, the season desk prioritizes
scheduled games and current-season production, and the long-view desk uses
market, age, and historical evidence with explicit uncertainty. No writer has
permission to silently decide which clock a number belongs to.

## 2026-08-26 - Writers need an editor before the facade

Distinct reporter voices are useful only when they are differentiated views of
the same validated packet. Each generated article may receive bounded previous
or peer-edition context to create disagreement and continuity, but that room
context is non-evidence and never replaces the deterministic receipt. A
deterministic desk-editor gate reviews required structure, evidence IDs, source
IDs, and generation mode before publication. Held copy stays off the printed
facade with the reason visible in the receipt, so editorial energy can add
meaning without weakening factual trust.

The editor is now an explicit optional second pass, not just a future idea.
`FRONT_OFFICE_EDITOR_MODE=llm` sends the same canonical packet and a bounded
draft to Luna. Approve, modify, and hold are durable review outcomes; a modify
must be a complete replacement that passes the writer validator, and a hold is
excluded from peer context as well as the printed facade. The deterministic
gate remains authoritative, and the editor cannot add facts, scores, motives,
transactions, or sources.

## 2026-08-26 - A market disagreement needs a decision surface

Four separate clock-minus-market fields are useful evidence, but buried fields
still make the manager do the synthesis manually. The Four-Window Market Read
now has a dedicated Market vs Clock section, and the Trade Desk exposes
position-scoped sorting for disagreement, clock lead, and market lead. The
surface remains explicit that these are repricing leads, not dollar gaps or
proof of a bad market.

## 2026-08-26 - Availability context must survive the projection table

The prior availability repair stopped signals from entering actionable lanes,
but the projection table still carried the historical number without enough
context. Availability scope, status, and note now travel through source
components, season consensus, and weekly allocation. The trust gate checks
both the columns and their semantic caveats, while the generic table formatter
uses conditional signing/active language. A green projection row is therefore
not allowed to mean more than its source snapshot supports.

## 2026-08-26 - Personal newsroom quality target is Luna max

The personal writer target is OpenAI `gpt-5.6-luna` with
`reasoning.effort=max`. The provider boundary defaults to that setting but
keeps an explicit environment override for intentional cost/latency choices;
the model and effort must remain visible in preflight and publication receipts.

## 2026-08-26 - Conditional baselines must stay out of current-role action copy

The current-role action view is a stricter boundary than the projection table.
Players whose Sleeper rows have no current NFL team may retain a conditional
historical PPG baseline for dynasty context, but they cannot calibrate the
active projection cohort or appear as current-role Cornerstones or Shop
Candidates. The fallback report now carries separate counts for current-role
and conditional baselines, and the signal row exposes
`availability_conditioned_unavailable` when a current market gap cannot be
trusted. The safeguard is included in the deployed `main` revision;
publication still requires the current writer receipt and authenticated smoke.

## 2026-08-26 - Writer scopes must inherit current-role action boundaries

The fallback Topline report and the paid Topline packet are the same product
boundary. If the fallback excludes a no-team player from Cornerstones and Shop
Candidates but the LLM scope still labels that row as ordinary player evidence,
the writer can recreate the regression. The team-report scope now filters
`no_current_nfl_team` rows out of its current-role player packet, while deeper
horizon and data-room surfaces preserve conditional dynasty context. Scope
generated player packets also carry `player_name` for the shared validator;
that validator strips the display name before checking caveat language so
player names cannot accidentally satisfy the availability contract.

## 2026-08-26 - Healthy availability is not an injury caveat

Editorial receipts should report only meaningful limitations. The boundary
checker now treats `Active`, `Available`, `Healthy`, and
`No current Sleeper injury flag` as clear availability, while preserving
warnings for real limited statuses such as `Questionable`, `Out`, `IR`, and
`PUP`. This keeps healthy articles quiet without relaxing the requirement that
injury-sensitive rest-of-season claims acknowledge the missing recovery model.
