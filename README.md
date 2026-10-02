# VigilWatch

Serverless uptime monitoring that runs entirely inside the AWS always-free tier.

## The "Why" Before the "How"

Teams often find out about outages from their users. Commercial monitoring is
either expensive or heavy to operate for a small team. VigilWatch asks a narrow
question: how much real monitoring (scheduled checks, history, incidents,
alerts and a live dashboard) can you get from managed AWS services while
paying nothing and running no servers?

It is an exercise in engineering trade-offs, Infrastructure as Code and
production habits (tests at every layer, least privilege, gated deploys),
not a tour of AWS services.

## What it does

- Checks every registered URL every 5 minutes (HTTP GET, 5 s timeout, no redirects followed).
- Classifies each check as `UP`, `DEGRADED` (correct status but slower than 1 s) or `DOWN`.
- Keeps 48 h of raw checks and 30 days of daily rollups and incidents.
- Opens an incident and emails once after 2 consecutive `DOWN` checks, and emails again on recovery.
- Serves a dashboard with current status, 30-day uptime, a latency trend and incident history.
- Alarms on the monitor itself: checker errors, checker not running, dead-lettered runs, API 5xx.

## Architecture

```text
Browser ── HTTPS ──> CloudFront ──(OAC)──> S3 (index.html, view.js, app.js, config.js)
   │
   └── HTTPS ──> API Gateway HTTP API (throttled, CORS = dashboard origin)
                   ├── POST /register ──> Lambda register_endpoint ─┐
                   └── GET  /checks   ──> Lambda get_checks ────────┤
                                                                    v
EventBridge rate(5 minutes) ──> Lambda uptime_check ──> DynamoDB (endpoints, history)
                                   │      │
                                   │      └──> SNS ──> email (DOWN / RECOVERED)
                                   └── on failure ──> SQS dead-letter queue

CloudWatch: logs (14 days), EMF metrics, 4 alarms ──> SNS
```

More detail: [docs/README.md](docs/README.md). Operations: [docs/RUNBOOK.md](docs/RUNBOOK.md).
Decisions: [docs/adr/](docs/adr/).

## Why these technologies?

| Technology | Reasoning |
|---|---|
| Lambda (python3.12, arm64) | No servers; arm64 is cheaper per GB-second; stdlib-only code means no dependency packaging |
| DynamoDB (provisioned 5/5 per table) | Key-value access patterns; provisioned capacity is covered by the always-free tier, on-demand is not ([ADR 0002](docs/adr/0002-provisioned-dynamodb-with-rollups.md)) |
| API Gateway HTTP API | Cheaper than REST APIs, built-in CORS and throttling ([ADR 0001](docs/adr/0001-http-api-over-rest-api.md)) |
| EventBridge | Managed schedule, no cron host |
| SNS email | Free for the first 1,000 emails a month |
| CloudFront + private S3 | HTTPS, security headers and caching for a static dashboard; 1 TB/month free |
| Terraform (>= 1.10) | Reproducible infrastructure, remote state with native S3 locking, `terraform test` with a mocked provider |

## Engineering trade-offs

- **No authentication.** The dashboard is a public demo. Instead of auth, the API is throttled (5 rps),
  monitored URLs are capped at 10, and every URL passes an SSRF guard (http/https only, no
  private, loopback, link-local or metadata addresses, re-checked before every probe, redirects
  not followed). See [ADR 0004](docs/adr/0004-zero-cost-security-tradeoffs.md).
- **Provisioned DynamoDB.** It is free but can throttle under bursts. Daily rollups keep the
  30-day uptime query at no more than 30 items, so normal use stays far below capacity.
- **Low-cardinality metrics.** Metrics are emitted with Embedded Metric Format and a single
  `Service` dimension, so the number of custom metrics stays fixed however many URLs are monitored
  ([ADR 0003](docs/adr/0003-emf-metrics-without-per-endpoint-dimensions.md)).
- **One region, one probe location.** A check from one region cannot tell "site down" from
  "network path down"; multi-region probing costs more and is out of scope.
- **Cold starts** add latency to the first API call after idle time; the checker is not user-facing.

## Cost

| Service | Monthly usage at defaults | Always-free allowance |
|---|---|---|
| Lambda | ~9k checker runs + API calls, 128 MB | 1M requests, 400k GB-s |
| DynamoDB | 2 tables x 5 RCU/5 WCU provisioned | 25 RCU, 25 WCU, 25 GB |
| CloudWatch | 4 custom metrics, 4 alarms, logs kept 14 days | 10 metrics, 10 alarms, 5 GB logs |
| SNS | email alerts | 1,000 emails |
| SQS | DLQ, normally empty | 1M requests |
| CloudFront | dashboard traffic | 1 TB, 10M requests |
| API Gateway HTTP API | dashboard polling | 1M calls/month for the first 12 months, then $1.00 per million |
| S3 | a few KB of site files + Terraform state | 5 GB for the first 12 months, then cents |

The only line items that can exceed $0 after the first year are API Gateway and S3, and both
are bounded by throttling and tiny storage. Set up a zero-spend AWS Budget as a backstop
(see the runbook).

## Repository structure

```text
lambda/            Lambda handlers + common/ (status, SSRF guard, repository, checker, view)
terraform/         Main stack, terraform test suite (tests/), bootstrap/ for state + CI role
frontend/          Static dashboard (no build step) + node:test/jsdom tests
tests/             unit/, integration/ (moto), contract/ (API schema), e2e/ (post-deploy), policy tests
scripts/           local_api.py: dashboard + API locally with AWS mocked
docs/              Architecture, runbook, ADRs
.github/workflows  ci.yml (quality gates), deploy.yml (OIDC, plan -> approval -> apply)
```

## Running it

First-time setup (state bucket, CI role, migrating an older deployment) is in
[docs/RUNBOOK.md](docs/RUNBOOK.md). After bootstrap:

```bash
cd terraform
cp backend.hcl.example backend.hcl   # fill in the state bucket name
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan -var notification_email=you@example.com
terraform apply tfplan
terraform output dashboard_url
```

Pushing to `main` runs the same thing in GitHub Actions: CI, then a plan, then apply after a
reviewer approves the `production` environment.

## Testing

Every layer has tests, and every feature in this codebase was written test-first (red, then green).

| Layer | Tooling | Command |
|---|---|---|
| Unit (status, SSRF guard, probe) | pytest | `pytest tests/unit` |
| Integration (DynamoDB, SNS, handlers) | pytest + moto | `pytest tests/integration` |
| API contract (shared JSON Schema) | pytest + jsonschema, node:test | `pytest tests/contract` |
| Infrastructure | `terraform test` with a mocked AWS provider | `cd terraform && terraform init -backend=false && terraform test` |
| Frontend (rendering, XSS, config) | node:test + jsdom | `cd frontend && npm ci && npm test` |
| Pipeline and docs policy | pytest | `pytest tests/test_workflows.py tests/test_docs.py` |
| End-to-end smoke | pytest, against a live or local stack | `API_URL=... DASHBOARD_URL=... pytest -m e2e tests/e2e` |

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest --cov                                       # fails under 85% coverage
ruff check . && ruff format --check .
```

Run the whole thing locally with no AWS account (AWS is mocked, probes are real):

```bash
python scripts/local_api.py      # http://127.0.0.1:8787
```

## Lessons learned

- Infrastructure should be version controlled alongside application code, and so should its tests.
- Event-driven systems reduce operational work for scheduled jobs, but the schedule needs a
  target and a permission, and something should alarm when it stops firing.
- "Free" depends on details: on-demand vs provisioned capacity, metric dimensions, log retention.
- State files and build artifacts do not belong in git.

## Future improvements

- Authentication (Cognito) and per-user endpoints
- Multi-region probes to separate "site down" from "path down"
- Custom domain with ACM
- Status-page sharing and Slack/webhook alert channels
