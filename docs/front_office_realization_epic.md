# Epic: Realize Fantasy Dominator as a Personal Front Office

Status: in progress
Date: 2026-08-25
Owner: Fantasy Dominator product

Current publication contract (2026-08-26): six desks are registered and
bundled—Daily Brief, Team Report, Market Watch, Four-Window Market Read, Trade
Desk, and Manager Intel. Older dated checkpoints below may report five desks or
`0/5` because they predate `horizon_watch`; those counts remain historical and
are not current production status.

## 2026-08-26 career-window presentation amendment

The player dossier now gives the bounded five-year career-window score its own
visible card instead of burying it in the Dynasty explanation. This keeps the
four decision windows and their component evidence legible: weekly utility,
rest-of-season production, dynasty market/timeline, and the separate internal
career scenario. The new card carries projected points, years, blended PPG,
status, and calculation basis; it does not change the deterministic formula or
present the scenario as a lifetime forecast or trade price.

## Data lifecycle boundary (2026-08-25)

Historical league assembly and recurring upkeep are separate operations. A
bootstrap run builds the historical Sleeper evidence base and derived
analytics. A maintenance run requests the current league and bounded
current-season weeks, merges canonical rows by exact source identity, and then
rebuilds derived tables and the browser bundle. This keeps maintenance cheaper
and prevents a narrow refresh from deleting the history that makes manager and
league dossiers meaningful.

The exact matchup-evidence slice is now promoted into the reusable
`league_standings` table. The League view shows standings and coverage so a
reader can distinguish a quiet/offseason team from a genuine 0-0 record. The
next model-depth slice is the history-anchored career window documented below.

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
- Market Clock Morgan: separate this week, season, dynasty, and career clocks;
- Trade Desk Talia: counterparties and trade opportunities;
- Look-Ahead Lonnie: schedule, future value, stashes, and deadlines;
- Dossier Dana: manager and team history.

Acceptance criteria:

- The six section articles are visibly different in voice and purpose.
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
current Sleeper label, five publication receipts at that historical checkpoint,
and the question-led Data Room. `horizon_watch` was added afterward, making the
current contract six desks. Release 1 remains open because Railway still
reports deterministic fallback until the operator-authorized Luna run and its
current reporter receipts are completed and verified.

A first decorative masthead, `assets/media/front-office-masthead-v1.png`, is
now versioned in the repo and copied into each generated site through the
manifest. The masthead now also has a versioned mobile composition,
`assets/media/front-office-masthead-mobile-v1.png`, and the browser serves it
through a guarded responsive `<picture>` path with eager loading, dimensions,
and an explicit media receipt. Additional reporter art and article-specific
media remain Release 4 work; the artwork contains no factual text or
statistics.
## 2026-08-25 writer and outcome checkpoint (five-desk contract)

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

## 2026-08-25 proxy market propagation checkpoint

The market provenance audit found 41 current player assets with nonzero
`internal_proxy_player_value` rows in `team_asset_inventory` but zero market
values in `player_dossiers`, `player_signal_scores`, and
`action_recommendations`. The deterministic pipeline now uses external market
values first and fills only missing players from the exact asset ledger,
carrying the proxy trace and proxy-aware risk/confidence language through
signals, actions, and profiles. A local rebuild reduced the mismatch count to
zero across all 41 proxy assets. Production acceptance requires a scoped
league refresh after deployment so the durable private bundle consumes the
newly rebuilt tables.

### Production acceptance amendment — `5654d74`

Public smoke passed for
`5654d74073656cb3ae225def1572ef74b450d67f`. The authenticated production
home identified the linked manager as Lulu’s Potatoe’s, the exact league
edition remained ready, and the scoped league refresh rebuilt the durable
bundle. The team route reconciled 30/30 market rows at 835.54, and Jimmy
Horn's player route showed market 43 with `Market source: internal proxy
value` and the `internal_proxy_player_value` trace. Because Jimmy lacks
projection support, the decision surface correctly remains low confidence
with sparse-projection risk.

## 2026-08-25 writer preflight receipt

Repeated protected writer attempts correctly failed before any provider call,
but the headquarters only exposed the failure after the user pressed the
button. The home Writer Desk now publishes a safe preflight receipt showing
the configured provider, exact model, reasoning effort, API-key readiness,
and operator-gate state. It explicitly distinguishes the Railway
`OPENAI_API_KEY` from the separate browser-entered
`FRONT_OFFICE_OPERATOR_TOKEN`; neither secret is rendered or persisted. This
is an operational depth slice for the cost-incurring publication boundary,
not a relaxation of the protected-write rule.

### Production acceptance amendment — `f3ea7ce`

Public smoke passed for
`f3ea7ce977ae1cd9e42523522ce9a3374f10646e`. The authenticated headquarters
still identified Lulu’s Potatoe’s and rendered the new preflight: provider
`openai`, model `gpt-5.6-luna`, reasoning `medium`, API key `ready`, and
operator gate `configured; browser key required`. The edition remains an
honest `0/5 reporter articles · evidence-led fallback`; no writer call was
made during this verification because the browser operator key was absent.

## 2026-08-25 writer model reconciliation checkpoint

The first API run may predate a model configuration change. The headquarters
now compares persisted generated article receipts with the currently configured
model and reports the last model plus the count that needs regeneration. A prior
model can therefore never look like current Luna output merely because an old
artifact exists in the durable database. The comparison is informational and
does not bypass the operator gate or trigger generation.

Local proof: the full 198-test suite, local data trust gate, and diff check
passed. Production acceptance still requires the authenticated protected Luna
run and five current reporter receipts; no production generation claim is made
by this local checkpoint.

### Production acceptance amendment — `92ae655`

Public smoke passed for
`92ae655ede886f601001101dd4c4850d332c1223`. Authenticated Chrome then loaded
the live headquarters and verified the exact `Lulu’s Potatoe’s` identity, the
new model-reconciliation marker, `gpt-5.6-luna`, API-key readiness, and the
separate operator gate. The prior persisted run was reported as Luna-aligned;
the edition remains `0/5 reporter articles · evidence-led fallback` because no
current operator-authorized generation was performed. Release 1 therefore
remains open at the protected publication boundary.

## 2026-08-25 matchup outcome depth checkpoint

Historical manager dossiers now have a deterministic outcome seam beneath the
existing transaction and roster ledger. The refresh preserves Sleeper's raw
weekly matchup payloads, normalizes one exact `roster_id` row per week with the
opponent ID, points, margin, result, evidence, and source endpoint, and feeds
those rows into `manager_season_history`. Dossiers can now show observed
season records and point differential without treating a missing endpoint,
offseason, or missing score as a 0-0 season.

The browser entry path exposes the result as a receipt and uses `n/a` for
recorded matchup count when the source state is `not_recorded`. Local tests
cover exact opponent joins, unplayed matchups, quiet seasons, dossier
summaries, and the generated browser marker. Production acceptance still
requires a fresh private league refresh and authenticated verification of the
actual preserved matchup coverage; this code/doc checkpoint does not claim
that the current durable production bundle contains historical matchup rows.

### Production acceptance amendment — `201c3f7`

Public smoke passed against the full revision
`201c3f7d2d6319dae7bdfc246ebb1f12f9aa3fed`. Authenticated Chrome then
reloaded the private Joanie Loves Dynasty Football edition and opened the
exact Lulu's Potatoe's team route, preserving `roster_id=2`. The live
manager dossier showed a recorded `45-37-18` outcome across 108 matchup rows
with the `manager_season_history;matchups` trace. The writer desk remained
at `0/5` fallback because the separate operator authorization was not
supplied; no paid generation claim is made.

## 2026-08-26 front-page depth and market trust checkpoint

The front page now receives a structured `front_page_panels` contract from the
issue builder. It presents the selected roster pulse, roster-linked news with
market context, projection/market disagreement candidates, and manager dossier
previews. Each panel item has an entity route, evidence trace, and explicit
uncertainty copy, so the newspaper facade remains a connected presentation
layer over the data room.

The market audit also closed a second scale regression downstream of the
DynastyProcess ingestion fix: canonical values above 100 are no longer divided
again by signal scoring. Old-player/low-market rows are discounted and labeled
`role_uncertain_watch` with a role-check action. This keeps recent per-game
production from becoming a false starter forecast while preserving the research
lead for human review. The refreshed local bundle now shows the selected
Lulu’s Potatoe’s roster, four linked news signals, and the four front-page
desks. The protected Luna run and production deployment remain separate gates.

## 2026-08-26 manager trajectory depth checkpoint

Manager dossiers now carry a deterministic `trajectory` object comparing the
latest two observed seasons with the preceding observed window. It reports the
season IDs, trade and waiver activity, records where available, per-season
activity delta, and explicit `insufficient_history`/`not_comparable` states.
The browser exposes this as a Manager trajectory evidence drawer on both the
active manager snapshot and exact team dossier pages; the manager article
packet receives the same object. This closes the remaining shallow-profile
seam around contender/rebuilder transitions and transaction timing without
turning partial current-season activity into intent or a forecast.

## 2026-08-26 Topline newsroom context checkpoint

The existing five-article publication contract now gives Topline Tony a real
league beat packet instead of only a valuation slice of the selected roster.
The `team_report` scope carries exact-roster player evidence plus current
league news, selected-team matchup rows, and selected-team trades/waivers.
The prompt names these as observed context and requires the reporter to
connect them to the roster read without turning them into future-performance
claims or manager intent. A contract test proves the packet includes all four
evidence classes while preserving current-season and league scoping.

## 2026-08-26 news boundary and presentation regression checkpoint

The first generated league-news bundle exposed a seam failure: long Sleeper
league IDs were loaded as scientific-notation numbers in the browser bundle,
so string-only filters made the News desk look empty even though the source
table contained rows. The impact table now preserves `league_id` and `season`,
ownership is scoped by league and player, and the issue builder uses an
ID-safe comparison at the presentation boundary. The browser now shows the
selected team's linked signals and the full current-league count while keeping
other leagues out of the private facade; a focused test protects the seam.

## 2026-08-26 written-depth and manager-identity checkpoint

The deterministic publication fallback now renders the same bounded Topline
Tony week ledger that the protected writer receives: selected-roster and
league news, matchup status, and recent trade/waiver evidence. Its receipt
reserves evidence IDs for those context classes instead of spending the whole
24-row cap on player valuation rows. Manager Intel now consumes the dossier
objects, exposing history sample size, recorded outcomes, descriptive
trajectory, and supported trade-fit lanes. Dossier history follows stable
Sleeper `owner_id` across historical roster-ID changes while current assets
remain exact-roster scoped.

The event-level browser table is now aligned with that rule: it carries the
canonical league and owner identity and cannot present a repeated roster
number from another league as the selected manager's history.

## 2026-08-26 publication-template checkpoint

The issue no longer treats all six article bodies as one generic blob. Each
desk has a reusable template contract (`morning-ledger`, `team-notebook`,
`market-ticker`, `trade-desk`, or `manager-dossier`) and a semantic block
projection from the durable markdown. The browser renders feature, wide, and
rail layouts with the same evidence receipt underneath, so the newspaper
facade can gain personality without forking the fact or writer pipeline.

## 2026-08-26 entity-news scope checkpoint

The refreshed browser bundle now scopes `league_news_impact` consistently in the
News Desk, question-led event pulse, and player entity pages. This matters
because a single global Sleeper event is materialized once per historical league
owner; the raw table is correct to repeat it, but a player page is not allowed
to present those historical copies as six current signals. Long league IDs are
compared numerically as well as textually at the browser seam. Local acceptance
is one current Tyreek Hill signal in the selected Lulu's Potatoe's league and
zero browser errors.

## 2026-08-26 mobile reading facade checkpoint

The publication templates now control list preview density. The first three
calls remain readable on the front page; long evidence, guardrails, and
additional calls are available through explicit drawers. The narrow shell also
uses a horizontal desk rail and removes duplicate masthead weight so the
reader reaches the issue sooner. This is a presentation-only projection: the
durable markdown, semantic blocks, receipts, and Data Room remain intact.

## 2026-08-26 news-to-market depth slice

The publication facade now has a deterministic `news_market_edges` table. It
is built only from current scoped `league_news_impact` rows and a meaningful
existing market-gap or sell-pressure score. It labels upside lag, pressure
lag, or mixed news, carries event count, market value, baseline PPG, evidence,
risk, confidence, and source trace, and is visible in the front-page Market
desk, Trade Desk signal board, Data Room diagnostics, and the Market Watch
writer packet. The existing projection-gap lane remains as a fallback.

This is the model for future editorial lanes: deterministic code identifies a
bounded, inspectable disagreement; a writer explains why it might matter; the
reader can inspect the receipt and decide. The LLM must not manufacture a
dislocation from prose or blend news across leagues.

## 2026-08-26 current writer-state reconciliation

The current local refresh produced deterministic-template fallback articles,
with receipts showing `model_mode=deterministic_template` and an explicit
fallback reason. The protected operator gate was not enabled, so no paid Luna
generation was run as part of this refresh. The earlier writer checkpoint above
records a prior local Luna exercise and remains historical; it must not be used
as proof that the current bundle or production has fresh Luna-written copy.

## 2026-08-25 manager outcome receipt checkpoint

Manager trajectory now separates activity coverage from outcome coverage. A
partial current season remains visible in the activity window, but its missing
matchups cannot create a stronger/weaker results claim. The dossier and browser
show recorded seasons, partial seasons, and the limited/not-comparable state.
The dossier also exposes `scored_matchups` separately from scheduled matchup
rows so the profile tile and narrative use the same denominator.
## 2026-08-25 horizon-market slice

The player decision layer now has a deterministic three-clock contract. Refresh
builds `player_horizon_market_scores` from season projections, weekly allocations,
availability, roster ownership, and signal/market evidence. It exposes separate
next-game, rest-of-season, and dynasty scores, plus contender fit, rebuilder fit,
and the spread between them. The player page, Market desk, team-report fallback,
and Market Watch writer packet all carry the same receipt.

This is intentionally a foundation rather than a claim that schedule-aware
weekly projections or career forecasts exist. The next-game lane stays
opponent-neutral until schedule/bye evidence is added; dynasty remains a
market/timeline lens. The next follow-up is schedule-aware weekly evidence and
calibration of horizon scores against observed outcomes, not a new ungrounded
ranking formula.

## 2026-08-26 matchup calibration receipt checkpoint

The schedule-aware horizon now carries an out-of-sample calibration receipt for
historical defensive factors. Each team/position factor is evaluated on later
seasons than the evidence used to build it, with validation seasons, evaluated
games, factor MAE, baseline MAE, MAE delta, direction accuracy, and a status.
The receipt reaches the player card and Market Watch/Team Report packets. This
does not claim that a factor predicts the next game; it lets the reader see
whether the adjustment has added signal in the available holdout sample.

## 2026-08-26 schedule-aware horizon follow-up

The next-game seam now consumes a preserved nflverse schedule and a small
historical position-level points-allowed factor. The browser and writer packets
carry the opponent, home/away state, bye status, matchup factor, and the
schedule coverage receipt. The remaining calibration work is to grade these
factors against observed weekly outcomes and eventually replace the internal
dynasty timeline proxy with a real multi-year production projection. The
following matchup-calibration checkpoint records that holdout grading was then
added; the multi-year production model remains future work.

The current implementation makes that distinction visible by adding a
five-year career-window projection and score to the same horizon receipt. The
score uses projected PPG, projected games, age, and documented position curves;
it is intentionally labeled an internal scenario and does not overwrite the
separate dynasty market score.

## 2026-08-26 three-clock market board checkpoint

The Three-Clock Market Board is now a first-class Trade Desk surface rather than
an implementation detail of player pages and writer packets. It supports active
team versus league scope, value-lane filtering, horizon sorting, player dossier
links, and an evidence/risk receipt on every displayed row. The board reuses the
canonical `player_horizon_market_scores` rows; it does not create a second
ranking formula or let browser controls rewrite deterministic facts. This is the
required bridge between the data room and the media facade: a reader can find a
contender/rebuilder disagreement, read the article lens, and inspect the same
hard evidence without leaving the decision surface.

The default board ordering now follows the selected team's configured strategy
(`contender`, `rebuilder`, or balanced) while preserving both fit scores and
the spread. This makes the board personal without creating a private or
untraceable score.

The horizon rows also carry `horizon_model_version` and `fit_basis`. The
version is part of the evidence receipt, and the weighting basis is visible to
the writer and reader, so a future formula change cannot masquerade as a data
refresh.

## 2026-08-26 availability-boundary checkpoint

The next-game lane may adjust expected points for a current Sleeper
availability flag, but the rest-of-season lane remains a production baseline
when no recovery timeline is available. The basis, risk receipt, fallback
writer prose, and player Three Clocks card now state that the rest-of-season
baseline is not recovery-adjusted. This keeps a questionable player from being
read as though the model had projected a full-season absence or recovery.

## 2026-08-26 score-scale checkpoint

The horizon score contract now carries `horizon_score_basis` with every row:
the four clock scores and contender/rebuilder fits are position-relative
percentiles from 0-100, not dollar market values or cross-position price
rankings. The browser and writer surfaces expose this receipt and direct the
reader to `market_value`/`market_percentile` for price comparisons. This is a
small but important guard against reproducing the earlier failure mode where a
surface-level score made a low-value player appear to outrank a star from a
different position.

## 2026-08-26 counterparty timeline bridge

The three clocks now inform the actual counterparty workflow. Exact player and
target-roster joins add target-team lens, active-team lens, fit spread, and a
versioned timeline read to every edge without changing the independent market
price calculation. The same receipt is carried into trade theses, manager
dossiers, deterministic Trade Desk prose, and the visible edge table/cards.
This turns contender-versus-rebuilder value from a concept on the market board
into a concrete question attached to a possible conversation while preserving
the human decision boundary.

## 2026-08-26 three-clock publication amendment

The three-clock market is now also a dedicated `horizon_watch` publication
desk, with Market Clock Morgan as its default reporter. Its evidence packet and
fallback article separate This Week, Rest of Season, Dynasty Window, and
Contender vs Rebuilder reads. The packet selects a small sample within each
position; position-relative percentiles are never presented as a universal
cross-position leaderboard, while canonical `market_value` remains the
cross-position price anchor. This adds an editorial layer on top of the hard
data without duplicating score calculations or changing the human decision
boundary.
## 2026-08-26 clock-transition receipt amendment

The three-clock market now records the movement between adjacent decision
windows: rest-of-season minus next-game, dynasty minus rest-of-season, and
five-year career-window minus dynasty. These later-minus-earlier deltas make
the disagreement legible as a market transition rather than leaving the reader
to subtract scores from a card or asking a writer to infer it. They remain
position-relative percentiles, not prices or new blended grades, and become
unavailable when either endpoint is unavailable.

The same fields now reach the Market Clock Morgan packet, deterministic
fallback, front-page market read, Three-Clock Market Board, and player dossier.
The contender/rebuilder weighted fit and its spread stay separate: a transition
can explain why a player's value moves through time, while the fit lens
explains which roster strategy benefits from that shape.

Each horizon row also reports `fit_coverage` and names omitted clock inputs in
the fit basis. When a partial row is still usable, the deterministic fit
renormalizes the remaining weights; the reader can therefore distinguish a
four-clock strategy fit from a partial evidence lead.

## 2026-08-26 history-anchored career-window checkpoint

The career clock now uses preserved nflverse weekly production when a current
Sleeper player has a unique normalized-name plus position match to one source
player ID. The five-year age curve blends the current season projection with a
recency-weighted historical PPG anchor and exposes the source player ID, join
method, history seasons, games, latest season, and PPG in the horizon receipt. A name
that resolves to multiple source IDs is withheld and falls back to the
age-only scenario with an explicit ambiguity risk; the Sleeper ID remains the
canonical player identity. This is a versioned deterministic model change,
not a claim that the scenario is a lifetime forecast or a trade price.

## 2026-08-26 manager transaction-lane depth checkpoint

The manager dossier now has a separate `manager_transaction_preferences` table
for identity-resolved player movement by position. It follows stable
`owner_id` lineage across historical roster IDs and distinguishes trade,
waiver, and draft acquisitions from disposals. Where those player IDs are
present in the current `player_horizon_market_scores` table, it adds the
current next-game, rest-of-season, dynasty, career-window, contender-fit, and
rebuilder-fit context plus acquired-minus-sold deltas.

This is intentionally not a historical price model. The horizon averages are
current context for names a manager previously moved; they do not prove that
the manager preferred those assets at the time, wants them now, or will accept
an offer. Unresolved player identities stay in an `UNKNOWN` lane, and sparse
lanes remain low-confidence. The Manager Room and Manager Map expose the same
receipt, giving Trade Desk analysis a deeper evidence layer without making a
new browser-only score.

## 2026-08-26 active-asset audience checkpoint

The counterparty workflow now has a two-sided audience layer. The new
`counterparty_asset_interest` table joins active-roster player assets to
identity-resolved manager transaction lanes, current team need, and available
horizon fit. Its `conversation_fit_score` is explicitly a research-priority
signal, not a market value, probability of acceptance, or claim about intent.

Trade theses, the Trade Desk, manager dossiers, and the writer packet now show
possible audiences for our assets alongside the existing seller-side
counterparty edges. Missing lanes remain absent rather than becoming inferred
demand; sparse history, missing horizons, confidence, risk, and source traces
remain visible. This is the bridge from “who owns the asset?” to “which
conversation is worth investigating?” without creating an offer generator or
a second market model.

## 2026-08-26 available-market publication checkpoint

The available-market research table now reaches the publication surface. Market
Watch gives Waiver Wire Waverly a position-aware packet of identity-resolved
names absent from the selected league roster, carrying all four clock scores,
clock-to-clock deltas, fit coverage, and the canonical price anchor. The front
page reserves one card for the same lane when usable evidence exists, while the
Draft Room remains the deeper board. Market Clock Morgan continues to own the
full-league clock comparison; Waverly interprets the available names. Both
articles sit on one deterministic source table, preserve missing evidence, and
state that roster absence is not proof of waiver eligibility.

## 2026-08-26 entity-entry follow-through

The available-market publication now has a connected player route. When a
front-page or horizon-board card points to a player who has no roster dossier,
the browser joins the identity-resolved available horizon row with canonical
player metadata and renders a player evidence page. It preserves missing
clocks, fit coverage, market anchor, and source trace, while explicitly
labeling the row as snapshot-based research rather than ownership or waiver
eligibility. This closes the publication-to-data-room entry path without
creating a second player model or another generation call.

## 2026-08-26 horizon surface integrity amendment

The Trade Desk now presents the four horizon scores as visual percentile
meters, preserving the numeric labels, separate contender/rebuilder fit row,
transition deltas, and evidence drawer. Missing scores render as unavailable;
they are never silently turned into zero. The homepage desk shelf now exposes
all six registered publication desks, including the Market Clock Morgan read,
so the new analysis has a reader entry path.

The local validator also checks score range, clock coverage, transition
arithmetic, model version, score basis, and value-lane vocabulary. This is a
structural trust gate, not a claim that the horizon percentiles are outcome-
calibrated forecasts. Calibration remains a separate future slice requiring
dated snapshots and realized outcomes.
## 2026-08-26 horizon feedback foundation

The horizon layer now has a path to learn from realized results. Each refresh
preserves the current deterministic comparison in an idempotent
`horizon_snapshot_history.csv`; later refreshes derive
`horizon_score_accuracy.csv` for next-game and active rest-of-season outcomes
when the Sleeper-named player can be joined unambiguously to nflverse usage.
The browser and trust gate expose the cold-start state instead of implying
calibration. Dynasty, career-window, and contender/rebuilder fit remain
separate decision constructs until a longitudinal outcome contract exists.

## 2026-08-26 horizon repricing-lead checkpoint

The horizon layer now also shows each decision clock against the current
same-position market percentile: next-game minus market, rest-of-season minus
market, dynasty minus market, and career-window minus market. This gives the
newsroom a precise way to look for a player's utility moving ahead of or behind
the market without calling that difference a dollar price or a proven
mispricing. The canonical market value remains the cross-position price anchor;
missing endpoint evidence stays unavailable. The validator reconciles these
deltas, and the Trade Desk, Market Clock Morgan packet, fallback article, and
front-page market read consume them from the canonical horizon row.

## 2026-08-26 four-window repricing publication checkpoint

The live naming now matches the actual model: next game, rest of season,
dynasty market, and the separate five-year career-window scenario are presented
as a Four-Window Market Read. The deterministic fallback adds a Market vs Clock
section that selects the largest positive and negative same-position deltas per
position, while the Trade Desk adds disagreement sorting and a visible four-cell
repricing grid. These are discovery leads layered over the hard data; they do
not create a universal player rank, dollar price, or proof of mispricing.

## 2026-08-26 counterparty repricing bridge

The counterparty workflow now carries the canonical four-window scores,
clock-minus-market deltas, transition deltas, and largest same-position
disagreement window into both target-owned trade edges and possible audiences
for our owned assets. Trade theses, manager dossier fit cards, and the Trade
Desk packet can therefore answer two separate questions together: which team
has the stronger timeline fit, and which time window is leading or lagging the
current market percentile. The existing trade and conversation scores remain
unchanged; copied horizon context is validated against the canonical horizon
table and missing joins stay unavailable.

## 2026-08-26 personalized horizon fit amendment

The four horizon scores remain the shared deterministic instrument, while each
private league may optionally set `strategy_profile.horizon_fit_weights` for
its contender and rebuilder lenses. Values are normalized and malformed lanes
fall back to the documented defaults with an explicit fit receipt. This lets a
manager decide how much urgency, current-season production, dynasty runway, or
career-window scenario should influence the fit read without creating a new
market score or changing the underlying evidence. The profile editor exposes
the setting, and profile updates merge private strategy JSON so an edit cannot
erase core holds or tracked picks. The scheduler/user refresh path also carries
private manager-trade profiles into the same scoped context used by the
app-triggered refresh.

## 2026-08-26 strategy receipt entry-path amendment

The private horizon fit is now visible on the My Team strategy panel, including
the active contender/rebuilder/balanced lens, the number of roster horizon rows,
the resolved weighting profile, and the deterministic `fit_basis` receipt. A
player evidence chain now carries all four canonical horizons plus contender and
rebuilder fit scores, so the reader can follow the same decision model from a
team-level strategy setting to an individual player page. This is presentation
and traceability over the existing evidence model; it does not create a second
score or imply that a fit lens is a forecast.

## 2026-08-26 current-availability provenance amendment

The normalization path now treats Sleeper player-cache availability as
current-state metadata. `roster_players` emits an explicit
`availability_scope`: `current_season_snapshot` for the configured current
season and `historical_unavailable` for older or boundary-less rows. Historical
injury fields are blank rather than inheriting today's status, preventing a
current injury flag from becoming false evidence in multi-season manager or
player dossiers. This corrects provenance without pretending that a current
status supplies a recovery timeline or recovery-adjusted rest-of-season
projection.

## 2026-08-26 availability receipt follow-through

The same `availability_scope` receipt now travels into `player_dossiers` and
`player_horizon_market_scores`, then appears in the player table, player page,
and horizon evidence card. A reader can distinguish a current Sleeper snapshot
from intentionally unavailable historical status without inspecting a raw CSV.
This is provenance only: it does not turn a current injury flag into a
recovery timeline or change any horizon score.

## 2026-08-26 market-quality receipt follow-through

The hard-data boundary now carries the canonical market consensus receipt into
the four-window rows: source count, component disagreement, and consensus
confidence. The same values appear in horizon snapshots, writer evidence, the
Trade Desk, and player pages. This lets the newsroom distinguish a real
clock-versus-market research lead from a thin or divided price anchor without
creating a second valuation formula or silently rescaling a horizon score.
## Horizon markets: decision instrument and media layer

The three requested market questions are separate deterministic instruments:
next game, rest of season, and dynasty/career horizon. Their deltas are not
another price model; they explain where urgency, season production, or dynasty
patience changes the audience for an asset. Contender and rebuilder fit are
personalized combinations of those canonical lanes.

The newsroom should use those fields to produce distinct stories—weekly
lineup/market context, season planning, and dynasty repricing—without
regenerating duplicate articles when the evidence fingerprint is unchanged.
Each story must keep the hard-data receipt one click away. The public read is
therefore short and decision-led, while the full player cohort, conditional
PPG baseline, injury provenance, market-source quality, transition deltas, and
source traces remain queryable in the data room.

## 2026-08-26 data relevance and editor checkpoint

The data room now makes relevance a first-class input rather than forcing each
writer to infer it from a mixed historical/current bundle. Current Sleeper
availability is separated from historical production: a player with no current
NFL team may retain historical evidence, but the weekly and rest-of-season
actionable scores are unavailable and the baseline is labeled conditional on
signing. The next-game, season, and dynasty/career desks therefore receive the
same canonical packet with different declared questions, not different facts.

The newsroom also now supports bounded peer and previous-edition context. This
is editorial context only, is excluded from evidence receipts, and exists to
create useful disagreement and continuity between voices. A deterministic desk
editor reviews every candidate for required story fields and evidence/source
receipts before it reaches the printed facade. Held articles remain inspectable
in the publication receipt but do not display unsupported copy or actions.

## 2026-08-26 decision-view presentation slice

The Four-Window Market Board now has focused views for All Clocks, This Week,
Rest of Season, Dynasty/Career, Contender vs Rebuilder, and Repricing Leads.
Changing the view changes the default sort and the amount of card copy shown;
it does not create or recompute a score. This makes each market number useful
as its own decision instrument while keeping the shared evidence packet and
position-relative comparison boundary intact. The full card and evidence
drawer remain available when the manager wants the complete read.

## 2026-08-26 inspectable writer generation plan

The operator now exposes a protected, read-only writer generation plan before
the cost-incurring action. It runs the real desk scopes and compares each
desk's evidence fingerprint, content hash, reporter, writer mode, and
configured model to its current publication receipt. The plan reports whether
each desk will generate, reuse, keep its deterministic fallback, or is blocked
by missing evidence or a missing provider key. It makes the expected Luna
work visible without making a provider request, and the eventual writer run
continues to use the same predicate rather than a second planning model.

## 2026-08-26 writer identity seam correction

The horizon publication scope now enforces `league_id` in addition to season.
This closes a multi-league entry-path risk in which a correct-looking
four-window article could have received another league's identified rows from
the same processed workspace. The correction is covered by a cross-league
adversarial scope test; blank legacy league IDs remain allowed only where the
row itself does not claim a conflicting league.

## 2026-08-26 horizon movement receipt follow-through

The four-window scores now have a dated reader-facing change seam. Each refresh
compares the current row with the latest genuinely earlier snapshot in the same
league, season, roster, player, position, and model scope and writes
`horizon_market_movements.csv`. Same-week reruns and first-run baselines remain
empty; missing endpoints stay unavailable. The newsroom uses changed rows to
explain what moved, while preserving the rule that a movement receipt is not a
fifth score, a dollar price, or proof of mispricing.

## 2026-08-26 current-news scope correction

Current RotoWire and Sleeper-trending events are now attached only to
current-season ownership in the league-impact table. The previous join could
fan a current event into every historical season in which a player appeared,
which made a correct event look like repeated news and weakened the historical
evidence boundary. The change preserves multi-league current-season coverage,
keeps blank legacy rows explicitly unscoped, and is protected by an adversarial
current-versus-completed-season test.

## 2026-08-26 identity fallback correction

The presentation audit found two last-mile identity fallbacks that could undo
the source-of-truth work: a missing manager roster match selected the first
manager row, and a missing team dossier match selected all players. Both paths
now fail closed to an empty or quiet read, and team-report evidence is
intersected with the exact scoped `roster_players` player IDs before it reaches
the writer. Cross-roster and cross-league entry-path tests protect the seam.

## 2026-08-26 desk editor repair pass

The newsroom now has an optional explicit Luna editor pass after each writer
draft. `FRONT_OFFICE_EDITOR_MODE=llm` is the paid opt-in; deterministic review
remains mandatory in every mode. The editor receives the same selected,
validated evidence packet plus bounded draft context and must approve, return a
complete evidence-cited repair, or hold the article. Persisted review receipts
survive markdown reload and browser bundling, so a held article cannot be
printed accidentally and a revised article is labeled as revised. Held
sections are also excluded from the daily brief's peer context. This closes the
editorial quality seam without allowing an LLM to become a source of facts,
scores, manager motives, or transactions.

## 2026-08-26 writer-plan parity repair

The protected writer preview and the paid workflow now share a stable article
reuse key. Peer and previous-edition prose remains available to a writer as
bounded editorial context, but it is not part of the evidence fingerprint:
newly generated peer prose cannot be known by a no-cost plan and cannot cause a
false regeneration cascade across the newsroom. The fingerprint still changes
for the article's selected evidence, league/roster scope, prompt, reporter,
model, and editor mode. An entry-path test generates the multi-desk issue and
then proves the preview reports reuse for every unchanged desk.

## 2026-08-26 bounded newsroom packets and scoped retries

The first real Luna run exposed an operational seam rather than a content
problem: the manager dossier and trade packets carried raw transaction and
counterparty histories into the provider request, making a single desk more
likely to hit rate limits and harder to retry safely. The durable dossiers stay
complete in the data room, while writer packets now carry bounded aggregates,
recent history, leading fits, and explicit source traces. The workflow also
supports a targeted article retry, so a failed desk can be repaired without
regenerating approved articles or their editor receipts.

The authenticated identity recheck now has a bounded browser wait. A slow
Sleeper discovery cannot leave the control permanently stuck on “Checking”;
the saved verified identity remains visible and the manager gets a truthful
retry message while the server-side request completes or times out.

## 2026-08-26 projection baseline availability repair

The data audit found that the deterministic signals already withheld actionable
next-game and rest-of-season scores for players without a current NFL team,
but the projection contract and generic browser table still exposed their
historical PPG as an unlabeled current-looking number. Availability scope,
status, and note now travel through every projection source component, the
season consensus, and weekly allocation. The browser labels those values as
conditional on signing or active return, and the local trust gate requires the
availability columns. This keeps historical signal useful without letting it
masquerade as a present projection.

## 2026-08-26 Luna configuration alignment

The provider boundary now defaults the personal newsroom to OpenAI
`gpt-5.6-luna` with `reasoning.effort=max` when no explicit environment
override exists. The setting remains independently configurable and is
recorded in the writer preflight and article receipts, so a lower-cost run is
visible as a deliberate operating choice rather than an accidental model
downgrade.

## 2026-08-26 newsroom progress receipt amendment

The asynchronous newsroom now persists compact progress after each desk,
including the active reporter, completed/total desk count, configured model and
reasoning effort, and each completed desk state. The reader polls long enough
for a multi-call Luna run plus optional editor pass to finish. This improves
operational truthfulness without changing evidence, scores, article reuse, or
publication authority; the durable final article/editor receipts remain the
only proof that copy was printed.

## 2026-08-26 durable writer-run checkpoint repair

Authenticated production verification found that a prior writer action could
remain represented only by a recovered interruption after the process died,
with no per-desk checkpoint for the manager to diagnose. The writer seam now
records a run ID and explicit queued, refreshing, writing, publishing, and
terminal stages; refresh and bundle wrappers emit their own safe checkpoints;
and terminal failures carry forward the last model, timeout, active desk, and
per-desk states. The provider timeout is configurable but bounded, and both
browser writer controls watch long enough for the complete six-desk workflow.
This is an operational prerequisite for the protected Luna publication, not
proof that a paid run has completed; publication still requires the matching
reader manifest and article receipts.

## 2026-08-26 availability-null boundary repair

The local refresh exposed a second route to the old Hill/Mixon regression:
blank Sleeper team and injury cells were loaded by pandas as `NaN`, then the
shared availability helper read those sentinels as literal text. The result
was an invented injury flag instead of `no_current_nfl_team`, plus noisy
availability notes on healthy players. The boundary now normalizes CSV nulls
before classifying status. The economics ledger carries that status into its
asset-gap rows and excludes conditional no-team rows from the action preview.
The regenerated local evidence now shows Tyreek Hill and Joe Mixon as
conditional historical baselines, while Jayden Daniels remains available and
Jalen Nailor remains a low-production, market-rich watch rather than a top
asset.

## 2026-08-26 writer receipt reload checkpoint

The headquarters now renders the selected league's persisted writer-run
checkpoint after a page reload, including active desk progress and explicit
terminal interruption/failure language. User-scoped all-edition runs use the
aggregate receipt while they are active or terminal, because their work is
not owned by one selected league. This keeps a cost-incurring run visible
without treating an in-progress checkpoint as publication: the current
article/editor receipts and bundle revision remain the only proof that copy
was printed. A newer selected-league writer checkpoint takes precedence over
an older aggregate terminal receipt. The behavior is covered by
selected-league and all-edition entry-path tests and has passed the public
production smoke gate.

## 2026-08-26 writer request receipt binding

The browser writer control now binds its polling loop to the `run_id` returned
by the accepted operator request. If the durable status endpoint returns an
older receipt or no receipt after a short grace window, the control stops and
states that the request was not observed rather than leaving a stale “writer
started” message on screen. This keeps a paid action from being retried blindly
and makes a process restart, wrong scope, or storage failure visible at the
entry path. The server response and durable receipt are covered by an
adversarial contract test; this does not claim that a provider call completed.

## 2026-08-26 publication receipt honesty checkpoint

The issue masthead previously summarized every indexed article artifact as an
“article receipt,” which could make six deterministic fallbacks look like six
LLM reports. The reader now separates current LLM articles, evidence-led
fallbacks, and held editor drafts in that summary while keeping the full
receipt drawer available. The change is presentation-only, but it preserves
the product rule that the media facade must never overstate the paid editorial
layer.


## 2026-08-26 signal identity checkpoint

The Signal Board team filters had retained a legacy name-based seam: breakout
rows matched `player_name`, and sell rows matched the fantasy team label. That
could reintroduce the wrong-team regression after a rename even though the
selected league and roster identity were correct underneath. The browser now
derives the active roster's exact `player_id` set from the scoped roster table
and uses it for breakout, sell, and projection-gap views. The entry-path test
also asserts that those team filters do not fall back to display names.

## 2026-08-26 opportunity-scope depth checkpoint

The opportunity layer was using global nflverse usage correctly but joining it
to the entire historical roster archive by normalized name. In a multi-league
workspace, that could make a player inherit the first historical roster ID or
team label encountered, and the Data Room's signal-disagreement question could
read the unscopeable table directly. The join now selects the current season
and selected league before attaching Sleeper identity, carries `league_id`
through the published table, and fails closed when the requested scope is not
present. The Data Room filters the disagreement view to the selected roster's
player IDs through the same current-league helper. This is a scope repair over
existing usage scores, not a new ranking formula.

## 2026-08-26 cross-position market-price view

The Four-Window Market Board now has a separate Market Price view that sorts by
the canonical cross-position `market_value` anchor. The view keeps the four
clock scores visible as secondary, position-relative percentiles and sends
unpriced rows to the bottom rather than letting missing values sort as leaders.
This gives the manager a direct answer to “who is actually priced higher?” while
preserving the separate questions of weekly utility, season value, dynasty
window, fit, and repricing. It does not create a fifth score or reinterpret a
clock percentile as a universal market ranking.

## 2026-08-26 manager dossier index correction

The Manager Room no longer uses the first 18 non-empty lines of
`manager_dossiers.md` as its dossier surface. That preview could make a deep
manager data set look sparse by hiding most managers. The browser now consumes
the structured `managerDossierItems` payload, renders one evidence summary per
roster, and links each summary to the exact `#team-{roster_id}` dossier route.
The fallback path shows the complete Markdown artifact only when the
structured payload is unavailable. This keeps the durable manager intelligence
reachable without spending another writer call.

## 2026-08-26 Manager Intel compact navigator

The deterministic Manager Intel fallback now acts as a newsroom entry point:
it previews five evidence-ranked dossiers with exact roster links and points
to the full manager index. This preserves the newspaper reading flow while
keeping the deep manager history reachable. Current LLM Manager Intel remains
the editorial surface when its article receipt is current.

## 2026-08-26 Sleeper identity-lineage receipt

The private reader bundle now carries the linked Sleeper user ID alongside the
exact league and roster receipt. This makes the full identity chain inspectable
after refresh or deployment while preserving the important boundary: the
Sleeper user establishes ownership, but `roster_id` selects the managed team.

The serving path also treats a bundle with a missing lineage field as stale
when the authenticated league row has a linked Sleeper user, so a deploy can
self-heal older durable artifacts before they reach the reader.

The Data Room diagnostics exposes those receipt fields to the signed-in
manager, turning identity continuity into a reader-visible check rather than
an internal-only contract.

## 2026-08-26 targeted writer retry entry path

The paid workflow had already accepted a set of article keys internally, but
the browser could only launch an entire selected-league or all-league run. The
protected operator seam now validates those keys, requires an owned league,
and forwards them to the evidence-backed workflow without changing the normal
full-edition behavior. When a terminal receipt names failed or held desks, the
Writer Desk renders `Retry failed desks`; when the worker stopped during a
known provider call, it can retry that current desk. Refresh-stage failures
remain full-retry only because there is no safe desk target to invent.

## 2026-08-26 selected-edition launch boundary

The selected-edition browser action now fails closed when its league selector
does not yield an exact `league_id`. An empty selector can no longer fall
through to the server's deliberately aggregate all-edition scope, and the UI
states that no writer request was sent. This preserves the paid-action and
identity boundaries while keeping aggregate generation explicit.

## 2026-08-26 authenticated shell revision receipt

The headquarters HTML now exposes the running source revision in a safe meta
tag and body data attribute. This makes an authenticated browser entry
inspectable when an already-open tab may be stale, while the edition manifest,
private bundle, and publication receipts remain the authoritative proof of
what content is served.
