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

## Current open boundary

The durable-bundle migration gate was closed on 2026-08-25 after a clean
authenticated production entry path exposed source revision `a69e7fd`, the
verified `roster_id=2` receipt for Lulu’s Potatoe’s, the v2 fallback story
spine, and the visual-direction receipt. The remaining open boundary is the
protected Luna publication: deterministic fallback remains the honest reader
state until the operator-authorized run produces current per-article writer
receipts. This is an explicit cost and authority boundary, not a reason to
weaken the receipt contract.

The article-specific media slice is live on `e830e05`: the signed-in edition
loaded four 1536px desk illustrations, kept the exact `roster_id=2` identity
for Lulu’s Potatoe’s, and exposed media metadata beside the evidence receipt.
Lazy artwork must be checked after it enters the viewport; an initial DOM
presence check is not proof that the browser loaded the asset.
