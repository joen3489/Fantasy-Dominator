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
