# Fantasy Dominator agent guide

This repository is the Fantasy Dominator personal fantasy-football front office.
The product is a private, browser-first media experience over a trustworthy
Sleeper data room. Future changes should make it easier for one manager to
understand multiple teams, find actionable edges, and read evidence-backed
editorial written in distinct voices.

## Non-negotiable product rules

1. Sleeper is the source of truth for league identity, rosters, users,
   transactions, drafts, picks, and player metadata.
2. Preserve raw source payloads before normalization. Deterministic code owns
   facts, joins, scores, projections, labels, freshness, and source traces.
3. The identity boundary is explicit:
   `Clerk user -> Sleeper user -> league -> roster_id -> team profile`.
   A display name or team name is never a substitute for a roster ID.
4. League/team customization is private state. It must not leak between users,
   leagues, or rosters, and it must not overwrite canonical source facts.
5. Writers are editorial lenses over validated evidence. They may emphasize,
   explain, and disagree; they may not invent facts, replace deterministic
   analysis, execute trades, send messages, or imply that an estimate is an
   observed action.
6. The human manager makes the final decision. Recommendations must show why,
   risk, confidence, and source trace.
7. Content generation is explicit and cost-incurring. Do not regenerate a
   dossier or article when its evidence fingerprint and relevant inputs have
   not changed.
8. The media facade should make the data room legible, not hide it. Every
   important story should have a path to the underlying evidence and freshness
   receipt.
9. The consumer product is decision-first. A prominent recommendation must be
   scoped to the selected league and exact roster and state the action, the
   current alternative, likely cost, why now, risk, confidence, and freshness.
   "No move" is a useful result; generic advice and filler are not.
10. Attention is a scarce product resource. Rank aggressively, suppress
    unchanged or duplicate recommendations, and fail closed on contradictory
    leads instead of publishing every available signal or article.
11. Copy earns space only when it states evidence, explains team-specific
    relevance, recommends an action, describes uncertainty, or identifies
    provenance. Editorial personality may aid comprehension but may not create
    competing sections or meaningless volume.
12. Keep operator machinery separate from the manager experience. Writer jobs,
    storage audits, packet states, and generation controls belong in an
    operational surface; the primary UI should lead with the manager's next
    decisions and work at a verified mobile viewport.

## Source-of-truth map

- `docs/data_contract.md`: enforceable table, source, trace, and V-model rules.
- `docs/sprint_plan.md`: ordered product roadmap and acceptance checks.
- `docs/front_office_principles.md`: product north star and design doctrine.
- `docs/reporter_personas.md`: writer voices and article assignments.
- `docs/production_runbook.md`: Railway, Clerk, durable storage, and smoke
  verification procedure.
- `docs/anti_recursive_dev_audit.md`: dated audit rubric for development
  failure classes and the current evidence-backed findings.
- `docs/front_office_operating_lessons.md`: compact durable memory of the
  product model, evidence/editorial boundaries, and anti-recursive guardrails.
- `docs/single_brain_decision_product_epic.md`: current execution epic for
  Codex-first editorial artifacts, canonical profiles, decision-led route
  composition, and the scheduled Luna operating loop.
- `docs/decision_log.md`: regression lessons and decisions that should not be
  rediscovered by future work.
- `config/leagues.yml`: legacy/default seed and strategy configuration; it is
  not a replacement for authenticated league-scoped state.
- `data/processed/`, `data/analysis/`, and `data/site/`: generated artifacts;
  inspect them, but do not treat generated prose as canonical facts.

When documents appear to conflict, use this order: raw source and code
behavior, `docs/data_contract.md`, this guide and product principles, then the
roadmap. Update the relevant document when a decision changes; do not leave
contradictory instructions in place.

## Safe change protocol

Before changing an identity, refresh, writer, or serving path:

- trace the full path from browser request to store/action, database or file
  write, generated artifact, and browser response;
- preserve existing user changes and unrelated work in the working tree;
- keep read-only behavior for Sleeper and external sources;
- make migrations additive and idempotent;
- add an adversarial test for the failure mode, not only a happy-path test;
- expose a receipt or status when identity, freshness, storage, or generation
  is limited;
- never add secrets, session tokens, or private production data to Git.

For LLM work, use the provider boundary in `src/llm.py`. Keep model/provider
configuration in environment variables, keep structured output schemas strict,
and pass only the selected league's validated context. Luna is the configured
OpenAI model (`gpt-5.6-luna`); `reasoning.effort` is a separate tuning value,
not part of the model name.

## Anti-recursive development guardrails

The project adopts the supplied anti-recursive-development rubric as a local
practice, not as a copied foreign skill file. For contract-sensitive work:

- behavioral tests should name the design source they encode; otherwise they
  document current behavior but do not establish product law;
- every designed capability needs an entry-path test from the user-facing
  surface through its real wiring;
- before deleting or retiring an artifact, enumerate its runtime consumers and
  effects rather than trusting its label;
- contracts must fail closed at the seam, even when today's caller filters or
  compensates for them;
- gates must report proximity to failure, not only PASS/FAIL; and
- dated claims must be amended with the same change that makes them stale.

Run gates as independent commands and inspect raw exit codes. A wrapper that
prints a failed command's output while returning success is not verification.
Browser and deployment verifiers must assert their preconditions (session,
viewport, visible surface, expected revision, and fixture freshness) before
trusting measurements; when those preconditions cannot be proven, report the
check as not done.

## Verification gate

Run the smallest relevant tests while iterating, then run the full gate before
handoff:

```powershell
python -m unittest discover -s tests -p "test*.py"
python scripts\validate_local_data.py
git diff --check
```

For a deployment, also run `python scripts\smoke_live.py` with
`FRONT_OFFICE_EXPECTED_REVISION` set to the commit that should be live. A
local green suite does not prove that Railway is serving the intended revision,
that the current Clerk identity can see its teams, or that `/app/data` is a
durable volume. Authenticated production verification is required for those
claims; see `docs/production_runbook.md`.

## Anti-regression checklist

- Can the current Clerk user see the same linked Sleeper user and roster after
  refresh, logout/login, and deployment?
- Does an exact `roster_id` win over stale or duplicate team names?
- Can a shared or legacy bundle ever serve private content for the wrong
  identity?
- Is every article assigned the intended reporter lens?
- Is the evidence current enough for the claim being made?
- Are unchanged dossiers skipped instead of spending another generation call?
- Does a degraded provider/source state remain visible to the reader?
- Does the UI present a useful story first while keeping evidence one click
  away?
