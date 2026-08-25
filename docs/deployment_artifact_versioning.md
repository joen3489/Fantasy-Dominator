# Deployment artifact versioning

Updated: 2026-08-25

## The failure mode

Railway can report the intended source commit while a durable `/app/data`
volume continues serving an older generated `index.html` and JavaScript
bundle. A healthy service and a correct Git SHA do not prove that the rendered
entry path was rebuilt.

This occurred because startup intentionally skipped refresh when an existing
site was present. The generated browser bundle had a content revision, but no
relationship to the source revision that produced its HTML and JavaScript.

## The rule

Treat the deployed source and the generated reader artifact as separate
runtime effects:

- `sourceRevision` identifies the code release that generated the shell.
- `bundleRevision` identifies the content/publication payload and its receipts.
- Authenticated league serving must compare `sourceRevision` with the running
  deployment SHA and rebuild a stale persisted shell before serving it. It
  should use preserved processed facts when available, or rebuild only the
  HTML/JavaScript shell from a complete preserved bundle when intermediates
  are absent.
- A code rebuild must not be represented as regenerated article content or
  trigger an unnecessary LLM call.

## Verification

The deployment gate must prove all three layers independently:

1. local tests and data trust checks pass;
2. `/healthz` reports the expected source SHA; and
3. a signed-in browser renders the expected entry path after stale-bundle
   invalidation, including the current identity receipt and visible UI marker.

This is an anti-recursive guardrail: a passing source-level test or a healthy
process is not proof that the durable artifact users actually see is current.
