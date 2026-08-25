# Fantasy Dominator decision log

This is a short memory of decisions and failure modes that materially affect
the product. Add an entry when a future implementation changes one of these
boundaries.

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

The playbook also records the remaining realization boundary: the protected
Luna publication, deeper historical manager intelligence, consistently
two-sided Trade Desk packets, and a measured learning loop are still work to
execute. Future status claims should be amended with the implementation that
changes them.

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
