# AGENTS.md

Slack app that unfurls X/Twitter links via xAI Grok. Two FastAPI services on GCP Cloud Run: `webhook_app` (Slack events → Pub/Sub) and `worker_app` (Pub/Sub push → xAI → `chat.unfurl`). Read `README.md` for layout and `docs/ARCHITECTURE.md` for design.

## Merging to `main` deploys to production

`.github/workflows/deploy-gcp.yml` builds and deploys both services to the live GCP project on every push to `main`. Pull requests run only the test job.

- Merging code is a production release; merge it only when a release is intended.
- For changes that need no release (docs, repo housekeeping), put `[skip ci]` in the merge commit title (squash merge) so the push skips the workflow. PR checks still run first.

## Local work

Work in the primary checkout on ordinary branches off `main`. `just` lists the recipes; `just check` is the CI-equivalent gate (ruff format, ruff lint, mypy, pytest). `just install` syncs deps with `uv`.

Tests mock Slack, xAI and Pub/Sub, and `tests/conftest.py` sets `TESTING=1`, so they need no `.env` and make no paid calls.

Running the services (`just run-webhook`, `just run-worker`) needs env vars exported in the shell. Nothing loads `.env` automatically, and the webhook refuses to start without `SLACK_SIGNING_SECRET`. Dummy values are enough to boot and hit `/health` and `/health/ready`:

```bash
export SLACK_BOT_TOKEN=xoxb-dummy SLACK_SIGNING_SECRET=dummy XAI_API_KEY=dummy PUBSUB_PROJECT=dummy PUBSUB_TOPIC=dummy
```

Real credentials only matter once a request reaches `/slack/events` (signature-checked) or `/pubsub`; with real keys those calls hit paid xAI inference and the live Slack workspace.
