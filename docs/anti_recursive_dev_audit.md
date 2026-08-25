# Anti-recursive development audit

Audit date: 2026-08-24  
Starting tree: `54fd2ac`; the landing commit for this audit is the current
source of truth after it is created.  
Source rubric: user-supplied `anti-recursive-dev-classes-8-13.patch`

The supplied file is a delta against another project's `.claude/skills/` tree,
not a standalone skill. Fantasy Dominator adopts the six failure classes and
two orchestrator duties as repository practice without importing that foreign
skill wholesale.

## Findings

| Class | Fantasy Dominator finding | Current control or action |
| --- | --- | --- |
| 8. Loyal test | Behavioral tests exist, but the corpus does not yet require every test to cite its design source. A green test can therefore describe implementation history rather than product law. | New contract-sensitive tests must cite `AGENTS.md`, `docs/data_contract.md`, or the relevant product contract. Treat uncited tests as evidence of current behavior, not immutable law. |
| 9. Tested-but-unreachable | The prior Sleeper cache repair was directly tested, but the production relink path did not assert cache bypass. | Relinking now calls discovery with `force=True`; API entry-path tests assert that keyword, and cache tests use distinct league payloads. |
| 10. Mislabeled cargo | No deletion appears in the recent `main` history, so there is no confirmed current incident. The risk remains for future “cleanup” of raw caches, bundle files, or UI rails. | Before deletion, enumerate runtime consumers and preserve a receipt or migration fallback. |
| 11. Compensated violation | Identity and private-bundle boundaries have direct fail-closed tests. No new compensated leak was found in this audit. | Keep seam tests direct: wrong roster, missing identity, wrong user, and legacy fallback must each be attacked without relying on a caller's filter. |
| 12. Knife-edge pass | The local data gate previously emitted age and verdict but not the remaining freshness margin. | `validate_local_data.py` now reports `freshness_margin_hours` and warns before the hard age limit. |
| 13. Claim rot | `README.md`, `config/leagues.yml`, and the sprint plan still described the historical Melkor label as current after the Sleeper rename. | Claims were amended on 2026-08-24. Future current-state claims must carry an observation date and be rechecked against the current tree/source. |

## Orchestrator duties

- Gates are run independently: the full unittest suite, local data audit, diff
  check, and—when deploying—the revision-aware live smoke. Do not pipe a gate
  into a formatter and trust the formatter's exit code.
- A browser check is evidence only when its session, visible page, viewport,
  target revision, and data freshness are known. If any precondition is not
  observable, the result is `NOT DONE`, not a green measurement.

## Remaining work

The next hardening slice is to add a lightweight design-citation convention to
the older behavioral tests and to add an authenticated browser smoke that
asserts the current user's exact roster receipt, not just generic page markers.
Those are separate from this audit because they need the real Clerk session or
an explicit fixture contract.

## 2026-08-25 follow-up

The local gate now includes a generated-bundle JavaScript parse check, article
receipt/reuse tests, and stale publication-receipt tests. The remaining
production-specific item is still open: run the revision-aware authenticated
Railway browser smoke against the signed-in Clerk identity and prove the exact
Sleeper roster receipt. Older behavioral tests remain behavior evidence until
they are gradually amended with direct design-source citations.

The 2026-08-25 contract slice adds direct tests for canonical evidence packet
quality labels, structured article defaults, reporter attribution on
deterministic stories, explicit publication receipt fields, and provider usage
metadata capture. These tests encode `AGENTS.md` and
`docs/front_office_realization_epic.md`; they do not turn a local green result
into proof that Railway is serving the new revision.

The authenticated Railway browser check on 2026-08-25 made that distinction
concrete: production correctly resolved the signed-in user's dynasty roster
as `roster_id=2`, and Sleeper identified `Moose Caboose` as `roster_id=4`, but
the live bundle did not contain the local question-led Data Room marker. The
next deployment gate must compare the expected revision and rendered entry
path, not only a successful login or a healthy API response.

## 2026-08-25 production follow-up

The revision-aware public smoke passed for commit
`b860da7ede3c33155039dca8093ef882301b4824`. A signed-in Chrome check of the
direct owned-league entry path rendered the current Sleeper label
`Lulu’s Potatoe’s`, five publication receipts, the fallback marker, and the
question-led Data Room with its Decision ledger and change-history section.
The authenticated smoke script remained intentionally skipped because no
`FRONT_OFFICE_SESSION_TOKEN` was supplied; the browser session is the evidence
for the visible authenticated surface. Railway still reports `0/5 reporter
articles` and deterministic fallback mode, so this verifies deployment and
identity continuity—not that a production Luna generation has occurred.

## 2026-08-25 browser propagation follow-up

The player-dossier refinement exposed a deployment-verification trap: a fresh
health response can report the intended Railway revision while an already-open
authenticated browser still presents the previous durable shell during
propagation. The verification gate therefore requires the owned-league route,
the rendered entry marker, and the bundle manifest's `sourceRevision` after a
clean reload and settled page load. The check then confirmed revision
`c91108bc74be7aa010652cfb57dd532f4ba4c3b1`, `Opponent roster`, the compact
evidence chain, and the full source-trace drawer.
This closes the manual authenticated browser verification item; the automated
`FRONT_OFFICE_SESSION_TOKEN` smoke remains intentionally not run.

## 2026-08-25 current deployment amendment

The `c91108bc` revisions noted above are historical browser observations. The
writer-receipt diagnostic slice then had a settled signed-in owned-league
route that reported source revision
`831fca842aaf05be09dc9b748063fb644c68d3d0`, league
`1313490073630547968`, and a verified exact `roster_id=2` receipt for
`Lulu’s Potatoe’s`. The Data Room displayed the new per-article receipt
warning and the existing `0/5 reporter articles · evidence-led fallback`
state. Public revision smoke passed; automated authenticated smoke remains
not run because no session token was supplied. This verifies deployment and
identity continuity, not successful Luna publication.

## 2026-08-25 timing and migration follow-up

The manager-season depth slice found a new instance of the anti-recursive
failure pattern: enriching an old durable dossier changed its receipt status
from `updated` to `unchanged` on the second source-only shell rebuild. The
first run looked correct, but the bundle was not idempotent. The migration now
preserves the prior dossier receipt state because it is not a new analytical
refresh, and `test_shell_rebuild_migrates_legacy_fallback_receipts` asserts the
bundle revision is stable on the second rebuild. The manager ledger also
records observed transaction weeks separately from any interpretation of
manager intent.

## 2026-08-25 story-spine migration follow-up

The fallback story-spine implementation is present in source and local bundle
tests, but the first production verification after revision
`3ca2e6b4925e5eccee9ededb4137b0d6bc4c6bbc` found a preserved user-scoped
payload still exposing the older empty `lede`, `thesis`, and `what_changed`
fields. The browser reported the current source revision, so this is not a
source/deploy mismatch; it is an incomplete durable-artifact migration or
serving-path defect. The gate remains open until a clean authenticated reader
load proves the current fallback schema or a current Luna receipt. Do not
weaken the receipt assertions or treat the health endpoint as proof of content
propagation.

## 2026-08-25 migration gate closed

After `a69e7fd30de84266029163248ef387855f5c3077` deployed, the clean signed-in
reader path self-healed the preserved bundle. The browser showed the current
source revision, verified `roster_id=2`, `Lulu’s Potatoe’s`, the
`deterministic_fallback_v2` story spine, and a visible visual-direction receipt
with evidence/source traces. The public smoke also passed against that exact
revision. The stale durable payload was therefore a real migration seam, not
a permanent production data loss; the new guard and entry-path tests now cover
it. The protected Luna run remains separate and is still pending operator
authorization.
