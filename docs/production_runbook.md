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
- `OPENAI_API_KEY` and `FRONT_OFFICE_LLM_PROVIDER=openai` for writer actions.
- `FRONT_OFFICE_LLM_MODEL=gpt-5.6-luna`.
- `FRONT_OFFICE_LLM_REASONING_EFFORT` chosen per workload: normally `medium`,
  with `high`, `xhigh`, or `max` reserved for work where extra quality is
  worth the cost and latency.

The model slug and reasoning setting are separate. `max` is a reasoning-effort
value, not a model name. Anthropic remains a compatibility option during
migration when explicitly configured.

## Deploy verification

1. Deploy the intended commit to Railway.
2. Confirm `/healthz` reports the expected revision, auth readiness, public URL
   readiness, durable data-root configuration, SQLite readiness, and writer
   configuration without exposing secrets.
3. Run the public and authenticated smoke checks from a trusted local session:

   ```powershell
   $env:FRONT_OFFICE_EXPECTED_REVISION = "<commit deployed to Railway>"
   python scripts\smoke_live.py
   ```

   Set `FRONT_OFFICE_SESSION_TOKEN` when checking the authenticated home page,
   continuity receipt, and owned league editions. Set
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
   reasoning effort.

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
