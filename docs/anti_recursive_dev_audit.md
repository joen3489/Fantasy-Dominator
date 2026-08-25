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

## 2026-08-25 - Current reader verification reopens the serving seam

The next deployment, `0c7b052`, passed public smoke at its expected revision,
but the clean signed-in manager route still embedded `99b39f6` and omitted the
new manager dossier entry markers. This is a fresh instance of the same
anti-recursive failure class: deployment health was treated as a proxy for the
actual user-facing artifact. The migration gate is therefore open until the
route exposes a safe selected-bundle/migration receipt or refuses to serve a
stale shell after recovery fails. The protected Luna boundary remains
unchanged and no paid generation should be used to mask this serving defect.

The implementation now does both: authenticated status/readiness exposes the
safe receipt, and the league route fails closed with a recovery response when
the post-migration bundle is still stale. The production browser evidence is
now present for `acd8c3ab3b1bf69581cd8fa95b8c7c9f45994683`: after a fresh
reload, the authenticated route reported the current private bundle, exact
`roster_id=2` identity, and the cross-season dossier marker; a repeat direct
entry stayed current. The initial stale navigation is retained as a
browser-freshness warning, so future verifiers must reload or otherwise prove
the fresh response before trusting the page.

## 2026-08-25 - Historical player rows need stable identity and both directions

The next audit found a different shallow seam: `player_transaction_history`
stored player names without the Sleeper IDs available in raw `adds`/`drops`,
and trade rows described only acquisitions. A history table could therefore
look populated while failing to join to the player page or explain what a
manager gave up. The normalization and profile layers now preserve source ID
lists, emit acquired and sold events, and label every resolution path.

The adversarial tests cover direct IDs, unique normalized-name recovery,
ambiguous names, unmatched names, and the sold-side trade event. A fresh local
refresh resolved all 3,101 rows by source ID and passed the full 188-test gate;
the generated CSVs remain ignored artifacts, so the durable contract is the
code, docs, and test coverage rather than an accidental checked-in snapshot.

The local trust gate now audits this contract directly. This prevents a
future refactor from preserving the column names while dropping IDs, changing
trade direction semantics, or erasing source traces; unresolved legacy names
remain a visible warning rather than a silent pass.

## 2026-08-25 - Semantic gates must reach the reader

The local validator had a stronger player-history identity receipt than the
browser surface, creating a new seam where the product could look fresh while
its historical joins were weak. The bundle now carries the deterministic
receipt, the Data Room renders it, and the serving contract rebuilds a durable
bundle that lacks it when a deployment revision is present. Entry-path tests
cover partial coverage, malformed rows, and a missing durable receipt. This is
the reusable rule: a semantic gate is incomplete until its limitation is
visible at the point of consumption.

## 2026-08-25 - A configured strategy must reach the decision surface

The My Team page exposed strategy metadata while explicitly leaving value tags
as a future feature, even though deterministic fit, need, liquidity, and action
tables already existed. That is a shallow-but-green seam: the data pipeline can
be correct while the product remains generic. The browser now joins the exact
active `roster_id` and `player_id` rows, renders alignment and action mix, and
marks missing fit rows `not_scored`. The entry-path test asserts the real My
Team surface contains these joins and no longer contains the planned-overlay
claim.

## 2026-08-25 - The learning loop must reach decisions, not just prose

The existing ledger could evaluate article usefulness while actionable thesis
cards had no outcome path. That created a plausible but shallow learning
surface. The decision cards now reach the real scoped interaction endpoint;
the seam validates recommendation-specific artifact type and outcome states,
stores the bundle/evidence context, and reports recommendation rates separately
from reporter rates. Tests cover the authenticated entry path, invalid states,
and the separation of the two summaries.

## 2026-08-25 - Entry-path markers must invalidate durable shells

The next production check found the same failure class one layer deeper: the
new recommendation-learning code was deployed, but an old durable shell still
passed the existing dossier and data-quality checks. The guard now treats the
recommendation outcome control, its `decision_outcome` wiring, and the
recommendation learning summary as a semantic reader contract. An adversarial
test uses a current source revision and valid preserved payload while omitting
those markers, proving that the route requests migration instead of returning
the old interface. Future slices must add their entry-path marker and stale
bundle test in the same change.

The guard is now verified in production at `375bed1368b9f2706af44138bbe6e23ee79663b8`:
public smoke matched the full revision, and the authenticated owned route
rendered the recommendation controls, separate learning summary, exact roster
identity, and semantic history receipt. The migration gate is closed for this
slice; browser freshness and exact entry-path proof remain required for the
next one.

## 2026-08-25 - Do not leave event evidence stranded behind aggregate metrics

The manager page could look complete while its event-level source table was
unreachable from the manager dossier. The new structured `transaction_timeline`
is built only from rows whose exact `roster_id` matches the dossier, is bounded
and ordered deterministically, and has an entry-path test for the rendered
timeline and event evidence. A foreign roster fixture is excluded. This keeps
the slice aligned with the identity and evidence rules before any writer
interpretation is added.

## 2026-08-25 - Direct manager decisions must reach the existing outcome seam

The manager dossier reused Trade Desk fit evidence but had no outcome control,
so the same hypothesis had different learning behavior depending on entry
path. The direct card now carries a stable `manager-fit` key into the existing
recommendation interaction endpoint with evidence, risk, confidence, and the
exact target player. The source-level entry test and authenticated browser
proof must cover the manager path; no second feedback table is allowed.
The deployed entry proof at `9fb20f8778fffb396e966af640fb11f6efc92824`
found six live `manager_fit` controls with roster/player keys and evidence.

## 2026-08-25 - Do not let a dossier-level overlap overstate each fit

The first cross-season evaluation reported aligned position groups globally,
which could make an individual current fit appear historically supported when
it was not. The structured evaluation now emits one alignment row per fit and
fails to a visible `no_direct_lane` state when no matching historical lane
exists. The adversarial analysis test covers the aligned case; future fixtures
must cover the no-lane case rather than weakening the label.
The production browser proof at `2c8d2a6de187a8db50b8c472d2c6df93d4eb12bd`
showed both states in the live manager dossier: three aligned and three with
no direct lane.

## 2026-08-25 - Data Room change receipts must use a prior scope

The first question-led event view correctly showed a current pulse but could
not yet answer a return visit's “what changed?” question. The reader now
computes `dataRoomDelta` before overwriting the durable bundle, compares the
three event tables by source IDs, and reports added/updated/removed counts.
The contract fails closed when the prior bundle or any comparison table is
missing; it never treats every row in a first snapshot as new. A unit test
covers the added-event ordering and incomplete-scope failure, while the
browser entry test requires the comparison copy and fallback marker. Future
changes must preserve the prior bundle boundary and keep strategic meaning in
the deterministic analysis layer rather than smuggling it into the delta.

The production entry proof at
`6e706ffff1643b8322b3a74fedcdafd9c531ed1f` matched public revision smoke and
the authenticated private Chrome route. The Data Room rendered the verified
prior-bundle receipt and a zero-added-event result without replacing it with
the unavailable state or exposing private implementation details.

## 2026-08-25 - Do not erase live readiness on a blocked write action

The production operator surface exposed a shallow state mutation: a missing
operator token replaced the full authenticated status receipt with a minimal
blocked object. The UI then displayed missing writer configuration even though
the prior status had provider/model evidence. The browser now uses an additive
status overlay for blocked and client-side failure paths. The entry-path test
requires the helper and its rationale, and the authenticated browser audit must
recheck that blocking an action preserves readiness evidence and does not call
the provider.

The production check at
`1be8e7c7160454dd28d9255cd4edce75e7e6e7c1` confirmed the exact failure seam:
the blocked action message appeared while the configured writer and
publication receipts remained visible. The action stayed fail-closed.

## 2026-08-25 - Team construction must be exact-scope presentation

The team entity page previously made the reader infer roster construction from
a long player list. The new construction panel uses the selected current
season and exact `roster_id`, keeps player joins on `player_id`, exposes
coverage and need/action evidence, and leaves missing joins unavailable. The
entry-path test requires the panel and evidence drawer, while the reader shell
contract adds its semantic marker so a stale durable shell cannot pass as the
current interface.

Production evidence at
`db6c71e34eb18c7069f7cd35361c83be65d39f48`: public smoke passed, and the
authenticated Moose Caboose route rendered the Team construction marker,
position mix, need lanes, recommendation mix, and Construction evidence for
roster ID 4. The root edition still identified Lulu’s Potatoe’s, so the new
surface did not cross the private identity boundary.

## 2026-08-25 - Do not let parallel economic joins disagree

The first Team construction panel used `player_dossiers` for market totals
while the manager dossier used `team_asset_inventory`. Live data exposed the
contradiction: the same 30-player roster displayed 720.54 in one place and
835.54 in another because four internal proxy values were omitted. The seam
now uses the canonical inventory ledger for totals, keeps projection joins
separate, and exposes `market_proxy_rows` plus the source table in the
construction evidence. The browser entry-path test protects the source
selection; production verification must check reconciliation, not only the
presence of a panel.

Production proof at
`eb9b68d96f40cffa0afec6131547be178d8f1395` verified the repair: the exact
roster-4 Team construction route showed 835.54 in both construction and the
manager dossier, `market_rows=30`, `market_proxy_rows=4`, and the canonical
`team_asset_inventory` trace. This is stronger evidence than a marker-only
entry check because it tests the disputed value across both consumers.

## 2026-08-25 - Player dossiers must share economic provenance

The same parallel-join pattern appeared at player grain: Jimmy Horn's entity
page used a profile row and showed market 0 while the exact roster asset ledger
held 43 as an internal proxy. The player entry path now joins the scoped
inventory row by `roster_id + asset_id`, shows the ledger/proxy descriptor, and
fails closed for an owned player when the row is missing. A profile fallback is
reserved for unrostered players. This extends the reconciliation check from
team totals to the individual decision object.

Production proof at
`b0142965abe1ba10986b40ed289eea21fa3b37e9`: Jimmy Horn's exact player route
showed market 43, `Market source: internal proxy value`, and the
`internal_proxy_player_value` trace. The same authenticated pass retained
the team-level 835.54 reconciliation and private Lulu’s Potatoe’s identity.

## 2026-08-25 - Do not leave proxy economics disconnected from decisions

The cross-table audit found 41 proxy-valued assets that were present in the
economic ledger but zeroed in profile, signal, and action tables. This was a
disconnected-depth defect: a source existed, but the decision seam ignored it.
The deterministic pipeline now propagates the fallback with an explicit proxy
trace and lower-confidence risk language. Local regeneration reports zero
mismatches. Production verification must include a scoped refresh and compare
the rebuilt tables, not merely inspect the already-published player card.
