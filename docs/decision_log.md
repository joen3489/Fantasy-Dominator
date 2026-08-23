# Fantasy Dominator decision log

This is a short memory of decisions and failure modes that materially affect
the product. Add an entry when a future implementation changes one of these
boundaries.

## 2026-08-23 — Preserve the doctrine in the repository

The project has accumulated useful decisions across code, deployment debugging,
and prior planning. The durable version now lives in `AGENTS.md`,
`docs/front_office_principles.md`, and `docs/production_runbook.md` so a future
coding session does not have to reconstruct the product from chat history.

## Identity and continuity lessons

- Team names and display names are mutable labels. An exact configured
  `roster_id` must win over stale names when normalizing or serving a private
  edition.
- The correct continuity chain is Clerk user → linked Sleeper user → league →
  roster. Losing any link can make a healthy-looking app show the wrong team or
  appear empty after login.
- User/league state needs additive, durable storage fields for the linked
  Sleeper account and identity-check receipts. A local fixture or legacy bundle
  is not proof that the authenticated user owns the content.
- Shared legacy artifacts are useful migration fallbacks only when their
  identity receipt matches. A private bundle must never be selected by name
  alone.

## Data and freshness lessons

- Deterministic facts and source traces are the foundation. LLM prose cannot
  compensate for stale, missing, or ambiguously matched source data.
- A refresh receipt must distinguish current, limited, disabled, unavailable,
  and stale sources. Optional sources such as Fantasy Nerds may be disabled
  without breaking the Sleeper-first build, but that limitation must remain
  visible.
- Local validation is necessary but not sufficient. The live revision, live
  auth configuration, durable `/app/data`, and real browser identity path all
  need separate verification.

## Editorial and generation lessons

- One global writer voice flattened the publication. The newsroom now assigns
  distinct reporters to topline, waivers, trade desk, manager intelligence, and
  look-ahead work, with league-scoped overrides.
- Personas change emphasis and tone, never evidence ownership. Every writer
  receives only the selected league’s validated context and must preserve
  citations, uncertainty, and read-only behavior.
- Dossiers should be durable intelligence, not disposable prose. Fingerprint
  relevant evidence and mark each result `new`, `updated`, or `unchanged` so
  expensive generation is incremental.
- The OpenAI provider boundary is explicit. The configured model is
  `gpt-5.6-luna`; reasoning effort is configured independently. Provider/model/
  effort metadata belongs in generation receipts.

## Known debt to keep visible

The last local verification passed the test suite and local data audit, but the
refresh receipt was roughly twenty hours old and the optional Fantasy Nerds
source was disabled because its API key was absent. Those are known data-state
limitations, not reasons to claim that production is fully verified. Live
authenticated browser continuity and Railway durable-storage verification must
remain part of the next production check.

## Do not regress these boundaries

- no Sleeper mutation, trade execution, or outbound manager messaging;
- no private content in a shared bundle;
- no name-based identity fallback when a roster ID is available;
- no generated fact rows in canonical processed tables;
- no automatic recurring LLM generation without an explicit cost/control
  boundary;
- no “production is working” claim based only on local tests or `/healthz`.
