# Epic: Realize Fantasy Dominator as a Personal Front Office

Status: in progress
Date: 2026-08-25
Owner: Fantasy Dominator product

This epic turns Fantasy Dominator from a well-intentioned collection of data,
analysis, and presentation surfaces into one truthful, durable personal media
and decision-support product.

The product loop is:

```text
Sleeper data
  -> validated evidence
  -> deterministic insight
  -> distinct analyst interpretation
  -> visual publication
  -> manager decision
  -> recorded outcome
```

The work is intentionally staged as vertical slices. Each slice must improve
the usable product and strengthen the contract needed by the next slice. Do not
begin by adding more pages, writers, charts, or generated images without first
connecting the existing layers at their seams.

## 2026-08-25 player-history identity checkpoint

The player transaction ledger now preserves Sleeper player IDs in normalized
trade and waiver rows, records both sides of a trade as `acquired` or `sold`,
and carries an explicit `identity_method` into player dossiers and the
browser. Direct source IDs are preferred; a unique historical name match is
marked `normalized_name`, while ambiguous or missing matches remain visibly
unresolved. This prevents a long player history from looking deep while its
rows cannot actually be joined to the player being analyzed.

The lesson is structural: every historical evidence object needs a stable
entity key and a labeled fallback path. A display name can help recover a
legacy row, but it cannot silently become canonical identity. The next
acceptance check is a refreshed artifact showing coverage of source IDs and
explicit unresolved counts.

The local trust gate now reports that coverage instead of treating the history
CSV as opaque. It fails on unsupported identity methods, a missing ID under a
resolved method, missing source traces, or invalid trade direction, and warns
when legitimate legacy name matches remain unresolved or trade direction is
asymmetric.

## Product north star

The finished product should let one manager:

- log in and immediately see the correct league and exact Sleeper roster;
- read a compelling daily edition through distinct analyst lenses;
- understand what changed, why it matters, and what decision it creates;
- move from every important claim to the underlying evidence;
- inspect current and historical player, team, and manager dossiers;
- find plausible trade opportunities specific to the selected roster and league;
- see freshness, source limitations, fallback content, and uncertainty honestly;
- return later and understand what changed since the last edition.

## Research-derived principles

These references informed the epic and should remain part of its design
vocabulary:

- The Pudding's data-story guidance: use a clear takeaway, a concrete data
  point, and a visual or interaction that advances the argument. One point per
  chart is a useful discipline; interaction must have narrative purpose.
  https://pudding.cool/process/how-to-make-dope-shit-part-3/
- Baseball Savant: combine an at-a-glance player snapshot, percentile-style
  comparisons, deep searchable data, and a glossary. This is a model for player
  and manager dossier design.
  https://baseballsavant.mlb.com/en/statcast_search
- Structured content and editorial workflows: articles, authors, media,
  metadata, ownership, readiness, history, and dependencies should be durable
  objects rather than one untracked prose blob.
  https://www.contentful.com/blog/wysiwig-who-structured-content-editor-best-friend/
  https://www.sanity.io/editorial-workflows
- Financial Times Visual Vocabulary: choose a visual based on the relationship
  being communicated, such as change, ranking, deviation, distribution, or
  correlation, rather than choosing the easiest chart to render.
  https://github.com/Financial-Times/chart-doctor/tree/main/visual-vocabulary
- OpenAI image generation: use the Image API for a one-shot asset and the
  Responses API for iterative image workflows. Treat size, quality, format,
  compression, moderation, and cost as explicit controls.
  https://developers.openai.com/api/docs/guides/image-generation
- Media delivery and accessibility: use responsive image variants, deliberate
  loading behavior, and meaningful alternative text.
  https://web.dev/articles/serve-responsive-images
  https://www.w3.org/WAI/tutorials/images/

## Workstream 1: Make publication truthful

This is the first implementation slice. Do not run another expensive content
generation cycle until this seam is reliable.

Add a real publication contract for every article:

- `article_id`
- `league_id`
- `roster_id`
- `section`
- `reporter_id`
- `content_status`
- `writer_mode`
- `evidence_fingerprint`
- `source_receipt`
- `bundle_revision`
- `content_hash`
- `generated_at`
- `fallback_reason`
- `model`
- generation-cost metadata where available

Acceptance criteria:

- The homepage only reports an article as published when the current browser
  bundle references that exact artifact.
- The homepage, edition page, Data Room, and operator status report the same
  revision and status.
- Unchanged evidence produces zero unnecessary LLM calls.
- Failed or partial articles remain visibly marked as deterministic fallback.
- Every story shows the reporter persona, never a team name.
- The selected `league_id` reliably controls homepage focus in production.
- An authenticated browser test proves Clerk user -> Sleeper user -> league ->
  roster ID -> rendered team name.

This directly addresses the observed contradiction between `5/5 reporter
articles`, `Evidence-led template`, and deterministic story cards.

## Workstream 2: Create canonical evidence packets

The LLM must receive structured, inspectable evidence packets rather than
loosely assembled rows.

Each packet should contain:

- claim candidates;
- supporting rows and evidence IDs;
- source IDs and freshness;
- source count and confidence;
- calculation or transformation used;
- related player, team, and manager IDs;
- permitted interpretation boundaries.

Acceptance criteria:

- Every written claim cites evidence IDs that exist in the selected league.
- A source count of one is labeled a single-source reference, not consensus.
- Missing sources lower confidence visibly.
- Historical names and current names are distinguished.
- Evidence packets are fingerprinted and reusable across article, UI, and
  dossier surfaces.
- Writers cannot create facts, transactions, motives, or certainty beyond the
  packet.

## Workstream 3: Turn the daily read into a real publication

The front page must consume structured article objects, not independently
reconstruct deterministic cards.

Each article should contain:

- headline, dek, and lede;
- reporter and editorial lens;
- thesis and what changed;
- supporting evidence and counter-evidence;
- action or question;
- risk and confidence;
- related entities;
- optional visual brief;
- evidence drawer link.

Initial reporter assignments:

- Topline Tony: what matters this week;
- Waiver Wire Waverly: waiver movement and roster-specific adds;
- Trade Desk Talia: counterparties and trade opportunities;
- Look-Ahead Lonnie: schedule, future value, stashes, and deadlines;
- Dossier Dana: manager and team history.

Acceptance criteria:

- The five section articles are visibly different in voice and purpose.
- The daily brief synthesizes article objects rather than recreating their
  facts.
- Unchanged articles are retained rather than regenerated.
- A changed evidence packet regenerates only the affected article.
- The reader can see whether each section is LLM-written or deterministic
  fallback.
- A complete issue has one consistent publication timestamp and revision.

## Workstream 4: Make identity and team switching reliable

The personal HQ should lead with ready, active leagues instead of incomplete
editions.

Implement:

- selected or most recently used league preference;
- clear ready, stale, and waiting-for-refresh groups;
- exact roster selection by `roster_id`;
- current team name separated from historical aliases;
- strategy profile name separated from team name;
- a clear roster-recovery path;
- strict user, league, and roster scoping for all private content.

Acceptance criteria:

- Lulu’s Potatoe’s remains the selected team after refresh and re-login when
  that is the current Sleeper label; name changes are picked up from Sleeper
  after refresh.
- Moose Caboose cannot appear as the selected team through name matching.
- Historical team names remain available without changing current identity.
- Every private artifact is scoped to user, league, and roster.
- The homepage opens to a useful edition or explains why none is ready.

## Workstream 5: Build real manager dossiers

The current manager data is a strong foundation, but aggregate metrics are not
yet a useful dossier.

Each manager dossier should include:

- current roster construction;
- season-by-season transaction timeline;
- players repeatedly acquired and sold;
- trade partners;
- waiver and FAAB behavior;
- pick accumulation or selling;
- contender/rebuilder transitions;
- preferred asset types and positions;
- transaction timing;
- confidence and sample size;
- plausible trade fits;
- evidence-backed questions to ask that manager.

Observed behavior, deterministic estimates, editorial interpretation, and
unknown motives must be visibly distinct.

Acceptance criteria:

- Each manager has a readable dossier, not only a metrics table.
- Historical behavior is visible by season.
- Every tendency has sample size and evidence.
- The dossier identifies a supported opportunity or explicitly says none is
  supported.
- No manager motive is stated as fact.

## Workstream 6: Make Trade Desk actionable but read-only

Trade Desk output should be a decision packet, not a generic target list.

Each opportunity should include:

- target manager;
- asset or assets to pursue;
- assets from the selected roster that may appeal to that manager;
- plausible offer range and minimum acceptable return;
- why the manager might care;
- historical evidence;
- risk of waiting and risk of acting;
- alternative counterparties;
- do-not-chase conditions.

Acceptance criteria:

- A user can understand the proposed conversation without reconstructing it
  from raw tables.
- Suggestions are explicitly read-only.
- The system never implies an offer was sent or accepted.
- Counterparty fit is tied to actual roster ownership and history.
- Recommendations show evidence and confidence, not only a score.
- The packet separates the target's owned assets from our exact-roster offer
  candidates.
- Offer candidates are ranked only against observed valuation lanes and carry
  evidence count and confidence; they are never presented as a predicted
  response or an automatically generated offer.

## Workstream 7: Rebuild the data room around questions

The Data Room remains available, but it should stop being the primary
presentation.

Organize the reader experience around questions:

- What changed?
- Why does it matter to my team?
- Which players are mispriced?
- Who is most likely to trade?
- Which signals disagree?
- What evidence is weak or stale?
- What should I investigate next?

Use visual forms based on the question:

- change over time -> sparkline or slope;
- ranking -> percentile band;
- disagreement -> diverging comparison;
- manager activity -> timeline;
- roster construction -> positional composition;
- trade fit -> two-sided comparison;
- uncertainty -> confidence range or evidence count.

Raw tables become drill-down tools with glossary links, source/freshness
indicators, filters, exports, and accessible mobile behavior.

## Workstream 8: Add a controlled media asset system

Generated imagery should strengthen the editorial identity without pretending
to be evidence.

Create an asset manifest containing:

- `asset_id`, `asset_type`, and purpose;
- user/league/article scope;
- prompt template and prompt hash;
- model, quality, size, and format;
- generation timestamp and content hash;
- alt text and credit/provenance;
- moderation and publication status.

Start with reusable assets:

- Front Office masthead;
- reporter portraits or illustrated avatars;
- section headers;
- abstract market, waiver, draft, and war-room illustrations;
- manager dossier textures;
- article-specific hero art only for major stories.

Do not generate factual text, statistics, team logos, or claims into images.
Those belong in HTML and data visualizations where they remain accurate and
accessible.

Acceptance criteria:

- Assets are versioned and tied to the content revision that uses them.
- Unchanged content does not regenerate unchanged art.
- Desktop and mobile variants are served responsively.
- Above-the-fold hero media loads eagerly; below-the-fold media is lazy-loaded.
- Every informative image has useful alt text.
- A media failure never blocks an article.
- Cost and generation state are visible to the operator.

Keep text generation on the configured Luna path, but use a separate image
model configuration. Image generation must not be coupled to article facts.

## Workstream 9: Add the learning loop

Eventually the system should learn what is useful to this manager. Track:

- articles opened;
- evidence drawers inspected;
- recommendations saved or dismissed;
- trade ideas pursued;
- prediction outcomes;
- stale or incorrect claims;
- manager-behavior prediction outcomes;
- writer usefulness by persona;
- generation cost per artifact.

This is a decision-support feedback loop, not personalization based only on
engagement counts.

## Release sequence

### Release 1: Truthful edition

Fix league selection, story attribution, artifact fingerprints, bundle
revisions, generated-article wiring, truthful status, and authenticated
production verification.

### Release 2: Useful front office

Improve team switching, evidence packets, source/confidence labels, Markdown
rendering, and narrative player pages.

### Release 3: Competitive intelligence

Build full manager dossiers, actionable Trade Desk packets, team-versus-manager
opportunity views, and historical aliases/timelines.

### Release 4: Media product

Add reporter-specific visual language, generated section art, responsive media
delivery, accessibility checks, and one or two high-value interactive data
stories.

### Release 5: Learning system

Track recommendation outcomes, content usefulness, historical prediction
quality, and prompt improvements.

## Non-goals

- Re-platforming the entire application.
- Adding more writers before the shared story schema works.
- Building charts that do not answer a decision question.
- Allowing LLMs to invent facts or execute transactions.
- Generating images before the publication contract is truthful.
- Building a broad public fantasy product.
- Scheduling LLM generation before cost and freshness controls are reliable.

## Definition of done for the epic

The epic is complete when a signed-in user can select a league, see the correct
Sleeper roster, read a current issue whose stories are actually backed by
validated article artifacts, inspect the evidence, open meaningful player and
manager dossiers, and receive read-only trade opportunities grounded in that
league's history. The system must report its revision, freshness, source
limitations, writer mode, and fallback state truthfully.

The first implementation slice is Workstream 1. Do not spend another content
run until that slice passes its production browser verification.

## 2026-08-25 implementation checkpoint

Workstreams 1-3 are now wired locally: article receipts include evidence and
content hashes, the browser bundle exposes a revision and publication receipt,
unchanged evidence skips the LLM call, and the reader-facing edition consumes
the actual article bodies. Workstreams 5-6 now emit structured manager dossier
and Trade Desk decision-packet fields, and Workstream 8 has an explicit media
manifest contract without coupling image generation to factual content.

The 2026-08-25 contract slice also makes article ID, section, roster scope,
source receipt, generation metadata, reporter, model, fallback reason, and
bundle binding explicit in storage. Writer calls request headline, thesis,
change, counter-signal, action, risk, confidence, related entities, and
optional non-factual art direction in addition to markdown. Canonical evidence
packets label source quality, freshness, calculation boundaries, and permitted
interpretation so a writer cannot turn a loosely assembled row into an
authoritative-sounding fact.

The first learning-loop seam is now local as well: a reader may explicitly
mark an article useful, needing work, or evidence reviewed. Those signals are
stored by user, league, exact roster, article, and bundle revision. Ordinary
page views are not silently treated as endorsement, and the feedback endpoint
cannot execute or communicate a fantasy transaction.

The selected-league preference is now persisted on the authenticated user
record. A valid league query updates that preference; a later home visit falls
back to the remembered owned league before considering the legacy default. This
is a continuity aid, not an identity shortcut: the selected team's roster is
still resolved through the linked Sleeper user and exact `roster_id`.

The revision-aware public smoke and signed-in browser check have now been
completed for the deployed revision. The selected owned league renders the
current Sleeper label, five publication receipts, and the question-led Data
Room. Release 1 remains open because Railway still reports `0/5 reporter
articles` in deterministic fallback mode; the operator-authorized Luna run
and its five reporter receipts still need to be completed and verified.

A first decorative masthead, `assets/media/front-office-masthead-v1.png`, is
now versioned in the repo and copied into each generated site through the
manifest. The masthead now also has a versioned mobile composition,
`assets/media/front-office-masthead-mobile-v1.png`, and the browser serves it
through a guarded responsive `<picture>` path with eager loading, dimensions,
and an explicit media receipt. Additional reporter art and article-specific
media remain Release 4 work; the artwork contains no factual text or
statistics.
## 2026-08-25 writer and outcome checkpoint

The first real Luna run completed all five section articles locally using the
configured `gpt-5.6-luna` provider. Each result carried a distinct reporter,
evidence fingerprint, content hash, and structured article payload; the
antagonistic review found that the generated copy preserved missing-data
limits and did not turn manager tendencies into certainty.

The reader now also has an explicit article outcome control: open, confirmed,
missed, or unclear. Outcomes are stored with the selected league, exact
roster, article key, and bundle revision. They are never inferred from page
views, and they do not claim that a recommendation was correct until the
manager records a result.

## 2026-08-25 learning-ledger checkpoint

The feedback loop now has a reader-facing summary in the Data Room. It counts
only deliberate signals, separates open calls from resolved outcomes, and
shows a confirmed rate only after the manager has recorded confirmed or missed
results. The summary is fetched through the authenticated league boundary and
is scoped to the exact verified roster, so a shared bundle cannot expose
another team's learning history.

Publication receipts now also retain an append-only change history. The Data
Room can show which article receipts are new, changed, failed, unchanged, or
not yet tracked, while the current artifact remains the source of truth for
what is published. A bundle revision change alone does not masquerade as a
new editorial insight. Provider usage metadata is retained with the current
receipt when available; the UI labels pricing as unknown rather than inventing
a cost estimate.

## 2026-08-25 fallback-receipt checkpoint

The browser entry path now renders a publication receipt for every displayed
section, including deterministic fallback articles that have no article-level
fingerprint. This keeps degraded content honest and preserves the one-click
route from the story to the Data Room instead of making a fallback silently
look like a complete generated article. The regression test covers the
fallback marker, evidence limitation text, and Data Room link; the production
gate must also verify the rendered receipt count against the visible sections.

## 2026-08-25 responsive-media checkpoint

The first media slice is now a real browser contract rather than a single CSS
background. The manifest records responsive variant media queries, public
paths, content hashes, dimensions, loading priority, and publication status.
The masthead uses a mobile-specific generated composition at narrow widths,
falls back to the desktop artwork and then to the text gradient if an image
fails, and exposes the decorative asset receipt in the Data Room. This is
deliberately limited to reusable masthead atmosphere; it does not claim that
all reporters have custom art or that artwork is evidence.

## 2026-08-25 Trade Desk depth checkpoint

The Trade Desk now carries `offer_candidates` as a structured shortlist from
the selected roster's `team_asset_inventory`. Each candidate is tied to the
counterparty's `manager_valuation_profiles` lane for its position group and
includes the lane label, preference score, evidence count, confidence, asset
liquidity, timeline fit, and source trace. The older `assets_we_can_offer`
name list remains as a compatibility field for existing readers.

This is a deliberate boundary: observed historical preference is useful for
opening a conversation, but it is not a quote, motive, or predicted response.
The UI labels the shortlist as potential assets to discuss, and the packet
retains explicit do-not-chase language. The behavioral test in
`tests/test_v_model.py` proves that the ranking uses the active roster and
does not leak an opponent's asset into the offer side.

## 2026-08-25 manager dossier entry-path checkpoint

Manager pages now open the same two-sided Trade Desk packet used by the main
Trade Desk: target assets, selected-roster offer candidates, valuation-lane
evidence, why-the-manager-might-care context, price guardrails, and
do-not-chase conditions. This closes the dossier-to-decision seam without
duplicating facts or implying that a trade was offered or accepted.

## 2026-08-25 player dossier entry-path checkpoint

Player pages now expose a structured dossier instead of only a headline and
metric tiles. The page connects the current analyst read to market,
projection, opportunity, role, news, and league-history evidence, then labels
confidence, source traces, watchouts, and the no-outcome guardrail. This makes
player analysis inspectable at the entity entry point while keeping canonical
facts in the data room.

The entry path was reviewed against the live signed-in bundle: an opponent's
player is visibly marked as `Opponent roster`, compact evidence labels keep the
read legible, and the full source trace remains available in a drawer.

The deployment check also now treats the rendered manifest revision as part of
the entry-path proof. A health revision alone cannot prove that an already-open
private browser has settled onto the new durable shell.

The next production writer attempt must be diagnosed from its returned
per-article receipt. The operator path now preserves workflow state, provider
and model metadata, reporter-level results, and validation messages instead of
replacing a failed run with a success-sounding refresh message. Until a
protected operator run produces five current reporter receipts, Release 1
remains open and the deterministic fallback must remain visible.

## 2026-08-25 deterministic fallback receipt parity checkpoint

The publication facade now gives deterministic fallback articles the same
inspectable receipt shape as generated articles: assigned reporter identity,
stable evidence fingerprint, explicit fallback reason, structured article
payload, and source receipt. The browser distinguishes article-level evidence
IDs from source-trace IDs and says when a fallback has no article-level
citation packet. This keeps the current degraded edition useful and honest
while leaving a clean seam for the protected Luna run to replace only the
interpretation layer.

This is a foundation rule for future depth work: every story path must carry
its way back to validated evidence, whether the story was generated by a
writer or rendered deterministically. New article types should extend this
receipt contract rather than inventing a lighter fallback format.

The deployment follow-up closed the durable-artifact seam behind this rule.
When a source-only deploy sees an old persisted shell, it now upgrades the
fallback markdown and embedded editorial payload in place from preserved
validated context before stamping the new source and bundle revisions. This
keeps the browser receipt truthful even when a full data refresh is not part of
the deploy.

The authenticated production check then confirmed the intended result on
`/league/1313490073630547968/#view-today`: the verified Sleeper roster is
`roster_id=2`, the current label is `Lulu’s Potatoe’s`, and all five displayed
fallback articles expose their new receipt metadata. Release 1 is still open
only for the protected Luna run; the deterministic publication itself is no
longer silently missing its evidence receipt.

## 2026-08-25 deterministic fallback story-spine checkpoint

Fallback articles now expose a versioned structured story spine: article-
specific lede, thesis, honest change boundary, counter-signal, action
question, and non-factual visual brief. This keeps the media facade useful
while a protected writer run is pending and gives Luna the same fields to
replace rather than creating a second presentation contract. A source-only
bundle migration upgrades older fallback payloads once and retains its
evidence fingerprint; it does not claim that deterministic text is writer
output.

## 2026-08-25 canonical fallback evidence checkpoint

The deterministic publication now carries row-level evidence IDs in the same
shape used by the writer packet contract. Player reads cite `player` evidence
rows; manager and trade reads cite `manager` rows; the daily brief preserves
the row type for both. The browser can therefore distinguish an exact evidence
anchor from a source trace even before the protected Luna run is available.
The next writer run can replace the interpretation while retaining this same
evidence identity seam.

## 2026-08-25 manager-season depth checkpoint

Manager dossiers now consume a deterministic `manager_season_history` ledger
rather than relying on career totals and historical-name strings. The ledger
preserves one row per historical manager roster, including quiet seasons,
trade and waiver activity, FAAB, assets moved, trade partners, roster shape,
exact roster identity, evidence, and source trace. The manager entry path now
renders that history alongside the existing cycle estimate and two-sided trade
packet.

The browser builder also derives the ledger from preserved canonical tables on
a source-only deployment when the newly introduced CSV is not present. An
adversarial shell-rebuild test proves that this migration does not change the
bundle on a second rebuild. This closes one important “metrics list versus
dossier” gap; it does not yet claim that manager intent is known or that the
Trade Desk has a guaranteed response model.

The ledger now also exposes observed transaction timing: active weeks, first,
last, and peak activity week, with trade and waiver weeks kept separate. This
adds the timing dimension required by the dossier contract without turning a
week number into a story about motive or deadline strategy.

## 2026-08-25 two-sided Trade Desk entry-path checkpoint

The main Trade Desk cards and manager team pages now share one browser packet
renderer. Both entry paths expose the target assets, selected-roster offer
shortlist, alternative counterparties when supported, why-the-manager-might-
care context, price guardrails, separate risks of waiting and acting,
do-not-chase conditions, and the evidence/source trace. The same packet is
explicitly read-only and labels potential assets as a conversation shortlist,
not a generated offer.

This closes the presentation seam where deterministic fields existed in the
artifact but were inconsistently visible at the decision point. It does not
claim a predicted response, a trade recommendation, or a complete market of
counterparties when the evidence does not support one; the empty alternative
counterparty state is shown honestly.

## 2026-08-25 reporter learning breakdown checkpoint

The authenticated learning summary now joins deliberate feedback and recorded
article outcomes back to the current scoped publication receipts. The Data
Room can show which reporter has received useful, not-useful, evidence-opened,
or resolved-outcome signals, along with article receipt coverage and a
confirmed rate only when confirmed or missed calls exist. Missing or stale
receipt joins remain explicitly unattributed; the system does not infer
usefulness from reading or treat an open call as a prediction result.

This is the first measurement seam for the newsroom lineup. It does not yet
claim statistically meaningful reporter evaluation; the sample size and
unresolved-call state remain visible so future content decisions have a clean
ledger to build on.

The browser now also seeds the desk list from the current publication
receipts, then overlays explicit database signals when available. This keeps
all five assigned desks visible before the first feedback record while
preserving zero as the honest usefulness count.

## 2026-08-25 manager dossier completeness checkpoint

Manager dossier entry pages now make the evidence boundary explicit even when
the current edge table is empty. Each dossier exposes seasons, observed
trades, waiver claims, observed events, active seasons, roster assets, and
market value, while the Trade-fit status section says either how many
evidence-backed fits are supported or that none is supported. The writer
context receives the same status and summary, so a missing fit cannot silently
become a generic manager story.

This closes the Workstream 5 acceptance gap where “no opportunity” was
previously represented by an absent section. It still does not claim manager
intent or a meaningful prediction rate from small samples.

## 2026-08-25 question-led event pulse checkpoint

The Data Room's “What changed?” answer now pairs current event volume with a
latest recorded pulse across news, trades, and waivers. Each item carries the
available player/team names, event detail, and timestamp in the question-led
surface, while the copy explicitly says that a current snapshot is not a
historical delta unless a prior receipt establishes that comparison.

This is a useful first event view without inventing a previous state or
burying the user in an unmotivated chart. The raw tables and source receipts
remain the authoritative drill-down.

## 2026-08-25 prior-bundle change receipt checkpoint

The question-led Data Room now preserves the prior durable reader bundle long
enough to compare the current `league_news_impact`, `trades`, and `waivers`
event scopes before overwrite. The deterministic `dataRoomDelta` receipt uses
source event IDs, reports per-table added/updated/removed counts, and exposes
a bounded list of newly recorded event views. The browser separates this
historical delta from the current event pulse and labels the comparison's
source scope.

The seam fails closed when there is no prior bundle or when any comparison
table is missing: the reader says that the change receipt is unavailable and
continues to show the current pulse without calling it historical change. The
entry-path test covers both verified and unavailable states. This is the first
return-later slice of the Data Room; it does not infer strategic importance,
manager intent, or recommendation outcome from event presence.

### Production acceptance amendment — `6e706ff`

Public revision smoke matched the full deployed source revision after Railway
propagation. The authenticated Chrome entry opened the private Joanie Loves
Dynasty Football edition for Lulu’s Potatoe’s, reached the question-led Data
Room, and rendered the verified “Since the prior reader bundle” receipt. The
receipt reported zero newly added news, trade, or waiver rows in this
comparison, while the separate current pulse remained visible with its source
event volume. The unavailable fallback was not substituted for a complete
comparison, and no private identity or source token was exposed.

## 2026-08-25 operator readiness overlay checkpoint

The authenticated operator surface revealed a useful seam before the next
writer run: clicking the LLM control without its required operator token
replaced the complete status receipt with only a blocked message. That made a
provider/model receipt disappear and could be mistaken for an API-key failure.
The browser now overlays blocked and client-side failure state onto the
existing status, preserving writer configuration, publication, and reader
contract evidence. The action remains fail-closed and makes no provider call.
This is a stability prerequisite for the protected Luna publication, not a
publication run itself.

## 2026-08-25 team construction entry-path checkpoint

The manager/team entity page now adds a deterministic Team construction panel
to the existing dossier. It is scoped to the selected current-season
`roster_id` and summarizes player count, position mix, market-value and
projected-PPG coverage, future firsts, need lanes, and roster-scoped action
mix. The construction evidence drawer names the source tables and coverage
counts so the summary is not another opaque analyst card. Missing market,
projection, or action joins remain `n/a` or explicitly unavailable.

The reader shell contract includes the Team construction marker so a durable
old shell cannot silently hide this entry path after deployment. This is a
team-context layer over existing evidence, not a new valuation model or lineup
recommendation.

### Production acceptance amendment — `1be8e7c`

Public revision smoke matched the deployed source revision. In the
authenticated private edition, the operator panel showed the configured
`openai / gpt-5.6-luna` writer receipt before the blocked action. Pressing the
LLM control without an operator token produced the explicit blocked message,
while preserving the writer API, provider, model, and publication receipt. No
provider call was made; the protected Luna publication remains an explicit
next action once the operator credential is available.

## 2026-08-25 cross-season trade-fit checkpoint

Manager dossiers now expose a deterministic comparison between current
counterparty edge rows and the manager's ranked historical valuation lanes.
The entry path shows aligned position groups when they exist, the number of
historical seasons in scope, lane evidence counts, recency-weighted scores,
and an explicit no-alignment state when the current fit does not match the
historical profile. This narrows the next conversation without treating a
preference lane as intent or a predicted response.

## 2026-08-25 manager transaction timeline entry-path slice

Manager dossiers now carry a bounded `transaction_timeline` derived from the
exact roster-scoped `manager_event_log` rows. The team dossier renders the 24
most recent observed trade/waiver events with season, week, counterparty,
assets moving in and out, FAAB/pick movement, and the event-level evidence
label. It explicitly says the log records what Sleeper observed, not why a
manager acted or what they will do next. The event timeline is structured in
the dossier payload so the browser and future writer packet consume the same
evidence object; the old aggregate-only manager view is no longer the only
path to historical behavior.

The authenticated production check after revision
`e99e0e6caf0854eae85b99b5e614711a2cdda343` loaded the private Joanie Loves
Dynasty Football edition with Lulu’s Potatoe’s as the verified active team,
then opened the Moose Caboose manager dossier and rendered 24 event rows.
Expanding the evidence drawer showed the event-level Sleeper trace and the
motive/future-behavior boundary. Public revision smoke also passed.

## 2026-08-25 manager-fit outcome entry-path slice

The manager dossier's current trade-fit cards now use the same scoped
recommendation outcome ledger as the main Trade Desk. Each direct manager
entry carries a `manager-fit:<roster_id>:<player_id>` key, the fit's evidence,
risk, and confidence, and a manager-fit outcome control. This makes the
manager page a learnable decision surface without confusing a fit hypothesis
with a completed trade or creating a second feedback system.

The authenticated production check after revision
`9fb20f8778fffb396e966af640fb11f6efc92824` opened the private Joanie Loves
Dynasty Football edition, entered Moose Caboose's dossier, and found six
`manager_fit` controls. The expanded drawer displayed the manager-fit label,
stable roster/player keys, and the evidence-bearing payload attributes without
submitting an outcome. The transient first bundle fetch was retried and the
clean entry then loaded the current reader.

## 2026-08-25 richer cross-season fit evaluation slice

Each current manager trade fit now carries a deterministic comparison to the
best matching historical valuation lane: aligned or no direct lane, lane
label, lane evidence, evidence count, confidence, and source trace. The
drawer also reports how many current fits align directly and how many remain
uncorroborated. This makes the cross-season comparison useful at the candidate
level while preserving the boundary that historical preference is not intent
or a predicted response.

The authenticated production check after revision
`2c8d2a6de187a8db50b8c472d2c6df93d4eb12bd` expanded Moose Caboose's
cross-season drawer and showed the live split of three directly aligned fits
and three with no direct historical lane. The six manager-fit payloads
retained their exact keys and candidate-level evidence.

## 2026-08-25 production migration gate remains open

The fallback story-spine code and local migration tests are in place, but the
first authenticated production check after revision
`3ca2e6b4925e5eccee9ededb4137b0d6bc4c6bbc` still found an older durable
user-scoped article payload: the source revision was current while the
embedded fallback `lede`, `thesis`, and `what_changed` remained empty. This is
the exact class of seam defect this epic is intended to prevent. Release
claims must remain scoped until a clean reader entry path proves the migrated
payload (or a current Luna receipt) in production.

## 2026-08-25 migration gate closed

Revision `a69e7fd30de84266029163248ef387855f5c3077` added a content-contract
check to the production serving path. A clean authenticated entry from
headquarters now proves the current source revision, exact `roster_id=2`
identity for Lulu’s Potatoe’s, the v2 fallback story spine, and the visual
direction inside the publication receipt. The stale durable-bundle regression
is closed and covered by an adversarial entry-path test. Release 1 remains open
only for the protected Luna run and its five current writer receipts.

The authenticated smoke contract now also checks all five publication receipt
objects and their structured story fields, including fallback visual direction.
This prevents a future green revision check from accepting a shallow shell
with missing or stale editorial payloads.

## 2026-08-25 article-specific media slice

The first controlled newsroom-art slice is now in the repository: versioned,
non-factual illustrations for the Look Ahead, Team Report, Market Watch, and
Trade Desk sections. Each asset is keyed to an `article_key` and `reporter_id`,
has a scoped media receipt, dimensions, alt text, prompt/model metadata, and
fails closed to text when unavailable. The publication renders the matching
desk art above each article and repeats its decorative-only status in the
publication receipt. This is a recognition and reading aid, not evidence; the
masthead remains the only hero asset. Future art should extend this contract
only when it improves comprehension or section recognition.

The production browser check after `e830e05` loaded all four desk images after
individual viewport entry, while preserving the authenticated `roster_id=2`
receipt for Lulu’s Potatoe’s. This closes the first media entry-path slice;
the protected Luna publication remains the separate open boundary.

## 2026-08-25 production boundary observed at `0c7b052`

At this checkpoint, public smoke reported the expected deployment revision, but
a clean signed-in manager entry still exposed the older embedded reader revision
`99b39f6` and omitted the current cross-season manager dossier contract. The
serving path therefore still needs an observable bundle-selection and
migration receipt, followed by a fail-closed response when it cannot produce a
current reader. This is the next required slice before protected Luna content
is generated or the release is described as fully propagated.

## 2026-08-25 reader-serving contract implemented

The route now computes a safe reader receipt for both user-scoped and legacy
migration candidates, exposes it through authenticated status/readiness, and
rechecks the final bundle after migration. Incomplete, wrong-identity, stale,
or contract-incomplete bundles cannot be returned as a successful reader;
they produce the branded recovery state instead. Local adversarial tests cover
the failed-recovery path and the absence of filesystem details. The remaining
acceptance check at this implementation checkpoint was a deployed signed-in
browser proof at the exact league route; that proof is recorded below.

## 2026-08-25 reader-serving gate verified in production

After deployment `acd8c3ab3b1bf69581cd8fa95b8c7c9f45994683`, public smoke and
the signed-in Chrome path were checked independently. A fresh reload served
the current private bundle and the repeat entry remained current. The
embedded receipt proved `roster_id=2` for Lulu’s Potatoe’s, all five article
receipt keys, `current · private` reader state, and the rendered
“Cross-season valuation lanes (6)” manager dossier section. The first stale
navigation before reload is retained as evidence that browser freshness is a
real precondition, not discarded as noise. The migration slice is accepted;
the protected Luna publication remains the next cost-gated boundary.

## 2026-08-25 Data Room semantic-quality receipt

The player-history identity audit is now carried into the browser bundle as a
deterministic `dataQuality.player_history_identity` receipt and rendered in the
Data Room. It reports row count, resolved/unresolved joins, identity methods,
and acquired-versus-sold balance. Fresh builds and shell-only rebuilds derive
the receipt from the same history rows the reader displays. Legacy or malformed
rows are labeled `partial` or `contract_error`; they cannot look like verified
historical depth. The entry-path tests cover both the partial-coverage state and
the fail-closed contract-error state.

## 2026-08-25 strategy overlay entry-path slice

The My Team surface no longer describes strategy value tags as planned while
the underlying fit tables sit unused. The browser now joins the exact active
roster IDs to `team_fit_scores` and `action_recommendations`, displays the
team's `team_needs_matrix` shape and need lanes, summarizes fit bands and
current action mix, and exposes the top aligned roster evidence. The roster
table carries the same fit/action labels and timeline/liquidity scores.

This is a presentation of deterministic evidence, not a new valuation model:
the join must be by `player_id` and selected `roster_id`, and an absent fit row
must remain `not_scored`. The old “planned overlay” copy is covered by an
entry-path test so a future UI change cannot silently regress to profile-only
customization.

## 2026-08-25 recommendation outcome entry-path slice

The decision ledger now has a separate recommendation lane. Target, sell, and
trade thesis cards expose an explicit outcome control; the browser submits a
scoped `recommendation` interaction carrying the thesis key, decision type,
subject, bundle revision, confidence, risk, and evidence snapshot. The API
validates the four allowed states and rejects recommendation outcomes sent as
article interactions. The learning summary reports recommendation calls and
rates separately from article usefulness and reporter outcomes.

This records the manager's later report; it does not infer success from a
page view, execute a transaction, or imply that a thesis became true. The
existing upsert key makes changing an open call to confirmed/missed replace
the current state without duplicating history rows.

### Production acceptance amendment — `375bed1`

The recommendation-learning slice is live and browser-verified. The exact
owned league route serves the current private bundle for Lulu’s Potatoe’s,
exposes 25 decision controls with the four validated outcome states, and the
Data Room shows the separate recommendation learning lane alongside the
verified historical identity receipt. The durable-shell migration contract is
now part of the acceptance gate for future reader capabilities.

## 2026-08-25 team construction entry-path checkpoint

The team entity page now has a deterministic Team construction panel for the
selected current season and exact `roster_id`. It presents roster count,
position mix, market-value and projected-PPG coverage, future firsts, need
lanes, recommendation mix, and a construction evidence drawer. Missing joins
remain `n/a` or unavailable; the panel is a roster snapshot, not a lineup or
valuation recommendation. The semantic `Team construction` shell marker and
browser entry-path test protect this surface from a stale durable shell.

### Production acceptance amendment — `db6c71e`

Public smoke passed at the full revision
`db6c71e34eb18c7069f7cd35361c83be65d39f48`. Authenticated Chrome opened the
private Joanie Loves Dynasty Football edition, then the Moose Caboose entity
page. The panel rendered exact roster ID 4 with 30 roster players, position
mix QB 6 / RB 9 / TE 2 / WR 13, market value 720.54, projected PPG 258.7,
recommendation mix, and the Construction evidence drawer. The private edition
continued to identify Lulu’s Potatoe’s as the signed-in manager’s team.

## 2026-08-25 market valuation reconciliation entry-path checkpoint

The first Team construction implementation exposed a real trust seam: its
market total was computed from `player_dossiers`, while the manager dossier
computed the same roster's economic total from the canonical
`team_asset_inventory`. Four internal proxy-valued players were therefore
silently omitted from the new panel. The construction panel now uses the
exact current-season inventory rows for market totals, keeps `player_dossiers`
for projection coverage, and reports both market-row coverage and the count
of `internal_proxy_player_value` rows. This makes the 30-player Moose Caboose
total reconcile to the manager dossier while preserving the external/proxy
distinction.

The entry-path test requires the inventory source and proxy receipt markers;
the production amendment will be recorded after the deployed browser check.

### Production acceptance amendment — `eb9b68d`

Public smoke passed for
`eb9b68d96f40cffa0afec6131547be178d8f1395`. Authenticated Chrome re-entered
the private edition, opened Moose Caboose's exact roster-4 entity page, and
verified that Team construction and Manager dossier both reported market
value 835.54. The construction receipt showed 30/30 market rows, four
internal proxy values, 30 projection rows, 30 action rows, and the exact
`team_asset_inventory` source trace. Lulu’s Potatoe’s remained the private
edition identity at the root.

## 2026-08-25 player market provenance entry-path checkpoint

The adjacent player entity route exposed the same join defect in smaller form:
Jimmy Horn's player dossier showed market value 0 even though the exact roster
asset ledger carried an internal proxy value of 43. Player pages now resolve a
rostered player's market value by exact `owner roster_id + asset_id` from
`team_asset_inventory`, label the value as external or internal proxy, and
fail closed to unavailable when the scoped asset row is missing. Unrostered
players may still use their profile market value because no owned asset row
exists. The entry-path test protects the inventory join and unavailable label;
the production amendment will follow the deployed browser check.

### Production acceptance amendment — `b014296`

Public smoke passed for
`b0142965abe1ba10986b40ed289eea21fa3b37e9`. Authenticated Chrome opened
Jimmy Horn's exact player entity page from Moose Caboose. The page rendered
market value 43, labeled it `internal proxy value`, and exposed the
`internal_proxy_player_value` trace; the team route still reconciled at
835.54 and the private root remained Lulu’s Potatoe’s.
