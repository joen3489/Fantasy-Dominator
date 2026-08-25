# Front Office operating lessons

Last reviewed: 2026-08-25

This is the short, durable memory for Fantasy Dominator. It exists so future
work does not rediscover the same product and development lessons in chat.
The detailed requirements remain in `AGENTS.md`,
`docs/front_office_principles.md`, `docs/data_contract.md`, and
`docs/front_office_realization_epic.md`.

## Product model

Fantasy Dominator is a private personal headquarters with a media facade over
a trustworthy data room. It is not a generic fantasy dashboard and it is not a
collection of AI articles.

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

The durable-bundle migration and semantic-reader gates are closed for the
current deployment `ad08ef1f8b2b001fc71f8349651bd9028112273b`. A fresh,
authenticated direct entry served the current private bundle for exact
`roster_id=2` / Lulu’s Potatoe’s, rendered the Data Room's “Historical
identity receipt,” and reported 3,101 history rows, 3,101 resolved joins, zero
unresolved rows, and balanced acquired/sold trade direction. The reader receipt
reported `current · private`; public smoke independently verified the expected
deployment revision. Browser freshness remains an explicit verification
precondition because an already-open tab can retain an older shell until it is
reloaded.

The protected Luna publication is a separate open boundary: deterministic
fallback remains the honest reader state until the operator-authorized run
produces current per-article writer receipts. This is an explicit cost and
authority boundary, not a reason to weaken the receipt contract.

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
