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
