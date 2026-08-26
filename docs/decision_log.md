# Fantasy Dominator decision log

This is a short memory of decisions and failure modes that materially affect
the product. Add an entry when a future implementation changes one of these
boundaries.

Current publication count (2026-08-26): six desks are registered and surfaced:
Daily Brief, Team Report, Market Watch, Four-Window Market Read, Trade Desk,
and Manager Intel. Older entries that say `0/5`, “five desks,” or “five
articles” describe production checkpoints before `horizon_watch` was added;
they are historical receipts, not the current publication contract.

## 2026-08-26 - Availability must travel with projection baselines

The projection model intentionally preserves historical production when a
current Sleeper player has no NFL team, but that number is not a current
season or next-game forecast. Projection season, weekly, and source-component
rows now carry the current Sleeper availability scope, status, and note into
the consensus contract. The browser formats those values as `conditional
baseline PPG if signed` (or `if active`) and the player dossier uses the same
status precedence. This keeps useful history while preventing an unsigned or
injured player from reading like a healthy current projection.
The local trust gate also fails when the status is missing its corresponding
availability note or signing caveat, so a structurally complete but
semantically stale artifact cannot pass.

## 2026-08-26 - Default the personal newsroom to Luna max reasoning

The personal product's writer target is OpenAI `gpt-5.6-luna` with maximum
reasoning effort. The provider boundary now defaults to `reasoning.effort=max`
when Railway or a local secret store does not provide an override; operators
can still choose a lower setting explicitly for a deliberate cost or latency
tradeoff. The model slug and reasoning setting remain separate receipts.

## 2026-08-26 - Keep the aggregate operator receipt total

The authenticated aggregate `/api/operator/status` route must always return
the user's safe multi-league summary when no `league_id` query is supplied.
An unreachable return left the homepage status request as `None`, which
FastAPI rejected with a 500 even though the league-scoped status route still
worked. The route now returns the aggregate summary and includes the operator
enabled flag in the empty-workspace case; the regression test protects this
user-facing seam.

## 2026-08-26 - Do not call deterministic fallback editor-approved

The first production writer attempt refreshed the selected league and rebuilt
the bundle, but its six visible articles remained deterministic because no
current LLM artifacts were accepted. The publication reader previously
defaulted any valid deterministic receipt to `Editor approved`, which blurred
the difference between evidence-led continuity content and a paid reporter
draft reviewed by the desk editor. Deterministic receipts now publish as
`fallback` / `keep_fallback`: they remain readable and evidence-linked, but
they do not receive editor-approved feedback or outcome controls.

## 2026-08-25 - Separate bootstrap from maintenance refreshes

The refresh pipeline now has two lifecycle modes. Bootstrap is the first-time
historical assembly path. Maintenance is the recurring current-state path: it
uses a bounded week scope and merges exact-key canonical rows into the prior
snapshot before rebuilding derived outputs. This preserves the data foundation
while keeping routine updates cheaper and the refresh receipt truthful.

## 2026-08-25 - Preserve the research-to-build playbook

The research and product review is now captured in
`docs/front_office_research.md`. The durable lesson is that Fantasy Dominator
is a private publication over a data room: a story begins with a question,
uses validated deterministic evidence, applies a bounded analyst lens, and
ends in a human decision or recorded outcome. Presentation choices must serve
that path. Structured content, progressive disclosure, question-led visuals,
exact roster identity, evidence/source separation, bounded LLM use, optional
generated media, and revision-aware browser verification are now explicit
working rules rather than assumptions left in chat history.

At the time this playbook was adopted, the remaining realization boundary was
the protected Luna publication, deeper historical manager intelligence,
two-sided Trade Desk packets, and a measured learning loop. The Trade Desk,
manager dossier entry path, event pulse, and reporter coverage seam have since
been implemented and are recorded in later checkpoints below. The remaining
open boundary at that checkpoint was protected Luna publication plus the
accumulation of enough explicit outcomes to evaluate the newsroom honestly.
The latest production reader check reopened a separate serving-path boundary;
see the current reader-selection checkpoint below.

## 2026-08-25 - Self-healing publication migration verified

The durable-bundle guard now checks the fallback receipt schema in both the
manifest and embedded app bundle, not only the source SHA. A clean signed-in
production entry path after `a69e7fd30de84266029163248ef387855f5c3077`
verified `roster_id=2`, `Lulu’s Potatoe’s`, the v2 fallback story spine, and
the visible visual-direction receipt. This closes the stale-shell migration
gate exposed by the prior deployment check. Public smoke passed against the
same revision; the automated authenticated smoke remains intentionally
skipped because no session token is stored in the repo or shell.

The publication is still deterministic fallback (`0/5` current Luna articles)
until the protected operator run is authorized. That is a truthful degraded
state, not a deployment failure.

## 2026-08-25 - Authenticated smoke must validate publication depth

Revision, league, and roster checks alone can still leave a shallow or stale
reader payload. The authenticated smoke now requires all five publication
receipts, known writer modes, structured headline/thesis/change/action fields,
reporter identity, and—when deterministic fallback is published—the current
fallback schema, lede, and visual direction. This keeps the automated gate
aligned with the media product rather than proving only that a shell exists.

## 2026-08-25 - Reuse one two-sided Trade Desk packet at every entry point

The main Trade Desk and team dossier routes now call the same browser packet
renderer. A structured trade thesis is not deep enough if its offer side,
alternative counterparties, timing risks, do-not-chase conditions, and source
trace are only present in JSON or only on one page. The shared renderer keeps
both paths read-only and shows an explicit empty state when the evidence does
not support an alternate counterparty. This is a presentation contract over
the deterministic thesis fields, not a new recommendation engine.

## 2026-08-25 - Measure the newsroom by explicit signals, not attention

The learning summary now joins scoped article receipts to deliberate feedback
and recorded outcomes, then groups the result by reporter and writer mode. A
page view remains silent, an open call remains unresolved, and a confirmed
rate is shown only for confirmed versus missed calls. This makes the writer
lineup measurable without turning a small personal ledger into a false claim
of model or reporter accuracy.

## 2026-08-25 - Empty manager fits must be an explicit result

Manager dossiers now carry `trade_fit_status` and `trade_fit_summary` through
the deterministic artifact, writer context, and team entry page. “None
supported” is a useful evidence result; omitting the section invites the
reader or a writer to fill the gap with a manager label or invented target.
The UI also exposes the activity sample-size fields needed to judge whether a
tendency is well supported.

## 2026-08-25 - “What changed?” must distinguish pulse from delta

The Data Room now lists the latest recorded news, trade, and waiver events
alongside aggregate volume. It does not call the list a historical change
unless a prior receipt supports that claim. A current snapshot can show a
useful pulse without pretending that every retained row is new.

The learning panel similarly separates receipt coverage from manager signals:
current publication receipts establish which desks exist, while only the
scoped interaction ledger can establish usefulness or outcomes. A desk with
zero signals must remain visible as zero, not disappear or become successful
by implication.

## 2026-08-25 - Preserve a prior reader bundle for return-later deltas

The Data Room now records a deterministic `dataRoomDelta` while the previous
durable `app_bundle.json` is still available. It compares news, trade, and
waiver rows by their source event IDs and keeps per-table added, updated, and
removed counts separate from the current pulse. The receipt is visibly
`not_available` when the previous comparison scope is missing or incomplete;
the first snapshot is never presented as historical change. This establishes
the return-later evidence seam without claiming that a newly observed event
is important, intentional, or a recommendation outcome.

The deployed entry proof at `6e706ffff1643b8322b3a74fedcdafd9c531ed1f`
matched the public revision and the authenticated private edition. Chrome
rendered Lulu’s Potatoe’s, the verified prior-bundle heading, and the honest
zero-added-event result alongside the current pulse. This closes the first
return-later comparison seam; it does not close the broader Data Room or
protected Luna publication work.

## 2026-08-25 - Preserve readiness evidence when operator actions are blocked

The authenticated operator panel initially showed the cached writer receipt,
but pressing the LLM action without `FRONT_OFFICE_OPERATOR_TOKEN` replaced the
whole status object with only `state=blocked` and a token message. That made the
same screen appear to lose its provider and model configuration. The browser
now overlays blocked or client-side failure state onto the existing status,
preserving the live writer, publication, and reader-contract fields. No writer
call is attempted until the operator token is present.

The production proof at `1be8e7c7160454dd28d9255cd4edce75e7e6e7c1` matched
public revision smoke and the authenticated private edition. A blocked LLM
click preserved `openai`, `gpt-5.6-luna`, and the publication receipt. This
closes the readiness-display seam; it does not authorize or complete a Luna
generation run without the operator token.

## 2026-08-25 - Make team construction visible in the entity dossier

The team page already showed a roster list and manager behavior, but a reader
had to reconstruct roster shape from cards. It now presents exact current-
season position counts, market/projection coverage, future firsts, need lanes,
and roster-scoped action mix with a construction evidence drawer. The browser
joins by `roster_id` and `player_id`; missing values stay unavailable. The
semantic shell marker is part of the migration contract so the capability
cannot disappear behind a durable older shell.

## 2026-08-25 - Preserve the operating lessons in-repo

The compact product and development memory now lives in
`docs/front_office_operating_lessons.md`. The durable model is a private
personal context layer over a deterministic data room over bounded editorial
lenses. Depth must come from reusable evidence objects—season ledgers,
transaction timing, roster construction, counterparties, projections, and
outcomes—rather than from longer generic prose. A media surface must explain
what changed and open the underlying evidence; generated imagery is optional
atmosphere with its own receipt and never a source of facts.

The most important deployment lesson is also recorded there: a current source
revision does not prove that a preserved user-scoped bundle or article payload
has migrated. The authenticated reader must be checked at the entry path for
exact roster identity, durable payload schema, story/fallback state, revision,
and freshness. Until the current production bundle visibly exposes the new
fallback story-spine schema or a current Luna receipt, production remains an
open migration gate.

## 2026-08-25 - Adopt the Front Office realization epic

The project is now treated as a personal front-office publication backed by a
deep data room, not as a dashboard with optional AI prose. The durable plan is
in `docs/front_office_realization_epic.md`.

The first implementation gate is the truthful-publication seam: the current
browser bundle, article artifacts, evidence fingerprint, reporter identity,
generation mode, and operator status must agree. No content run should spend
LLM cost until unchanged inputs can be skipped and the reader-facing issue is
proven to consume the generated artifact.

The product will use structured content objects for articles, evidence, and
media. Generated imagery is an editorial asset with scope, prompt/model
metadata, content hash, responsive variants, alt text, and publication status;
it is never a source of fantasy facts. Text writers remain evidence-grounded
lenses, and the human manager remains the decision-maker.

The work is sequenced as vertical slices: truthful publication, canonical
evidence packets, daily read, identity continuity, manager dossiers, read-only
Trade Desk, question-led Data Room, controlled media assets, and a learning
loop. This sequencing is intentional: more writers, charts, or imagery cannot
repair a broken seam between data, generated content, and the publication.

## 2026-08-24 - Apply the anti-recursive development rubric

The supplied anti-recursive-development delta is now represented by the
repo-local audit in `docs/anti_recursive_dev_audit.md`. It adds six checks to
the normal workflow: loyal tests, unreachable capabilities, mislabeled cargo,
compensated violations, knife-edge gates, and claim freshness. The immediate
changes were league-forced identity discovery, freshness-margin reporting, and
dated correction of the historical Melkor label. The rubric is a review
practice; it is not permission to import another project's code or claims.

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

## 2026-08-25 — Publication receipts are the seam between data and media

Article files are not published merely because they exist on disk. A current
publication must carry its reporter, writer mode, model, evidence fingerprint,
content hash, and fallback reason; the private browser bundle must expose the
same article receipt and bundle revision. The reader may show deterministic
fallback content, but it must label it as fallback and never count it as an
LLM-written article.

The generation workflow reuses an unchanged article only when the scoped
evidence fingerprint, reporter, model, writer mode, output hash, and user/
league context all match. The browser facade consumes the actual article body
and structured manager/trade packets; it does not rebuild a second story from
unrelated rows and call that publication.

Generated imagery has a separate manifest with prompt/content hashes, scope,
alt text, provenance, and publication status. It is decorative and optional:
an image failure must never block the evidence-led text edition, and images
must not contain factual stats or claims.

The first controlled asset is the repository-scoped decorative masthead
`assets/media/front-office-masthead-v1.png`. It is copied into generated league
sites with a site-relative path and content hash; the browser applies it only
when the manifest marks it available or published. This is an atmosphere layer,
not evidence. The initial single-asset version did not satisfy the full
responsive-media workstream; the first responsive masthead slice is recorded
below.

## 2026-08-25 - Make evidence and article contracts explicit

The publication seam now carries explicit article ID, section, roster scope,
source receipt, generation metadata, reporter, model, evidence fingerprint,
content hash, fallback reason, and bundle revision fields. The writer tool also
returns a structured editorial object (headline, dek, lede, thesis, change,
counter-signal, action, risk, confidence, related entities, and optional art
direction) alongside markdown. Legacy deterministic fixtures may omit those
fields and receive honest defaults; production writer calls are still asked for
the full contract.

Evidence packets are normalized before they reach a writer. A packet labels
single-source and unattributed evidence explicitly, carries freshness and
source IDs, states the deterministic calculation boundary, and names what the
writer is not allowed to infer. This is the guardrail against burning model
tokens to turn loosely assembled rows into authoritative-sounding prose.

## 2026-08-25 - Learning signals must be explicit

The first feedback loop records only deliberate manager actions: useful, needs
work, evidence reviewed, saved, pursued, or outcome. Each row is scoped to the
authenticated user, league, exact Sleeper roster, article, and bundle revision.
Ordinary page views are not treated as approval, and feedback has no path to
Sleeper or manager messaging. This keeps future learning grounded in decisions
and outcomes rather than shallow engagement counts.

## 2026-08-25 - Remember the league, never the name

The authenticated user record now stores the last selected owned league. A
valid `league_id` query updates that preference, and a later home visit uses it
before the legacy first-league fallback. This improves return visits and
logout/login continuity without weakening the identity boundary: ownership is
checked first, and the current team is resolved by the linked Sleeper user and
exact `roster_id`. Mutable display names such as `Moose Caboose`, `Melkor Lord
of Light`, or `Lulu's Potatoes` must never be used as identity keys.

## 2026-08-25 - Make learning visible without inventing certainty

Explicit article feedback and outcomes are now summarized in the authenticated
Data Room. The ledger counts useful, needs-work, evidence-reviewed, saved,
pursued, open, confirmed, missed, and unclear states without counting ordinary
page views. A confirmation rate is withheld until there are resolved calls;
this is a manager-recorded feedback measure, not a model accuracy claim.

Publication history follows the same rule. Each changed artifact receipt is
stored append-only with its evidence fingerprint, content hash, reporter, mode,
and failure state. The reader can compare the current article with its prior
receipt, while a shell-only bundle revision is deliberately excluded from the
editorial change signal. Provider usage belongs in the receipt when returned;
we must not turn token counts into a dollar amount without a verified price
table.

An owned direct edition route is also a selection event. Visiting a bookmarked
`/league/{league_id}/` now updates the remembered league, so a manager does
not have to return through the home query-string link for the preference to
persist.

## 2026-08-25 - Verify the current label at the source boundary

An authenticated production browser check and a direct Sleeper read agree on
the identity boundary for `Joanie Loves Dynasty Football`: the signed-in
manager owns `roster_id=2`, while `Moose Caboose` is `roster_id=4`. Sleeper's
current trimmed team label is `Lulu’s Potatoe’s` (including that spelling), so
the application must render the current source label and not silently replace
it with a remembered or hand-edited name. If the desired Sleeper label is
`Lulu’s Potatoes`, it must first be changed and observed at Sleeper; the app
should then pick it up on refresh. This check also found that Railway was still
serving the older bundle without the local question-led Data Room marker, so a
signed-in page alone is not proof that the intended revision is live.

## 2026-08-25 - Fallback publication still needs a receipt

An evidence-led deterministic fallback is a valid degraded publication state,
not an absence of publication. The reader must still see the reporter, fallback
mode, source-quality/count context, and an explicit path into the Data Room.
Hiding the receipt whenever an article has no fingerprint made the fallback
look more complete than it was and severed the media-to-evidence path. The
entry-path test now requires the fallback receipt marker and the Data Room link,
and the live browser check must count receipts for all displayed sections even
when no Luna article artifacts exist.

## 2026-08-25 - Responsive media is a real contract

The initial masthead was only a single CSS background, which made the media
manifest more aspirational than operational on a phone. The first media slice
now keeps desktop and mobile artwork as separately hashed, site-relative
variants, selects them through a guarded `<picture>` path, loads the
above-the-fold masthead eagerly, and leaves a text-gradient fallback when the
asset is unavailable. The Data Room shows the asset status, variant count,
alt-text receipt, and prompt hash. Artwork remains decorative and cannot carry
fantasy facts.

## 2026-08-25 - Trade Desk fit is a shortlist, not an offer

The Trade Desk's `assets_we_can_offer` field was too shallow when it merely
listed our highest-market-value players. A useful packet must connect the
selected roster's exact assets to the target manager's observed valuation
lanes, while preserving the distinction between what the target owns and what
we might discuss.

The deterministic packet now emits `offer_candidates` with the asset's roster
and market context plus the matching `manager_valuation_profiles` label,
preference score, evidence count, confidence, and source trace. The browser
calls these “potential assets from our roster to discuss (not a generated
offer).” This is evidence of a historical lane, not proof of current intent,
a quote, or a predicted response. The system remains read-only and the human
manager makes the final decision.

## 2026-08-25 - Revision checks must include browser cache behavior

Railway can serve the expected source revision while an already-open browser
continues to display an older generated `index.html` from cache. A server-side
source-revision receipt is necessary but not sufficient for a truthful visual
verification. Private generated HTML and JSON bundle files now send
`Cache-Control: no-store, max-age=0` and `Pragma: no-cache`; the deployment
check must inspect the rendered entry path after a fresh load and confirm the
expected shell marker. This protects the user's personal edition from looking
stale after a successful deploy.

## 2026-08-25 - Make the cost gate visible before a writer run

The Clerk login is intentionally read-only; production writer and refresh
actions remain behind `FRONT_OFFICE_OPERATOR_TOKEN`, while `OPENAI_API_KEY`
only configures the model provider. The headquarters now explains that
separation before the user clicks Generate and translates a 403 into an
actionable message. A failed authorization must not be mistaken for a writer
failure or silently trigger a paid call.

## 2026-08-25 - Manager dossiers must open the two-sided decision packet

The manager page had strong historical intelligence but only a generic Trade
Angle, forcing the reader back to the Trade Desk to reconstruct the actual
conversation. It now renders the target assets, exact-roster offer candidates,
observed valuation-lane evidence, why-the-manager-might-care context, price
guardrails, and do-not-chase conditions in the dossier entry path. The
underlying packet remains read-only and uncertainty-labeled; the dossier is a
decision surface, not a second source of truth.

## 2026-08-25 - Player pages must expose an evidence chain

Player entity pages previously stopped at a one-line insight, score tiles, and
a transaction drawer. That made the player surface feel like a lookup page
even though the bundle contained market, projection, opportunity, role, news,
and history evidence. The page now opens a player dossier with the current
read, why it matters, the active decision lens, watchouts, an evidence chain,
source traces, confidence, and an explicit no-outcome guardrail. It remains a
view over canonical rows and validated insight cards; it does not create a
new player fact or imply a transaction.

The first live review also showed that exposing raw trace strings inline made
the page harder to read. The player dossier now shows compact source labels in
the evidence chain and keeps the complete trace in a collapsed drawer; it
also labels the player as yours, an opponent's, or unrostered.

The live verification initially showed the prior durable shell during deploy
propagation. A green health revision was not sufficient evidence; the browser
had to load the owned-league route, wait for the bundle, and assert the
manifest `sourceRevision` plus the visible player markers. The fresh signed-in
check then confirmed revision `c91108bc` and the new entry path.

The live smoke contract now encodes that lesson: authenticated checks fail if
the private bundle or manifest is bound to a different revision, league, or
missing verified roster receipt.

## 2026-08-25 - Writer failures must preserve their receipt

The authenticated production edition currently resolves the correct Sleeper
identity (`roster_id=2`, `Lulu’s Potatoe’s`) and serves the question-led Data
Room, but its last operator record is still `0/5 reporter articles ·
evidence-led fallback`. That is a valid degraded publication state, not proof
that the newsroom ran successfully.

The writer orchestration previously replaced the workflow's diagnostic message
with the generic phrase “League refreshed, writers run, and browser bundle
rebuilt.” This hid whether the run failed before an API call, during provider
generation, or during article validation. The orchestration now preserves the
workflow state, provider/model metadata, per-article results, and useful error
message. The Operator Mode panel renders those receipts and explicitly says
that failed or skipped sections remain deterministic fallback content. The
operator token remains a deliberate protected write boundary; no UI change may
turn a Clerk login or an API-key presence check into authorization to spend a
generation call.

The earlier `c91108bc` browser revision in this log is historical. The settled
production browser check for this diagnostic slice observed source revision
`831fca842aaf05be09dc9b748063fb644c68d3d0`, the same owned league, and the same
verified roster receipt. It still showed the expected degraded `0/5` state,
which is why the Luna publication gate remains open.

## 2026-08-25 - Homepage source receipts must use dataset identity

The live homepage briefly reported `0 news rows · 0/0 news sources current`
while the selected edition's Data Room and normalized issue carried 55 news
signals. The facade grouped sources by the literal display label `News desk`,
but production source receipts are named RotoWire player news and Sleeper
trending adds/drops. Source receipts now classify news from stable source and
dataset identity, and use the normalized league-impact count for the displayed
row total so overlapping provider rows cannot inflate the headline. This keeps
the media facade aligned with the data room instead of presenting a plausible
but false empty state.

## 2026-08-25 - Reporter attribution must be coherent in fallback content

The default newsroom lineup was already defined in `src/personas.py`, and LLM
articles resolved it by article key. Deterministic fallback markdown and the
publication facade still had a generic `front_office` seam, however: a fallback
receipt could identify `front_office` while displaying Topline Tony or another
named reporter. That made the multi-lens promise cosmetic and made receipts
harder to trust.

Fallback builders now resolve the reporter by article key, including their
front matter and voice markers. The reader facade treats a generic legacy
fallback ID as missing, then resolves the assigned newsroom persona; real LLM
receipts retain the known reporter that actually generated the artifact. Tests
assert both the markdown entry path and the publication receipt remain
`reporter_id`, `reporter_name`, and `reporter_persona` coherent.

## 2026-08-25 - Deterministic fallback receipts must be inspectable too

An evidence-led fallback is still a published product state. It cannot be
treated as a special case that skips the metadata needed to understand what
the reader is seeing. Deterministic fallback articles now carry a stable
`evidence_fingerprint`, reporter identity, explicit `fallback_reason`, a
structured article payload, and a source receipt alongside their markdown.

The receipt contract also distinguishes article-level `evidence_ids` from
`source_ids`. Evidence IDs identify the validated evidence objects an article
cites; source IDs identify the underlying source traces used to build the
context. A fallback with no persisted article-level citations must say so,
while still exposing its source traces and source tables. The UI labels those
fields separately so a source trace cannot be presented as if it were a cited
claim. This preserves the media-to-data path in both degraded and generated
modes and prevents a future writer change from quietly weakening the evidence
contract.

## 2026-08-25 - Source-only deploys must migrate durable receipts

Changing the source revision of a preserved browser shell is not enough when
the deploy also changes the shape of a durable article receipt. The first
receipt-parity deploy exposed that gap: the HTML shell reported the new SHA,
but the persisted markdown and embedded editorial payload still exposed the
old empty receipt fields. Shell rebuilds now perform an additive, idempotent
migration of deterministic fallback metadata from the preserved validated
rows and rebuild the editorial payload. They do not refresh Sleeper facts or
invoke an LLM. The regression test keeps this deployment path honest when
processed CSV intermediates are unavailable.

## 2026-08-25 - Fallback stories need canonical evidence IDs

Source traces tell the reader where the data came from, but they do not
identify the exact row supporting a claim. Deterministic fallback articles now
assign stable evidence IDs using the same `entity_type:entity_id:index`
convention as the canonical article evidence packets. The structured payload
reports those IDs and their count, while `source_ids` remains reserved for
source traces. This lets a fallback article and a future Luna article share the
same claim-to-evidence seam instead of making the degraded path permanently
second-class.

## 2026-08-25 - Receipt migration verified on the authenticated production path

The signed-in browser check after revision `536bc51` loaded the owned league
route, verified the identity receipt for `roster_id=2` and `Lulu’s Potatoe’s`,
and found five publication receipt drawers. Every deterministic fallback had
its assigned reporter, evidence fingerprint, fallback reason, structured
payload, and source receipt; the visible drawer separated the absence of
article-level evidence IDs from the underlying source IDs and linked back to
the Data Room. This is the required proof that a green health endpoint and a
new shell revision did not leave the reader on stale or uninspectable content.

## 2026-08-25 - Manager dossiers need a season ledger, not career totals

The first manager dossier surface exposed useful cycle labels and trade edges,
but its season history was effectively a list of aliases plus trade counts.
That was not enough to distinguish a recent tendency from a six-season career
total. The deterministic layer now emits `manager_season_history`, keyed by
historical `season` and exact `roster_id`, with trades, waiver claims, FAAB,
assets moved, trade partners, roster shape, evidence, and source trace. Quiet
seasons remain represented so missing activity is not mistaken for missing
history.

The browser consumes the same ledger in manager dossiers and renders it through
the existing team entry path. Source-only shell rebuilds derive the table from
preserved canonical tables when the new CSV is absent, and the migration is
type-normalized and idempotent. This is the pattern for future depth: add a
reusable deterministic evidence object first, then let dossiers, articles, and
the Data Room consume it without duplicating facts.

## 2026-08-25 - Manager timing must remain observed, not implied

Season totals alone still hide an important decision signal: whether a manager
acts steadily, only during waivers, or in a narrow late-season window. The
season ledger now records Sleeper transaction weeks separately for trades and
waivers, plus first, last, and peak observed activity week. Missing weeks stay
blank rather than being guessed from timestamps. The dossier renders those
fields as timing evidence, not as a claim about deadline intent.

## 2026-08-25 - Writer preflight must be visible before a paid run

The Data Room previously displayed provider and model values only when the
last operator record happened to contain them. A legacy or failed record could
therefore make a correctly configured Luna deployment look unconfigured, or
hide the missing API key until after a button press. The league-scoped operator
status now reports the safe writer preflight (`openai`, `gpt-5.6-luna`, reasoning
effort, key variable name, and configured boolean) without returning a secret.
The browser uses that preflight for the cost gate, while the publication
receipt remains the authority for whether articles were actually written.

## 2026-08-25 - Fallback articles need a story spine, not empty metadata

The deterministic publication previously had valid evidence IDs but blank
lede, thesis, and change fields. The reader therefore saw a raw report and a
receipt, but not a useful editorial frame while the protected Luna run was
pending. Fallback articles now carry a versioned, article-specific lede,
thesis, change boundary, counter-signal, action question, and non-factual
visual brief. These fields describe evidence scope and uncertainty; they do
not create events, motives, or outcomes. The migration upgrades older fallback
payloads once and preserves their evidence fingerprint.

## 2026-08-25 - Article media must be scoped and optional

The publication now carries four section-specific generated illustrations,
keyed to the daily brief, team report, market watch, and trade desk reporter
assignments. The media manifest records the article scope, reporter ID,
prompt/model metadata, content hash, dimensions, alt text, and publication
status. The reader only renders a valid site-relative asset and labels it as
decorative; the article, evidence receipt, and Data Room remain usable when an
image is missing or fails to load. This keeps generated artwork from becoming
a second fact channel or a deployment dependency.

## 2026-08-25 - Live media verification must include lazy loading

The first signed-in production check after `e830e05` found the four article
figures in the publication, but two lazy images had not loaded before they
entered the viewport. Individual viewport-entry checks then confirmed all four
assets loaded at 1536px, while the exact `roster_id=2` identity for Lulu’s
Potatoe’s and the article evidence receipt remained intact. Future browser
verification must distinguish DOM presence from a loaded media response.
Receipt presentation must also use the actual receipt schema: fallback
publication receipts expose their mode as `mode`, while durable database rows
use writer-mode fields. If the UI cannot read a mode, it must say that receipt
state is unavailable rather than implying the article is unlinked.

## 2026-08-25 - Compare current fits with historical valuation lanes

Manager dossiers now compare current counterparty edge rows with each
manager's recency-weighted historical valuation lanes and show the number of
seasons in scope. The browser distinguishes alignment, non-alignment, and no
current fit. This is a prioritization aid grounded in observed rows, not a
claim about manager intent or a predicted response.

## 2026-08-25 - Rebuild durable dossiers when their schema is stale

The first production browser check after the cross-season change exposed a
durable-bundle seam: the deployed shell and source revision were current, but
the preserved manager dossier objects lacked the new evaluation field. The
serving gate now checks the persisted payload schema, not only the revision and
fallback article receipts, and triggers the additive shell migration when the
field is absent. A current SHA is therefore no longer treated as proof that
the reader payload is current. The same guard now checks the generated HTML
shell for its current entry-path markers, because a current payload and SHA
can still be presented through a stale interface.

## 2026-08-25 - Do not let a stale private root mask a current bundle

Bundle selection previously preferred a complete private root before applying
the source and shell contract checks. That allowed an older user-scoped shell
to win over a current legacy migration bundle. Selection now prefers a bundle
only after identity and freshness/schema checks pass; stale roots remain
eligible only as recovery candidates for the migration path.

## 2026-08-25 - A healthy deploy is not proof of the authenticated reader

After `0c7b052` deployed, public smoke reported the expected revision, but a
clean signed-in manager route still embedded revision `99b39f6` and lacked the
current manager dossier markers for `trade_fit_evaluation` and “Cross-season
valuation lanes.” The code and local migration tests are not enough to call
this resolved: the route must prove which bundle root it selected, whether a
migration was attempted and succeeded, and which revision was finally served.

This reopens the production migration gate without discarding the prior
historical verification. The next implementation slice is a safe diagnostic
and fail-closed serving contract for that seam. It must not expose filesystem
paths, session tokens, or private payloads, and it must not trigger paid Luna
generation.

## 2026-08-25 - Recheck the reader after recovery, not just after rebuild

The league route now exposes a redacted reader-bundle receipt through the
authenticated operator status and readiness surfaces. It reports the selected
private or legacy root, expected and served revisions, identity match, shell
contract, fallback receipt contract, manager dossier contract, and bounded
failure reasons without returning filesystem paths or content. A rebuild that
leaves the bundle stale no longer returns its existing `index.html`; it shows
the recovery page with HTTP 503. This closes the silent-success code seam,
while the production gate remains open until a deployed signed-in route proves
the receipt and current reader together.

## 2026-08-25 - Reader migration verified after a fresh authenticated entry

Deployment `acd8c3ab3b1bf69581cd8fa95b8c7c9f45994683` passed public smoke. The
first signed-in browser navigation still showed the prior embedded `99b39f6`
manifest until a fresh reload; the reload and a repeat direct entry then
reported the current revision, `current · private` reader receipt, exact
`roster_id=2` / `Lulu’s Potatoe’s` identity, all five publication receipt keys,
and the rendered “Cross-season valuation lanes (6)” manager section. The
stale-reader gate is closed for this release, with browser freshness retained
as an explicit verification precondition. The protected Luna run remains
pending operator authorization.

## 2026-08-25 - Preserve player identity in historical evidence

The player-history re-audit found a depth defect behind the presentation: the
ledger contained readable names but discarded the Sleeper IDs that should join
events to player dossiers, and trades were represented only from the receiving
side. Normalized trade/waiver rows now carry source player ID lists; the
deterministic history builder emits both `acquired` and `sold` events and
records whether identity came from a source ID or a labeled name fallback.

This is a product rule, not a cosmetic field addition. A historical dossier is
only as deep as the evidence objects it can reliably join. Current local
refresh evidence is 3,101 rows, all `source_id`, with balanced trade direction
(505 acquired and 505 sold). Future unresolved matches must remain visible and
must not be silently promoted by display-name equality.

## 2026-08-25 - Put semantic data quality in the reader

The local player-history validator exposed an important receipt that the
browser did not show. That made the Data Room capable of presenting a fresh
but semantically weak history table without warning the manager. Fresh and
shell-only browser builds now carry `dataQuality.player_history_identity`, and
the Data Room renders its coverage, identity methods, trade-direction balance,
and bounded contract warnings. The receipt is derived from the displayed rows;
it is not a second manually maintained status. A `partial` or `contract_error`
state remains visible so presentation cannot overstate historical depth.

## 2026-08-25 - Make saved strategy affect the My Team read

The My Team page had a strategy panel that repeated profile metadata while
explicitly saying value tags were planned. That was a shallow presentation
seam: the deterministic pipeline already produced `team_needs_matrix`,
`team_fit_scores`, and `action_recommendations`, but the reader did not join
them to the active roster. The browser now uses exact `roster_id` and
`player_id` joins to show team shape, need lanes, fit coverage, action mix,
and the top aligned roster evidence; the roster table exposes the same fit,
action, timeline, and liquidity fields.

No new score or LLM call was added. This slice makes existing deterministic
evidence legible and fails closed to `not_scored` when a player fit row is
missing. The old planned-overlay copy is covered by a browser entry-path
contract test.

## 2026-08-25 - Keep recommendation learning separate from article learning

The first learning loop tracked article usefulness and article outcomes, but
target, sell, and trade theses had no explicit way to be evaluated. The
browser now renders an outcome control on those decision cards and writes a
private `recommendation` interaction keyed to the thesis and bundle revision.
The API accepts only `open`, `confirmed`, `missed`, or `unclear` and rejects a
recommendation outcome sent through the article lane.

The summary reports recommendation counts and confirmation rate separately
from reporter/article outcomes. This keeps a useful article from looking like
a correct decision and prevents a page view or generated sentence from being
treated as evidence that a recommendation succeeded.

## 2026-08-25 - Semantic reader contracts must advance with new entry paths

The recommendation-learning deployment showed that a durable bundle can carry
the current data and dossier contracts while still serving an older HTML/JS
shell. The authenticated route therefore requires explicit markers for the
recommendation outcome control and recommendation learning summary in addition
to `sourceRevision`, data-quality, and publication receipts. Missing markers
trigger shell migration from preserved facts; if recovery cannot produce a
current bundle, the route returns the recovery state rather than silently
serving the old interface. This is the reusable rule for every future
user-facing capability.

## 2026-08-25 - Recommendation-learning migration accepted in production

Commit `375bed1368b9f2706af44138bbe6e23ee79663b8` passed public revision
smoke and an authenticated exact-route browser check. The reader was
`current · private`, showed Lulu’s Potatoe’s for verified `roster_id=2`, and
rendered 25 scoped recommendation outcome controls with the four validated
states. Data Room showed the recommendation learning lane and the 3,101-row
historical identity receipt. The earlier stale-shell observation is retained
as the reason for the contract, not as the current production state.

## 2026-08-25 - Surface manager event grain in the dossier

The manager dossier had season history, repeated behavior, and trade-fit
summaries, but the actual `manager_event_log` was only available through a
separate table view. That was a disconnected-depth defect: a reader could see
that a manager made 46 trades without seeing the observed event that supported
the next conversation. Dossiers now carry a bounded `transaction_timeline`
with exact roster scope, event identity, timing, counterparty, asset movement,
and source evidence. The UI labels it as observed history and keeps motive and
future response unknown. The slice is deterministic and does not spend a Luna
call. Revision `e99e0e6caf0854eae85b99b5e614711a2cdda343` was then verified in
the authenticated production reader: Moose Caboose rendered 24 event rows,
while the private edition still identified Lulu’s Potatoe’s as the active
roster.

## 2026-08-25 - Reuse recommendation learning from manager dossiers

A manager dossier could expose a supported trade fit without letting the
manager record whether that hypothesis held up. The direct fit cards now use
the existing recommendation outcome lane with a stable
`manager-fit:<roster_id>:<player_id>` key and retain the fit's evidence, risk,
and confidence in the interaction payload. This keeps main Trade Desk and
manager-entry learning comparable and does not imply that a trade happened.
The authenticated production reader then exposed six `manager_fit` controls
on Moose Caboose's dossier at revision
`9fb20f8778fffb396e966af640fb11f6efc92824`; the check inspected the keys and
evidence without writing an outcome.

## 2026-08-25 - Attach cross-season fit evidence to each candidate

The manager dossier previously summarized valuation-lane overlap at the
manager level. That was too coarse: one aligned position group could make an
unrelated candidate look supported. Each current fit now carries its own
aligned or `no_direct_lane` comparison, lane evidence, sample count,
confidence, and source trace. This improves the decision packet without
turning historical preference into intent.

The authenticated production reader at revision
`2c8d2a6de187a8db50b8c472d2c6df93d4eb12bd` showed the candidate-level result
for Moose Caboose: three aligned fits and three `no_direct_lane` fits, with
the manager-fit keys and evidence intact.

## 2026-08-25 - Record team construction in the entity dossier

The team page now makes deterministic roster construction legible before the
reader reaches the long player list. It is scoped by the selected current
season and exact `roster_id`, aggregates position mix, market/projection
coverage, need lanes, future firsts, and action mix, and exposes its source
tables in an evidence drawer. It does not infer a lineup or let neighboring
rosters fill missing joins.

Production revision
`db6c71e34eb18c7069f7cd35361c83be65d39f48` was smoke-verified and then
authenticated in Chrome. Moose Caboose rendered the exact-scope panel with
30 players and the expected position, market, projection, action, and
evidence values while the private edition remained Lulu’s Potatoe’s.

## 2026-08-25 - Reconcile team market totals to the asset ledger

The Team construction panel initially summed `player_dossiers.market_value`,
which omitted four current-roster internal proxy values and showed 720.54
while the manager dossier's canonical `team_asset_inventory` total was
835.54. The panel now uses exact current-season player inventory rows for its
market total and reports proxy-row coverage separately. Projection coverage
continues to come from `player_dossiers`; missing inventory joins remain
unavailable. A market number is not trustworthy merely because it is
available, so the UI must expose whether it is externally sourced or proxy
valued.

Production revision
`eb9b68d96f40cffa0afec6131547be178d8f1395` was smoke-verified and checked
in authenticated Chrome. The two dossier surfaces now agree at 835.54; the
team construction receipt reports 30/30 market rows and four internal proxy
values, with the canonical inventory source visible.

## 2026-08-25 - Reuse market provenance on player dossiers

Jimmy Horn's live player entity page showed market value 0 while the exact
Moose Caboose asset ledger held an internal proxy value of 43. This was the
same parallel-join defect as the team total, but at player grain. Rostered
players now resolve market value through `team_asset_inventory` using exact
`roster_id` and `asset_id`, expose the proxy/external descriptor, and fail to
an unavailable value if the scoped asset row is absent. Profile market values
remain valid only for unrostered players.

Production revision
`b0142965abe1ba10986b40ed289eea21fa3b37e9` was smoke-verified and checked
in authenticated Chrome. Jimmy Horn's page now reports market 43 with the
internal proxy descriptor and trace instead of the prior profile-derived 0.

## 2026-08-25 - Propagate proxy market values through deterministic analysis

The asset ledger had 41 internal proxy values, but downstream profile and
signal tables still stored zero because their market join stopped at external
consensus. That made the data room internally inconsistent and left the
decision layer blind to economic context. The pipeline now fills missing
external values from exact player assets, preserves
`internal_proxy_player_value` in `source_trace`, and caps proxy confidence
with explicit risk language. Local regeneration verified zero mismatches
across inventory, dossiers, signals, and actions. A production league refresh
is required to rebuild the durable private bundle before this slice is called
live.

Production acceptance amendment: revision
`5654d74073656cb3ae225def1572ef74b450d67f` passed public smoke and an
authenticated scoped refresh. The private home retained Lulu’s Potatoe’s,
the team route reconciled 30/30 market rows at 835.54, and Jimmy Horn's
player route showed market 43 with the internal proxy descriptor and trace.
The source is now connected through the decision layer in production; the
proxy remains explicitly lower-confidence when projection evidence is absent.

## 2026-08-25 - Make the writer gate observable before spending tokens

The writer action is intentionally protected and cost-incurring. A missing or
incorrect operator token must fail closed before the request reaches Luna, but
the prior home surface made the distinction between the provider key and the
operator key too easy to miss. The Writer Desk now shows provider, model,
reasoning effort, API-key readiness, and operator-gate readiness without
exposing secret values. This preserves the separate Clerk/read-only and
operator/write boundaries while making the next publication attempt operable.

Production acceptance amendment: revision
`f3ea7ce977ae1cd9e42523522ce9a3374f10646e` passed public smoke and an
authenticated headquarters reload. The rendered receipt showed OpenAI
`gpt-5.6-luna`, medium reasoning, API key ready, and the operator gate
configured. The article count correctly remained 0/5 because no operator key
was supplied; this is a no-call state, not a failed provider run.

## 2026-08-25 - Reconcile prior writer models before a paid rerun

The first API run can be valid historical output while still being wrong for
the current configured model. A configured-model badge alone does not answer
whether the durable article receipts were produced by that model. The scoped
content receipt now reports the last generated model, the configured model, and
the number of persisted generated articles whose model differs. That state is
diagnostic only: it does not publish old content as current and does not spend
tokens automatically. The protected Luna run remains the authority for current
publication.

Production proof at code revision
`92ae655ede886f601001101dd4c4850d332c1223` passed public smoke and
authenticated Chrome verification. The live headquarters showed the exact
Lulu’s Potatoe’s identity and reported the prior persisted run as
`gpt-5.6-luna` aligned with the configured model. It still showed 0/5 current
articles because the separate operator authorization was not supplied; the
receipt is not being used to claim a fresh publication.

## 2026-08-25 - Add observed matchup outcomes to manager dossiers

The manager dossier's historical ledger now consumes an optional canonical
`matchups` table from Sleeper. The table is one row per exact roster/week and
retains the opponent roster ID, score state, margin, result, evidence, and
endpoint trace. `manager_season_history` aggregates those rows into wins,
losses, ties, points for/against, point differential, win rate, and an
explicit outcome coverage state.

The implementation deliberately distinguishes missing/offseason/unplayed
data from a recorded losing season. The browser therefore renders `n/a` for
matchup count when no matchup evidence exists and exposes the outcome receipt
next to the manager dossier. This is a foundation slice for future manager
prediction and feedback work, not a claim that observed outcomes reveal
manager intent or that the current production bundle has been refreshed yet.

### Production acceptance amendment — `201c3f7`

Railway now serves the full pushed revision
`201c3f7d2d6319dae7bdfc246ebb1f12f9aa3fed`. Public smoke returned 200 for
health and login. Authenticated Chrome verified the selected private team as
Lulu's Potatoe's / `roster_id=2` and the manager dossier outcome receipt as
`45-37-18`, 108 matchup rows, and
`manager_season_history;matchups`. The protected writer was not run.
## 2026-08-25 market scale and availability audit

Two reader-trust failures were traced to deterministic seams rather than the
LLM. DynastyProcess `value_2qb` is x100; the old `>100` conditional divide
turned a raw 93 into a market value of 93.0. All values from that source now
normalize as `raw / 100`, and the source trace names the conversion. Separately,
Sleeper injury fields were present in the player cache but discarded during
normalization, allowing baseline PPG copy to sound like a current forecast.

Player/roster rows and dossiers now preserve injury status/body part, user-facing
copy says `baseline PPG`, and signals carry availability in their evidence and
risk. The market score remains a decomposable deterministic read; it is not a
single authoritative truth and must show source scale, source count, and
disagreement where applicable. Regenerate the processed bundle before judging
the production surface, because old CSVs can preserve the pre-fix Nailor value.

## 2026-08-26 - Canonical market scale and role uncertainty

The market audit found that canonical high-end values were still being divided
by 100 inside signal scoring. The source ingestion boundary now owns all
`value_2qb/100` conversion; signal code consumes `102.32` as `102.32` and
regression tests prove it. A separate age-plus-low-market heuristic now marks
baseline gaps as `role_uncertain_watch` and routes them to a role check rather
than a breakout claim. This is intentionally conservative: the model may still
surface a research lead, but it must not confuse recent per-game production
with a reliable current starter role.

## 2026-08-26 - Front-page composition is a contract

The newspaper facade now receives four structured front-page panels from the
same issue builder: selected-team pulse, roster-linked news context,
projection/market disagreement, and manager dossier previews. Panels carry
entity anchors, source traces, uncertainty, and routes into the existing data
room. The UI is therefore a publication layer over evidence rather than a
second disconnected dashboard; generated Luna articles can add voice without
owning factual joins.

## 2026-08-26 - Manager trajectory stays descriptive

Aggregate manager labels were not enough to explain whether a manager was
actually changing behavior. Dossiers now compare the latest two observed
seasons with the prior observed window for activity and recorded outcomes.
The trajectory includes both season windows, deltas, source trace, and an
insufficient-history state. It is a reading aid for timing and transitions,
not evidence of motive or a forecast, and it is surfaced in the same dossier
entry path consumed by the manager writer.

## 2026-08-26 - Topline Tony needs the league week, not just player values

The first newsroom context audit found that the article assigned to Topline
Tony was fed mostly selected-roster valuation rows. That could produce a
polished team report without the news, matchup, or move context promised by
the product. The existing article seam now adds bounded current-season
`news`, `matchup`, and `transaction` evidence rows, filtered to the selected
league and exact roster where applicable. The writer may connect those rows
to stakes and timing, but the deterministic layer still owns facts and the
prompt explicitly prohibits converting context into intent or a forecast.

## 2026-08-26 - News identity must survive CSV numeric coercion

League news impact is private league context, not a global player-news feed.
Because pandas can read long numeric IDs as scientific-notation floats when a
CSV column also contains blanks, browser issue filters must compare canonical
IDs numerically as well as textually. The generated impact table now carries
`league_id` and `season`, ownership is keyed by `(league_id, player_id)`, and
the editorial seam has a regression test proving that the selected league's
news remains visible without admitting another league's repeated `roster_id`.

## 2026-08-26 - Historical manager depth follows owner identity

Roster IDs are local to a league and can change when the historical league
chain changes. The manager profile summary already retained stable Sleeper
`owner_id` and `roster_ids_by_season`, but dossier construction was still
selecting season history and event rows by the current roster number alone.
Dossiers now prefer owner-linked history and use the recorded season/roster
lineage only for legacy event rows. Current roster construction, needs, and
trade-fit assets remain exact-current-roster joins; historical depth no longer
silently drops a manager's earlier identity or admits an unrelated roster.

## 2026-08-26 - Event feeds must carry the identity seam

The manager dossier now follows stable owner lineage, but the raw event table
also needs its own seam. `manager_event_log` carries `league_id` and
`owner_id`, and the Manager Room filters by current season, exact league, and
exact roster. A roster number alone is never sufficient when historical league
data is present.

## 2026-08-26 - Desk templates are presentation contracts, not new facts

The five publication desks now carry stable template IDs and semantic content
blocks in the editorial issue. The template controls layout and navigation;
the markdown body, evidence receipt, and deterministic facts remain the source
of the story. This preserves one content path for fallback and Luna-written
articles while allowing the front page to read like a publication.

## 2026-08-26 - Entity news views must reuse the league boundary

The processed news table deliberately repeats one global Sleeper event for each
historical league that owns the player. The player page and News Desk therefore
cannot filter news by `player_id` alone. The browser now scopes news by the
selected `manifest.leagueId` and current season, comparing long IDs safely when
CSV serialization presents them as floats. This keeps the data room's shared
event history available while preventing a current player dossier from showing
six historical copies of one signal or another league's private impact row.

## 2026-08-26 - Mobile publication surfaces need reading density

The browser is a personal newspaper, not a CSV export. On narrow screens the
navigation is a horizontal desk rail, the duplicate shell header is reduced,
and long deterministic article lists show concise call text with evidence and
overflow behind explicit drawers. Full source context remains available; the
default reading path should preserve the story before the ledger.
## 2026-08-26 - News and price need an explicit deterministic seam

`league_news_impact` repeats global events for every identified league owner.
The signal layer now scopes those rows by the authenticated league and current
season before joining by player ID. It also emits `news_market_edges` only when
directional current news is paired with a meaningful market-gap or sell score.
This keeps the writer's job explanatory and preserves the fallback projection
gap when no news-backed edge is supported.

## 2026-08-26 - Market disagreement must be calibrated and qualified

The next market audit found that raw projected PPG and canonical market value
were not comparable units. Signal scoring now compares position-relative
percentiles instead of subtracting those raw values. Missing and internal-proxy
markets are explicitly uncalibrated; a single-source external market lowers
confidence and remains visible in risk/evidence. This makes a dislocation a
bounded research lead rather than a manufactured ranking claim. The regression
fixture includes a peer market cohort so a buy-low label cannot be earned from
one isolated player.

The same refresh also reconciles the writer-state record: the current local
bundle is deterministic-template fallback (`model_mode=deterministic_template`)
because the protected operator gate was not enabled. The historical Luna-run
checkpoint remains a record of an earlier local run; it is not evidence that
this refresh or current production contains newly generated Luna articles.

## 2026-08-25 - Activity coverage and scored outcomes must not be conflated

Manager history can contain scheduled matchup rows that have no scored result,
especially in the current partial season. Trajectory comparisons therefore
retain those seasons for activity timing but exclude them from outcome trends.
The dossier exposes `scored_matchups` separately from raw scheduled matchup
rows, and the browser labels the tile accordingly. A profile may say “limited
coverage”; it must not say “stronger results” when the latest outcome window is
only partially observed.
# 2026-08-25 - Player value must be horizon-specific

`projected_ppg` remains a season baseline and the weekly projection remains an
opponent-neutral allocation until a schedule/bye source is available. The new
`player_horizon_market_scores` table keeps next-game, rest-of-season, and
dynasty market lenses separate, carries current availability into the next-game
expected-points lane, and exposes contender fit, rebuilder fit, and their
spread. Dynasty is an external-market-plus-timeline lens (or a labeled internal
proxy when market evidence is missing), not a career-points forecast.

Writers may explain why a player is more useful to a contender than a rebuilder
or the reverse, but they may not collapse those scores into a universal player
grade. Missing projections remain unavailable rather than becoming zero
forecasts, and injury flags remain visible beside any baseline number.

## 2026-08-26 - Schedule evidence earns a narrower next-game claim

The horizon layer now preserves nflverse `games.csv` as `nfl_schedule` and
derives `nfl_team_defense_factors` from historical position-level fantasy
points allowed. When both joins are available, the next-game row names the
opponent, home/away state, bye status, and a clamped historical matchup factor.
Rest-of-season value counts scheduled games and explicit bye weeks. When the
schedule or team join is missing, the row remains opponent-neutral and says so;
the code does not manufacture a matchup projection from a name or a partial
schedule.

The row also now carries a separate five-year career-window production score.
It uses projected PPG, projected games, position-specific peak/decline
assumptions, and age. It is labeled as an internal scenario and is allowed to
inform rebuilder fit, but it does not replace dynasty market value or pretend
to know a player's lifetime total.

## 2026-08-26 - Matchup factors need a holdout receipt

The historical position-level defensive factor is useful context, but an
all-history factor can look more authoritative than it has earned. The factor
table now evaluates each team/position adjustment on later seasons than the
seasons used to construct it and carries validation seasons, sample size,
factor MAE, baseline MAE, MAE delta, direction accuracy, and a status. Horizon
rows and writer packets carry that receipt forward. Limited or non-improving
holdout evidence remains visible as a risk; it does not silently disable the
factor or turn a small sample into predictive certainty.

## 2026-08-26 - Make horizon markets directly comparable

The three-clock contract now has a browser entry path in the Trade Desk. The
Three-Clock Market Board filters exact active-team or current-league rows,
surfaces rebuilder/contender lanes, and links each row to the player dossier and
its evidence receipt. This is a presentation layer over
`player_horizon_market_scores`, not a second calculation path; its acceptance
test must cover scope, lane filtering, sorting, and the evidence drawer.

## 2026-08-26 - Version horizon assumptions with the market rows

`player_horizon_market_scores` now carries `horizon_model_version` and an
explicit `fit_basis`. Scores are not durable market facts unless the reader can
tell which deterministic weighting produced them. The version and weighting
receipt travel through the article packet and browser evidence drawer; a later
formula change must update the version rather than silently rewriting history.

## 2026-08-26 - Keep current availability separate from the season baseline

The next-game lane may reduce expected points for a current availability flag,
but the rest-of-season lane remains a production baseline when no recovery
timeline is available. It must say that it is not recovery-adjusted in the
deterministic receipt, writer evidence, and player surface. This prevents a
questionable or injured player from being presented as though the model had
projected a full-season absence or recovery.

## 2026-08-26 - Horizon scores need a scale receipt

The three-clock values are analytical position-relative percentiles from 0 to
100. They are useful for comparing a player's immediate, seasonal, dynasty,
and career-window standing against peers at the same position, and for deriving
the contender/rebuilder fit spread. They are not dollar market values and must
not be used as a cross-position price ranking. Market value and
market-percentile fields remain the price-comparison seam. The score basis now
travels with the horizon row, writer packet, and browser evidence receipt.

## 2026-08-26 - A counterparty edge needs two timelines

The `counterparty_trade_edges` table now carries a second deterministic join
to `player_horizon_market_scores`. The target roster's contender/rebuilder
lens is compared with the active roster's lens, but that result is labeled
timeline fit and never blended into `trade_edge_score` or treated as a price
quote. This is the useful distinction for a dynasty manager: the same market
asset can be more useful to the other team without being intrinsically worth
more. The edge, thesis, manager dossier, writer packet, and browser card all
carry the model version and basis; missing enrichment fails closed.

## 2026-08-26 - Do not let a useful new market become a sixth universal rank

The separate weekly, rest-of-season, dynasty, and career-window scores deserve
a visible article because they answer different manager questions. We added
`horizon_watch` with Market Clock Morgan as a synthesis desk rather than
blending the clocks into a new browser score. Its evidence packet is sampled
within position, and its copy sends cross-position price questions to the
canonical market value. This preserves the useful contender/rebuilder spread
without recreating the old failure mode where a surface score made an asset
from one position appear to outrank a star from another.

## 2026-08-26 - Do not hide the career clock inside dynasty copy

The deterministic horizon model already carried a separate five-year
career-window percentile, but the player page only exposed it as a sentence
inside the Dynasty card. That forced the reader to infer a fourth analytical
number from prose. The player dossier now renders a dedicated Career window
card with projected points, years, blended PPG, status, and the internal
age-curve basis. The distinction remains explicit: Dynasty is the market/
timeline lens, while the career window is a bounded scenario and neither is a
cross-position trade price.
### 2026-08-26: Preserve clock-to-clock market transitions

The horizon layer now records three explicit later-minus-earlier score deltas:
`rest_of_season_minus_next_game_delta`,
`dynasty_minus_rest_of_season_delta`, and `career_minus_dynasty_delta`.
These are position-relative percentile transitions, not extra market scores and
not trade prices. They let a writer explain why an asset is a short-term
contender premium, a patient-rebuild premium, or stable across windows without
recomputing or guessing from prose. A missing component leaves its delta
unavailable; zero is never used as a substitute for missing evidence.

The `horizon_watch` packet, front page, Three-Clock Market Board, and player
dossier now carry the same transition receipt. The contender/rebuilder fit
spread remains a separate weighted decision lens, so these transition deltas do
not collapse the three clocks into one universal grade.

The same rows now include `fit_coverage` and explicitly list unavailable clock
components in `fit_basis`. A partial fit is still a useful lead when a clock is
missing, but its available weights are renormalized and the missing evidence is
visible at the point of decision.

### 2026-08-26: Anchor the career clock to observed production when identity permits

An age-only five-year scenario is too shallow for a dynasty decision surface.
The horizon model now blends the current projection with recency-weighted
nflverse weekly PPG when a unique normalized-name plus position join resolves
to one source player ID. The receipt exposes the matched source player ID,
join method, history depth, latest season, and historical PPG. Ambiguous or missing joins remain visible
and fall back to the age-only scenario; they never silently become canonical
Sleeper identity or invented career evidence. The model version advances to
`horizon_market_v2` so this formula change cannot masquerade as a data refresh.

## 2026-08-26 - Make the full clock comparison visible where decisions happen

The Trade Desk market board now renders the four canonical horizon scores as
separate cards: next game, rest of season, dynasty market, and five-year
career window. Strategy fit scores remain in a separate row, and the three
later-minus-earlier clock transitions are shown as deltas. This is a
presentation completion of the deterministic horizon table, not a new browser
calculation or a blended universal rank. The board continues to group rows by
position and points readers to canonical `market_value` for cross-position
price comparisons.

## 2026-08-26 - Separate observed transaction lanes from revealed preference claims

The original manager valuation table was useful for broad activity posture but
too shallow for the intended manager dossier: current roster counts and all-time
activity multipliers do not show what a manager actually acquired versus sold by
position. The new `manager_transaction_preferences` table preserves
identity-resolved player movement across stable owner lineage, separates trade,
waiver, and draft acquisitions from disposals, and attaches current horizon
context when the historical player ID is present in the current market table.

The table and dossier call these `observed transaction lanes`. They do not call
them current preferences, historical prices, motives, or predicted responses.
Unresolved identities remain in `UNKNOWN`, and sparse lanes remain explicitly
low-confidence. This keeps the new market clocks useful for counterparty
questions while preserving the rule that deterministic evidence owns facts and
the human manager owns the decision.

## 2026-08-26 - Add a two-sided counterparty audience layer

The original counterparty edge table answers a seller-side question: which
assets held by another team look interesting or overpriced relative to our
model? That left the front office unable to answer the complementary question:
which of our own assets have a plausible audience in this league?

`counterparty_asset_interest` now joins an active player asset to another
manager's exact position lane, current team need, and available horizon fit.
The deterministic `conversation_fit_score` is a ranked research aid and its
receipt preserves the components and limitations. It must never be rendered as
a market value, buyer probability, willingness estimate, or generated offer.
The Trade Desk, trade thesis, manager dossier, and writer packet carry the
same rows. No row is emitted without an identity-resolved historical lane, and
missing or sparse evidence is shown as unavailable/low-confidence rather than
filled with a generic manager label.

## 2026-08-26 - Keep available-market clocks in the refresh cohort

Available-market candidates are not scored as an isolated market subset. When
the refresh has projection tables, the deterministic horizon builder scores
candidate rows inside that refresh cohort and then returns only canonical
players proven absent from the selected league. Market percentile peers come
from the complete position-specific market table. The Draft Room may show the
result as a research lead, but it must keep the availability and waiver-
eligibility limitation visible.

## 2026-08-26 - Put available market clocks on the publication path

The deterministic available-market table was already useful in the Draft Room,
but the publication layer did not consume it. Market Watch now carries a small,
position-aware available-market research packet for Waiver Wire Waverly, and the
front page reserves a preview card for that lane. The packet preserves all
separate clock scores, transition deltas, fit coverage, identity status, market
price anchor, and the explicit non-waiver-eligibility limitation. Market Clock
Morgan remains the dedicated full-league clock desk. This keeps the data model
single-source while giving each editorial lens a distinct job: one article
explains the whole market clock and one looks for available names worth
investigating.

## 2026-08-26 - Make available-market player cards real entity entry points

The available-market card and horizon board link by canonical Sleeper player
ID. A player with no current roster dossier must still open a useful evidence
page, or the publication is only decorative. The browser now joins an
identity-resolved `available_player_horizon_scores` row with the canonical
player metadata and renders the same four clocks, fit coverage, source trace,
and explicit availability boundary. The page labels roster absence as
research inferred from the selected snapshot; it does not create ownership,
waiver eligibility, or a claim receipt. An adversarial browser-bundle test
guards this entry path.
## 2026-08-26 - Make horizon comparison visual and mechanically auditable

The player market board now renders the four clock scores as comparable
position-relative percentile meters, with an unavailable state instead of a
zero-width claim. The text receipt remains beside the visual so a reader can
move from the shape of the value curve to the schedule, injury, model, and
source evidence behind it. The homepage desk shelf also exposes the sixth
`horizon_watch` entry point; a registered reporter that cannot be opened is not
a usable publication surface.

The local trust gate now validates the horizon seam: every populated clock and
fit score must remain on the 0-100 scale, `fit_coverage` must reconcile to the
four clock fields, and each transition delta must equal its later score minus
its earlier score. This validates arithmetic and presentation integrity; it
does not imply that a percentile is a calibrated forecast or a cross-position
price.
## 2026-08-26 - Preserve horizon beliefs for outcome feedback

Current horizon percentiles are useful comparisons, but a current-state CSV
cannot answer whether the next-game or rest-of-season lens was useful after
the games happen. The refresh now writes an idempotent, append-only
`horizon_snapshot_history.csv` and derives `horizon_score_accuracy.csv` from
later `player_usage_weekly` rows. The evaluator joins Sleeper-named snapshots
to nflverse by normalized name plus position and withholds ambiguous joins.
It reports descriptive rank correlation and top-quartile lift only; it does
not turn a percentile into a probability, grade a missing game as zero, or
pretend that one season's PPR output calibrates dynasty/career value or
contender/rebuilder fit. Those require appropriate longitudinal labels.

## 2026-08-26 - Make horizon-to-price disagreement explicit

Each horizon row now carries four same-position clock-minus-market-percentile
deltas: next game, rest of season, dynasty, and career window versus the
canonical `market_percentile`. These are repricing leads for the newsroom,
not dollar values, universal ranks, or proof of mispricing. They remain
separate from the cross-position `market_value` anchor and are withheld when
either endpoint is unavailable. The Trade Desk, Market Clock Morgan packet,
fallback publication, and front-page market read expose the deltas from the
same canonical row so writers do not invent the comparison in prose.

## 2026-08-26 - Repricing leads need a reader path

The four clock-versus-market deltas now have a dedicated fallback section and
Trade Desk controls for disagreement, lead, and lag. The selection stays inside
position because every endpoint is a position-relative percentile. This is a
research queue for deciding which window deserves attention; it is not a new
price, blended grade, or assertion that the market is wrong.

## 2026-08-26 - Carry repricing context into trade conversations

The counterparty seam now carries the canonical four-window scores, their
clock-minus-market deltas, and the largest same-position disagreement window
into both `counterparty_trade_edges` and `counterparty_asset_interest`. This
does not change `trade_edge_score` or `conversation_fit_score`; it gives the
Trade Desk a reason for investigating a conversation now and makes the
contender/rebuilder timeline question visible beside the manager and asset
evidence. Missing horizon joins remain blank and explicit. A positive delta
means the selected clock is ahead of the market percentile; a negative delta
means the market is ahead of that clock. Neither is a dollar gap, a universal
rank, a manager-intent claim, or an offer recommendation.

## 2026-08-26 - Treat horizon scores as a newsroom instrument

The next-game, rest-of-season, dynasty-market, and bounded career-window
scores are deterministic analysis on top of hard data. They are intentionally
separate because a player can be useful to a contender now and valuable to a
rebuilder later. The difference between the windows, plus the contender and
rebuilder fit scores, is the research surface for finding those disagreements.

Articles and reporter personas sit above this evidence layer. A desk may own a
decision window or a manager question, but it must consume the canonical
horizon packet, preserve its source and coverage receipts, and explain the
reasoning in its own voice. Four scores do not require four duplicate paid
articles: a new generation is warranted only when the audience, decision, or
evidence selection changes. This preserves cost control while allowing the
Front Office to become a differentiated media product.

## 2026-08-26 - Current availability is not historical evidence

Sleeper's player cache is current-state metadata. The normalizer now populates
`roster_players.injury_status` and `injury_body_part` only for the configured
current season. Historical roster rows leave those fields blank because a
current injury flag cannot establish what was known or true in an earlier
season. The refresh path passes the current-season boundary explicitly, and an
adversarial normalization test protects both the current and historical cases.

The provenance receipt is also carried into `player_dossiers` and
`player_horizon_market_scores`, and is rendered on player and horizon surfaces.
The receipt is a scope label, not an injury forecast or a recovery adjustment.

## 2026-08-26 - Sleeper free-agent state is a current availability constraint

The production symptom was initially described as stale source data because
Tyreek Hill and Joe Mixon retained historical PPG projections despite having no
current NFL team. A direct Sleeper check and the preserved local player cache
agreed on the current state: both players had a blank NFL team. The defect was
downstream eligibility semantics, not an upstream refresh failure. Jalen Nailor
also demonstrated why a position-relative horizon percentile must not be shown
as a cross-position market price.

The deterministic availability seam now distinguishes `no_current_nfl_team`
from an injury flag and from missing team evidence. Historical projection and
market context remain available, but next-game and rest-of-season actionable
scores are withheld, confidence is lowered, and copy says the baseline is
conditional on signing. The writer packet carries this distinction so a long
view can discuss a conditional asset without allowing a weekly desk to print a
false current-role forecast.

The publication seam also gained a deterministic editor review. An article must
have the required story fields plus evidence and source receipts before it is
approved; otherwise it is held off the facade with a visible reason. Previous
and peer articles may provide bounded non-evidence context to distinct writers,
but they cannot be cited as facts or defeat the editor gate.

## 2026-08-26 - Market clocks must show the quality of their price anchor

The four-window table now carries `market_source_count`,
`market_disagreement_score`, and `market_source_confidence` from the canonical
market consensus row. These fields qualify clock-versus-market research leads;
they do not rescale the horizon scores or create a second price model. A missing
market receipt is unavailable rather than zero, and the same fields are retained
in append-only horizon snapshots so later analysis can separate market evidence
changes from model changes.
The local trust gate accepts either a fully populated receipt or an explicitly
unavailable one; partial, malformed, or unsupported quality fields fail closed
before the data reaches the browser or writer packet.

## 2026-08-26 - Additional market sources must enter through an explicit seam

The market consensus contract already supported component sources, but the
refresh had no configured path for a second user-supplied export. Optional
`external_sources.market_value_files` entries now load canonical 0-100 CSV
values from the durable data root, label them `user_provided`, and preserve a
manual-file trace. The loader performs no magnitude-based rescaling and does
not scrape restricted providers. This gives the personal edition a safe path
to improve market breadth while keeping source count and disagreement honest.
## 2026-08-26 horizon identity and publication boundary

The horizon market is now row-scoped to league_id, not merely scoped by the
refresh that produced the file. A selected league filters the roster identity
before roster_id and mutable team labels are attached, and the selected
Sleeper roster wins over legacy projection labels. This is an explicit defense
against repeated roster IDs, stale names, and cross-league player joins.

The written horizon article is a publication layer, not a CSV dump. It
surfaces one lead per position in each window, a capped market-versus-clock
queue, and a capped contender/rebuilder queue. Full rows and receipts remain
available behind the article. Injury-aware PPG copy says “conditional baseline
PPG if active” when appropriate; no recovery timeline is invented.

## 2026-08-26 - Give each market clock a usable reading mode

The board previously showed every clock, fit, transition, and repricing field
on every player card. Although the labels were technically accurate, the
density made it easy to miss the actual question being answered. The browser
now offers focused views for this week, rest of season, dynasty/career,
contender versus rebuilder, and repricing leads. These are presentation modes
over the same deterministic rows; they do not create duplicate market scores
or duplicate paid articles.

## 2026-08-26 - Percentile labels must name their comparison class

Position-relative projection and market percentiles are now labeled with
their position scope in the Signal Board and with their horizon window in
trade and manager tables. The cross-position field is labeled market price
anchor. This is a UI contract, not a formula change: it prevents a high
percentile in one position from being read as a higher trade price than a
lower percentile in another position.

## 2026-08-26 - Preview writer work before paying for it

The six-desk publication is now preceded by a protected generation plan. The
plan uses the production evidence scopes and the same receipt-reuse predicate
as the writer workflow, then reports generation, reuse, fallback, and blocked
states per desk. It never calls the provider. This preserves the cost boundary
and makes a new horizon article or persona change inspectable before a Luna
run.

## 2026-08-26 - Every writer scope must carry league identity

The Four-Window writer scope filtered horizon rows by season but did not yet
enforce the explicit `league_id` boundary used by the other desks. That was a
real multi-league leakage risk even though the current private refresh usually
writes one current-season cohort. The scope now rejects identified rows from a
different league, and an adversarial test proves the other league's player
cannot enter the selected packet.

## 2026-08-26 - Make baseline PPG conditionality visible in every player read

The deterministic rest-of-season number remains a production baseline, not a
recovery-adjusted forecast. The focused browser market view, player dossier,
and deterministic writer fallbacks now say “conditional baseline PPG if
active” only when the current Sleeper snapshot has a limiting injury or
availability status; Active and Healthy rows retain the shorter “season
baseline PPG” label. This keeps a current status from being misread as a
season-long absence while making the difference between baseline production
and immediate availability visible at the point of decision.

## 2026-08-26 - Manager horizon coverage must be clock-specific

An aggregate transaction-lane match count could make a manager profile look
equally supported across all decision windows when only one or two horizon
fields were present. Manager transaction lanes now preserve per-clock acquired
and sold match counts for next game, rest of season, dynasty, career window,
and both strategic fit lenses, plus a readable coverage detail and structured
`horizon_coverage_by_clock` receipt for dossier writers. The profile continues
to describe current horizon averages as context for historically moved
players, never as historical prices or proof of intent.

## 2026-08-26 - Player horizon pages must reuse the authenticated scope

The Four-Window board already applied the selected league and season filter,
but the player-page entry path was still selecting horizon rows by player and
roster alone. The player page and team strategy overlay now reuse the same
`scopedCurrentRows` boundary, so a future multi-league bundle cannot show a
same-ID row from another league simply because the player name matched.

## 2026-08-26 - Availability language is one shared publication contract

Availability semantics were duplicated across the deterministic fallback,
writer packet scopes, and front-page editorial summaries. That allowed a
neutral or already-active status to drift into conditional PPG wording in one
surface while another surface used plain baseline copy. The shared
`src/availability.py` contract now treats Active, Healthy, Available, None,
and explicit no-current-injury receipts as neutral, and only uses conditional
baseline language for a limiting current status or a note with a recognized
availability marker. All publication and writer PPG summaries reuse this
contract; it remains current-only provenance and does not create a
recovery-adjusted projection.

## 2026-08-26 - Treat market movement as a dated receipt, not another score

The four horizon scores explain different decisions, but a current row alone
cannot tell the reader what changed since the last run. The refresh now
compares the current row with the latest earlier snapshot in the same exact
league, season, roster, player, position, and model scope and writes
`horizon_market_movements.csv`. Same-week reruns and first-run baselines do
not create movement. The artifact exposes endpoint deltas, the largest clock
movement, fit/lane changes, evidence, and source trace; it does not introduce
a fifth valuation formula or let a writer call a percentile delta a proven
mispricing.

## 2026-08-26 - Current news cannot become historical evidence

The league-news join was preserving a current event for every historical
season in which a player had an ownership row. That created repeated entries in
the global impact artifact and could make a present-day catalyst look like a
dated historical observation. The refresh now filters identified ownership to
the configured current season before fan-out across current leagues, while
blank-season legacy rows remain explicitly unscoped. News remains a source
event and impact receipt, not a historical manager or player fact.

## 2026-08-26 - Missing roster joins must not choose a neighboring row

The reader and team-report packet still had two dangerous compatibility
fallbacks: an absent manager roster match could select the first manager in the
file, and an absent team dossier match could fall back to all player rows.
Those fallbacks made a correct Clerk/Sleeper identity boundary look broken at
the presentation layer. They now fail closed to an empty or quiet read, while
unscoped legacy rows remain usable only when no identified scope exists. The
entry-path tests explicitly prove that a wrong roster cannot appear in the
selected edition.

## 2026-08-26 - A writer preview must predict the real reuse decision

The protected writer plan claimed to use the same fingerprint as the paid
workflow, but the workflow added newly generated peer articles to later desks'
fingerprints while the plan could not know that prose without making provider
calls. That made an unchanged issue look more expensive than it was. Peer and
previous-edition prose remains in the writer prompt as non-evidence newsroom
context, while the stable evidence fingerprint now covers only the selected
evidence, scope, prompt, reporter, model, and editor mode. A regression test
generates the full multi-desk issue and confirms the subsequent no-cost plan
reports reuse for every unchanged article.

## 2026-08-26 - Keep durable dossiers deep but writer packets bounded

The first Luna publication run showed that raw manager dossier histories were
too large for a reliable provider request. We keep the full deterministic
dossier for the data room, but the writer receives a bounded packet containing
aggregates, recent history, leading trade fits, and unknowns. The generation
workflow also accepts an explicit desk retry so a rate-limited writer can be
re-run without spending again on approved desks. This preserves depth in the
product while making cost and failure boundaries operable.

## 2026-08-26 - Identity rechecks need a visible timeout

Sleeper league discovery can take longer than a normal browser interaction
when several leagues are linked. The identity button now stops waiting after
20 seconds and reports that the saved verified identity is unchanged, rather
than leaving the page permanently stuck on “Checking.”

## 2026-08-26 - A persisted issue cannot define the current newsroom schema

The first authenticated production check after the six-desk release exposed a
presentation drift: the durable issue had been written before Market Clock
Morgan joined the lineup, so the page claimed six reporters while its visible
newsroom roster listed five. The authenticated league view now re-resolves the
lineup from the current article registry on every read, using writer
preferences only when their profile roster ID matches the verified Sleeper
roster. This repairs old bundles without inventing content, leaking another
league's preferences, or requiring a paid writer run.

## 2026-08-26 - Six-desk propagation is fixed; source-name sync remains open

Commit `1ede08a` is live. The authenticated production facade now shows all
six visible desks, including Market Clock Morgan, even when the persisted
issue predates that desk. Public revision-aware smoke passes and the exact
Dynasty roster remains verified. The same browser check still renders
`Melkor Lord of Light` in the selected edition while the current source-backed
roster data says `Lulu’s Potatoe’s`. The identity recheck returned `invalid
session token`, so no production identity repair is claimed. A fresh Clerk
session or an explicit source-name synchronization is still required before
the edition can be called fully current.

## 2026-08-26 - Current Sleeper labels follow the exact roster source row

The production check exposed a second identity/presentation seam: the exact
roster was verified, but a private profile had persisted its former Sleeper
name and the edition printed that historical label. Team names are mutable
source labels, so the new `src/team_identity.py` resolver selects the current
exact `league_id` + `season` + `roster_id` row, recognizes same-owner
historical labels as stale source presentation, and preserves any genuinely
different Front Office label as a private alias. Refresh, browser-shell
rebuild, profile reads, and the authenticated home view use the same resolver.
When a stored editorial issue contains the stale label in its headline or
dek, the read boundary recompiles the deterministic facade in memory so the
home page does not print old source presentation while waiting for a paid
writer run. Roster IDs remain the identity boundary; this change does not infer
ownership from a name.

## 2026-08-26 - Static edition entry must migrate preserved article wording

The home route could repair its deterministic issue in memory, but a direct
league entry still served a preserved static shell whose six article bodies
contained the former team label. The browser bundle now carries an explicit
`source_label_v1` contract. A bundle missing that marker is rebuilt at the
entry path, and the rebuild replaces only known historical `team_name` labels
in the six preserved publication bodies, refreshing their content hashes while
leaving evidence fingerprints and paid writer decisions intact. This is a
presentation migration, not an LLM regeneration.

## 2026-08-26 - Writer prompts are not enough for availability truth

The six-desk writer packet already carried current availability, conditional
historical baselines, and horizon limits, and the editor prompt named those
rules. That was necessary but not sufficient: a confident writer could still
turn a no-current-team player's historical PPG into an active-sounding
projection. The article validator now runs a deterministic, evidence-aware
claim-boundary check before an article can be recorded as generated. It holds
unqualified projection/PPG language for a player with no current NFL team and
warns when injury-sensitive rest-of-season production lacks the
not-recovery-adjusted caveat. The packet remains the source of facts; the
check does not invent a replacement score or recovery forecast.

## 2026-08-26 - Provider turbulence and editor failures must remain visible

Writer calls now use a bounded retry policy for transient provider responses
such as rate limiting, timeouts, and 5xx errors. The retry is deliberately
small and capped so a paid newsroom run cannot become an unbounded background
job. A final provider failure still flows through the normal receipt path.

When the optional LLM desk editor itself fails, the workflow now preserves the
validated reporter draft but records a held editor receipt instead of silently
leaving the prior deterministic publication in place. The reader can therefore
distinguish an approved article, an evidence-led fallback, and a draft waiting
for editor review; a failed provider cannot masquerade as editorial approval.

## 2026-08-26 - Aggregate job state must stay inside the user boundary

Unscoped refresh and all-edition writer actions previously wrote one legacy
global operator status file, while the authenticated headquarters summarized
per-user league status files. That mismatch could leave a user's interface
stuck on `Refreshing` or make an aggregate run invisible to its own status
poller. Aggregate receipts now live under the authenticated user's workspace,
and a persisted `running` receipt is converted to an explicit interrupted
failure after a process restart so a daemon restart cannot permanently block
the next run. League-scoped jobs continue to use their exact league workspace.

## 2026-08-26 newsroom progress must be durable and per-desk

The asynchronous writer action previously wrote a single `running` receipt
until refresh, six desk calls, optional editor calls, and browser rebuild all
finished. That made a healthy Luna run look frozen and gave the UI no way to
distinguish no progress from a slow provider response. The writer now persists
compact progress after each desk with the active reporter, completed/total
counts, model, reasoning effort, and per-desk state; it never includes prose,
evidence, secrets, or host paths in that progress payload. Reader polling also
waits long enough for the configured multi-call newsroom to finish, while the
durable final receipt remains authoritative after a tab sleeps or reloads.

### 2026-08-26: Do not call database-only writer artifacts published

The writer database receipt and the reader publication manifest are separate
claims. `content_artifact_status` now fails closed when the manifest is absent:
database rows are reported as unverified rather than current. A generated
article is only counted as current when its content hash and bundle revision
match the authenticated reader's manifest. This prevents a missing or
rebuilding bundle from presenting private historical artifacts as live content.

Current reporter status also requires the manifest receipt to match the
configured writer model and, when an editor receipt exists, to be approved.
Held drafts and pre-Luna articles therefore remain visible as history or
fallback, never as current publication.

## 2026-08-26 - Conditional free-agent baselines cannot calibrate current signals

The projection layer intentionally preserves historical PPG for a player with
no current NFL team, but that row is not a current-role peer. The signal layer
now excludes those rows from the active projection percentile cohort and leaves
their own current projection percentile and market-gap signal unavailable.
Their `market_gap_status` is explicitly
`availability_conditioned_unavailable`, rather than a misleading aligned or
disagreement label. This keeps the historical context useful for dynasty
research without letting a free-agent veteran distort current
projection-versus-market rankings. An adversarial test covers both the cohort
and the conditional row.
