# Front Office product research and build playbook

Status: durable guidance, reviewed 2026-08-25

This document preserves the research synthesis and product lessons behind the
Front Office realization epic. It is intentionally practical: future work
should use these rules to choose the next vertical slice and to reject work
that only makes the interface look busier.

## The product pattern

Fantasy Dominator is a private publication over a trusted data room. The
useful loop is:

```text
question -> validated evidence -> deterministic signal -> analyst lens
         -> decision packet -> human action -> recorded outcome
```

The product has three distinct layers:

1. Personal context: Clerk identity, linked Sleeper user, league, exact
   `roster_id`, strategy profile, and private history.
2. Data room: raw source payloads, canonical tables, derived signals,
   projections, freshness, confidence, and source/evidence receipts.
3. Publication: daily stories, reporter voices, dossiers, visualizations,
   and optional generated media.

The layers should feel like one experience, but they must not be collapsed.
The publication makes the data room understandable; it does not become a
second source of facts.

## Research-derived presentation rules

### Lead with a takeaway, then prove it

The front page should answer “what matters to my team today?” before exposing
the full table set. Every story needs a thesis, the change behind it, the
decision or question it creates, and a short route to proof.

### Use the right visual for the question

Charts and interactions are editorial instruments, not decoration:

- change over time: slope, timeline, or sparkline;
- ranking: ordered list or percentile band;
- disagreement: comparison or diverging view;
- roster construction: positional composition;
- trade fit: two-sided asset and need comparison;
- uncertainty: confidence, evidence count, and freshness together.

If a visual does not make a decision faster or reveal a relationship that
prose cannot, do not add it.

### Give readers progressive disclosure

The useful order is summary, explanation, compact evidence labels, then the
full data room. Keep raw source traces and long tables available in drawers,
detail pages, or filters without forcing them into the headline experience.
Player and manager pages should support the same path from quick read to
historical detail.

### Treat content as structured objects

An article, evidence packet, dossier, media asset, outcome, and publication
receipt are durable objects with IDs, scope, ownership, status, timestamps,
dependencies, and history. Markdown and HTML are rendered views of those
objects, not their only representation.

### Make the publication feel authored without hiding limitations

Distinct reporters should ask different questions and disagree in emphasis,
but they all receive the same validated evidence boundary. The interface must
show reporter, mode, confidence, freshness, fallback state, and source path.
An honest deterministic fallback is a usable product state; it must never look
like a completed LLM issue by accident.

## Data and identity rules that cannot be traded away

- Sleeper owns league identity, rosters, users, transactions, drafts, picks,
  and player metadata.
- Raw payloads are preserved before normalization.
- Deterministic code owns facts, joins, projections, scores, labels,
  freshness, confidence, and source traces.
- The identity chain is `Clerk user -> Sleeper user -> league -> roster_id ->
  team profile`. Names are labels and may change; they are never keys.
- Private strategy, articles, dossiers, feedback, and media must be scoped to
  user, league, and exact roster. Shared or legacy artifacts require a matching
  identity receipt before they can be served.
- Evidence IDs identify the exact validated rows behind a claim. Source IDs
  identify the upstream trace. Never present one as the other.
- A recommendation is decision support, not an instruction. Show why, risk,
  confidence, counterparty fit, and what would change the view. Never execute
  or communicate a trade.

## LLM and generated-media boundaries

LLM calls are explicit, paid editorial work. Use deterministic computation for
repeatable analysis, send only the selected league's validated context, and
skip generation when the relevant evidence fingerprint has not changed. The
configured Luna model is `gpt-5.6-luna`; reasoning effort is a separate
configuration value. Preserve provider, model, effort, reporter, evidence,
and validation metadata in the receipt.

Generated images are atmosphere and recognition, not evidence. Keep factual
text, statistics, logos, and claims in accessible HTML/data visualizations.
Version each asset with scope, prompt/model metadata, content hash, dimensions,
alt text, publication status, and responsive variants. Missing artwork must
never block the truthful text and data experience.

## Anti-recursive implementation checklist

Before calling a slice complete, verify all of the following:

1. Contract source: the test or acceptance check names the doctrine it
   enforces (`AGENTS.md`, the data contract, principles, or this playbook).
2. Real entry path: the capability is reachable from the user-facing surface
   and tested through its actual browser/API/store wiring.
3. Seam failure: the contract fails closed when identity, evidence, freshness,
   storage, or provider state is missing; it does not rely on a caller to
   compensate.
4. Consumer inventory: before deleting or replacing an artifact, enumerate its
   runtime readers, migrations, and deployment effects.
5. Honest gate: report proximity to freshness or coverage failure, not only
   PASS/FAIL. A wrapper must preserve the underlying exit code.
6. Deployment proof: verify the expected rendered bundle revision, session,
   league, exact roster receipt, visible entry marker, and fixture freshness.
   A healthy endpoint or successful build is not enough.
7. Antagonistic pass: ask how the slice could show the wrong team, stale shell,
   unsupported claim, duplicated cost, or decorative output while still
   appearing successful.

## Current realization boundary

As of this review, the repository has the foundation for structured receipts,
question-led presentation, exact roster identity, manager/trade evidence,
learning signals, responsive masthead media, and deterministic fallback
parity. The first article-specific media slice is now also wired for the daily
brief, team report, market watch, and trade desk; it remains decorative and
optional by design. The following remain explicit next work rather than implied
promises:

- complete and verify the protected Luna publication run;
- deepen manager dossiers with season history, sample sizes, and supported
  trade-fit questions;
- make Trade Desk packets consistently two-sided and read-only;
- expand the question-led data room without adding unmotivated charts;
- expand reporter-specific and article-specific media only where it improves
  recognition or comprehension;
- use the new reporter learning ledger to accumulate enough recorded outcomes
  for useful, honest evaluation of content and prediction quality.

When this status changes, amend this section and the decision log in the same
change. Do not leave a historical success claim looking current after the
underlying deployment, data, or content state has changed.

## Reference material

The original research references remain in
[`front_office_realization_epic.md`](front_office_realization_epic.md), under
“Research-derived principles.” They include The Pudding's data-story process,
Baseball Savant's layered player presentation, structured editorial content
workflows, the Financial Times Visual Vocabulary, OpenAI image-generation
controls, responsive image delivery, and WAI image accessibility guidance.

The implementation contracts remain authoritative in:

- [`front_office_principles.md`](front_office_principles.md)
- [`data_contract.md`](data_contract.md)
- [`production_runbook.md`](production_runbook.md)
- [`anti_recursive_dev_audit.md`](anti_recursive_dev_audit.md)
- [`decision_log.md`](decision_log.md)
