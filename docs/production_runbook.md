# Fantasy Dominator production runbook

This runbook is for the private Railway deployment. It is intentionally
verification-oriented: a successful build or `/healthz` response alone does
not prove that the personal headquarters is connected to the right identity or
that its data will survive a restart.

## Required production configuration

Keep values in Railway variables or a local secret store; never commit them.

- `FRONT_OFFICE_DATA_DIR=/app/data`, backed by a durable Railway volume.
- Live Clerk issuer/JWKS/publishable-key configuration, or the explicitly
  private development-auth exception documented in `README.md`.
- `FRONT_OFFICE_PUBLIC_URL` set to the canonical HTTPS origin when Railway’s
  public-domain fallback is insufficient.
- `FRONT_OFFICE_OPERATOR_TOKEN` for protected refresh, writer, and rebuild
  actions.
- `FRONT_OFFICE_SCHEDULER=on` only when scheduled per-user refresh is desired.
- `FRONT_OFFICE_REFRESH_MODE` is optional: use `bootstrap` for first league setup
  and historical backfill; recurring jobs default to the existing-edition
  `maintenance` path when they call the user-scoped refresh workflow.
- `FRONT_OFFICE_MAINTENANCE_WEEK_END` is an optional bounded override for the
  maintenance window. Without it, the run uses Sleeper's current league leg
  when available and otherwise fails closed at zero requested weeks rather
  than treating future placeholder matchups as evidence.
- `OPENAI_API_KEY` and `FRONT_OFFICE_LLM_PROVIDER=openai` for writer actions.
- `FRONT_OFFICE_LLM_MODEL=gpt-5.6-luna`.
- `FRONT_OFFICE_LLM_REASONING_EFFORT` defaults to `max` for the personal
  newsroom; set it explicitly when a lower-cost or lower-latency maintenance
  run is intentionally desired.
- `FRONT_OFFICE_LLM_REASONING_EFFORT_<ARTICLE_KEY>` optionally overrides the
  global effort for one desk, using the article key uppercased with non-word
  characters replaced by underscores (for example,
  `FRONT_OFFICE_LLM_REASONING_EFFORT_MARKET_WATCH=medium`). The selected value
  is written to the desk receipt and a change invalidates reuse of a prior
  article generated at a different effort.
- `FRONT_OFFICE_LLM_TIMEOUT_SECONDS` is optional and defaults to `120`; it is
  bounded to 30-300 seconds per structured provider request so Luna/max has
  time to finish without creating an unbounded job.
- `FRONT_OFFICE_EDITOR_MODE` is optional and defaults to `deterministic`; set it
  to `llm` for a paid Luna desk-editor pass after each writer draft. The active
  mode is exposed in `/healthz`, the Writer Desk, and the operator receipt so a
  run cannot be mistaken for having received an LLM edit.
- `FRONT_OFFICE_EXECUTION_MODE` defaults to `inline` for local iteration. Set it
  to `worker` only after a separate Railway worker service is attached to the
  same durable database and private data root. In worker mode, the API returns
  a durable queued receipt immediately; it does not hold the web request open
  for refreshes or Luna calls.
- Worker service variables: `FRONT_OFFICE_WORKER_ID` must be unique per worker,
  `FRONT_OFFICE_WORKER_POLL_SECONDS` defaults to `5`,
  `FRONT_OFFICE_WORKER_LEASE_SECONDS` defaults to `900`,
  `FRONT_OFFICE_WRITER_CONCURRENCY` defaults to `3` and is capped at `3`, and
  `FRONT_OFFICE_MAX_ATTEMPTS` defaults to `2`. Run the worker service with:

  ```powershell
  python scripts\newsroom_worker.py
  ```

  The web service and worker must resolve the same `FRONT_OFFICE_DATA_DIR` and
  database file. The current SQLite design is a single-owner production
  boundary: run one worker until shared-volume locking and restart behavior
  have been proven. A second worker is not a substitute for a durable queue.
  `/healthz` reports `worker_service_configured` when the queue mode and schema
  are present, but reports `worker_queue_ready` only after a recent worker
  heartbeat. This prevents a web service from claiming that queued paid work
  is being processed merely because its database exists.

Each authenticated newsroom run also writes an additive `edition_runs` receipt,
one or more `edition_jobs` rows, and a `publication_edges` graph in the same
durable database. These rows
contain stage, state, attempt, evidence fingerprint, model, a stable internal
client request ID, the provider request ID when returned, usage, and timing
metadata, but never prompts, secrets, or article bodies. The client ID is a
trace correlation value, not a provider idempotency guarantee. If Railway
restarts a daemon worker, the JSON receipt is recovered as interrupted and the
durable ledger remains available to explain which desks can be safely retried.
The run also freezes `analysis/edition_runs/<run_id>.json` with the exact
league/roster scope, freshness receipt, Reality Check summary, and hashes of
the named processed/analysis inputs. `analysis/edition_packet.json` is only a
latest-edition reader pointer; the run-scoped packet is the immutable resume
receipt. If those inputs change, the run is held and a new edition must be
started rather than mixing snapshots.

Use the authenticated `POST /api/operator/resume-edition` action with the
existing `league_id` and `run_id` to continue a non-terminal run. Resume is
same-run and ledger-driven: it does not create a new run, does not rerun
completed desks, and skips a second refresh once durable article jobs exist.
Because this action can spend on Luna, process startup only reconciles the
interrupted state; it does not silently resume paid work without an explicit
operator action.

The durable ledger now carries additive run/job leases. The worker claims the
run with a unique worker ID, heartbeats it, and claims each desk phase before
spending a provider request; a live unexpired lease is exclusive, while an
expired lease is resumable. Cancellation is cooperative for an active call,
and retry exhaustion becomes an explicit dead-letter state rather than an
infinite paid loop. This is still a single-owner SQLite deployment boundary:
keep one worker until shared storage semantics are proven.

The model slug and reasoning setting are separate. `max` is a reasoning-effort
value, not a model name. Anthropic remains a compatibility option during
migration when explicitly configured.

OpenAI writer requests also carry a privacy-safe scope cache key and hashed
user safety identifier. The key is an optimization hint, not proof that a
provider cache hit occurred; inspect `cached_tokens` in the per-job execution
receipt to measure actual reuse. Prompt text, evidence payloads, and secrets
are not persisted in these receipts.

## Deploy verification

1. Deploy the intended commit to Railway.
2. Confirm `/healthz` reports the expected revision, auth readiness, public URL
   readiness, durable data-root configuration, SQLite readiness, and writer
   configuration without exposing secrets.
3. Run the public and authenticated smoke checks from a trusted local session:

   ```powershell
   $env:FRONT_OFFICE_EXPECTED_REVISION = "<commit deployed to Railway>"
   $env:FRONT_OFFICE_EXPECTED_EDITOR_MODE = "llm" # only for a paid Luna editor run
   python scripts\smoke_live.py
   ```

   Set `FRONT_OFFICE_SESSION_TOKEN` for the deployment gate; without it the
   command fails closed rather than claiming production is verified. For an
   intentional public-only diagnostic, set `FRONT_OFFICE_PUBLIC_ONLY=1` and
   record that the private check was not done. Set
   `FRONT_OFFICE_OPERATOR_TOKEN` locally only when checking the safe operator
   storage audit. Never paste either token into Git, an issue, or a chat log.

   When a session token is supplied, the smoke also checks every owned
   edition's `data/app_bundle.json` and `data/manifest.json` for the expected
   deployment revision, league ID, and verified exact `roster_id`. A 200 HTML
   response alone is not an authenticated production proof.

4. In a real browser, log in and verify the complete continuity path:
   current Clerk user → linked Sleeper user → league → exact managed roster.
   Refresh the page and repeat after logout/login. Confirm that the selected
   team name, roster ID receipt, strategy profile, articles, and dossiers all
   belong to the same league/team. The generated HTML and JSON bundle should
   be `no-store`; if an already-open tab still shows the prior shell, perform
   one clean reload and treat a missing expected shell marker as a deployment
   verification failure rather than trusting the server revision alone.
5. Trigger a writer action only after source freshness and identity are green.
   Confirm the receipt records the selected reporter, provider, model, and
   reasoning effort. Once accepted, do not deploy or restart the Railway
   service until the writer status is terminal: a newsroom run spans refresh,
   six desk calls, optional editor calls, and bundle publication. A service
   restart during that window will recover the durable checkpoint as
   interrupted and no article should be treated as published; a status read by
   another live worker will preserve the running receipt instead of calling it
   interrupted. Retry on the stable revision only after the owner is actually
   gone and the receipt is terminal. If the run has durable jobs, use the visible
   **Resume this edition** control rather than starting a fresh edition.

   A terminal writer receipt is still not proof that paid copy was printed.
   For the post-run acceptance check, set
   `FRONT_OFFICE_REQUIRE_LLM_PUBLICATION=1` and
   `FRONT_OFFICE_EXPECTED_WRITER_MODEL=gpt-5.6-luna` alongside the expected
   revision and authenticated session token before running
   `scripts\smoke_live.py`. That
   stricter mode requires all six registered desks to be automatic LLM output,
   approved for publication, and attributed to a named assigned reporter. The
   ordinary smoke remains fallback-tolerant so provider degradation is visible
   without making the reader unavailable.

Before comparing a prompt, model, effort, or reporter-roster change, run the
local deterministic scorecard against the frozen regression pack:

```powershell
python scripts\evaluate_newsroom.py --fixture tests\fixtures\newsroom_eval\reference.json
python scripts\evaluate_newsroom.py --analysis-dir data\analysis
```

The first command is the comparable evaluation surface. The second is an
artifact audit: it reports `not_scored` when the published bundle does not
carry the complete writer packet, rather than treating article citations as
independent proof. Do not turn `not_scored` into a passing quality claim.

## Data lifecycle

The data room has two intentionally different build paths:

- **Bootstrap** assembles the configured league plus discovered historical
  leagues, their configured transaction/matchup weeks, raw caches, normalized
  facts, derived analytics, and the browser bundle. The current season is
  bounded by Sleeper's observable leg; it is the first setup or a deliberate
  historical repair operation.
- **Maintenance** refreshes the current league and bounded current-season week
  range, then merges those canonical source rows into the prior snapshot by
  exact source keys. Derived analytics and the browser bundle are rebuilt from
  that merged evidence. Historical rows are preserved even when the current
  maintenance window is narrower.

Every refresh writes `refresh_metadata.refresh_mode`,
`requested_week_end`, and `historical_refresh_scope`. A maintenance run is not
allowed to imply that omitted historical rows were re-fetched. If a first
edition has no prior canonical snapshot, the user-scoped workflow selects
bootstrap automatically; otherwise it selects maintenance.

## Local trust gate

Before deployment or handoff, run:

```powershell
python -m unittest discover -s tests -p "test*.py"
python scripts\validate_local_data.py
git diff --check
```

The local data audit checks processed schemas, source traces, duplicate IDs,
news freshness, and deterministic analysis validity. Treat warnings as part of
the product state. For example, a disabled optional source or an old refresh
must be visible rather than silently described as current.

## Recovery rules

- If a refresh fails, keep serving the last complete edition with its receipt;
  do not replace the page with an empty shell or raw `league file not found`
  response.
- If the current identity cannot be matched to a preserved workspace, stop
  personalized actions and inspect Clerk subject, linked Sleeper account,
  `FRONT_OFFICE_DATA_DIR`, and the storage audit. Do not “fix” this by copying
  another user’s league bundle.
- If the live revision is wrong, redeploy or correct the Railway service before
  diagnosing application behavior. A local fix is not live until `/healthz`
  proves the revision.
- If a provider or source is unavailable, keep deterministic data available,
  mark the affected interpretation limited, and avoid fabricating content.
- Never delete the durable `/app/data` volume as a first recovery step.

## What production-ready means

Production-ready means all of these are true at the same time:

- the intended revision is live;
- Clerk authentication is configured for the intended privacy mode;
- `/app/data` is durable and the current identity can see its preserved rows;
- the exact roster identity is verified for every personalized edition;
- local trust checks pass and freshness warnings are understood;
- browser verification confirms the real logged-in workflow;
- generated content is labeled with its evidence, reporter, and model receipt.
