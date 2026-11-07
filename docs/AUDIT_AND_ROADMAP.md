# VigilWatch: audit, gap analysis and roadmap

Date: 2026-10-23. Audited commit: `c3f7201` (PR #4, open and unmerged; `main` is still `4663a23`).
Method: the principles in `DevOps_Engineer_Agent.md`, the senior-devops skill (IaC, CI/CD, deployment
strategy, monitoring, anti-patterns), and a point-by-point comparison with the review notes.

## Evidence legend

Every claim below carries one tag, and the roadmap keeps the same rule: **a result is only written into
the repo's docs after it was actually produced.** Anything tagged `NEEDS-AWS` stays a documented
procedure plus an empty results template until it is run. Numbers that were never measured are not
published, because a reviewer who probes one invented figure will distrust the rest.

| Tag | Meaning |
|---|---|
| `CI` | Passed in GitHub Actions on a clean checkout of the audited commit |
| `MOCK` | Proven only against moto or a mocked Terraform provider |
| `REPO` | Observed by reading the tracked files |
| `NEEDS-AWS` | Cannot be proven without an AWS account |

## 1. Where things stand

- `main` still has every problem listed in the review notes. The fixes exist only on PR #4
  (30 commits ahead, 0 behind). **Nothing is visible to a reviewer until it merges.**
- All four CI jobs pass on the PR head (`CI`): Python (191 tests, 93.9% coverage), Terraform
  (fmt, validate, 10 `terraform test` runs, tflint), frontend (10 tests), security (gitleaks, trivy).
- Nothing has been applied to AWS. Every runtime claim is `MOCK` or `NEEDS-AWS`.
- This machine no longer has Python 3.12 or Terraform installed (the venv's base interpreter is gone;
  `terraform` is not on PATH). CI is therefore the source of truth for this audit. Restoring the
  toolchain is task 0.1.

## 2. The review notes, point by point

### Inconsistencies

| # | Note | On `main` | On PR #4 | Remaining work |
|---|---|---|---|---|
| 1 | README contradicts itself on automation | Confirmed: "automated deployment" claimed (line 91) while "GitHub Actions quality gates" is listed as future (line 87) | Resolved `REPO`: Production Readiness section removed, gates listed under structure, workflows exist and pass `CI` | README subtitle still says "always-free tier"; API Gateway's free tier is 12 months only (the cost table says so, the subtitle does not). Reword. Add CI and coverage badges |
| 2 | Layout does not match README | Confirmed: root `api_gateway.tf` and `outputs.tf` | Resolved `REPO`: no root `.tf` files, one `terraform/` directory. A clean checkout passes fmt, validate and `terraform test` in CI `CI` | The README's *Running* steps use `terraform init -backend-config=backend.hcl`, which needs the bootstrap bucket. That path is `NEEDS-AWS`. Add a "no AWS needed" quick start (local stack and tests) so a newcomer gets a working result in two commands |
| 3 | Trade-offs and lessons are generic | Confirmed | Partly resolved `REPO`: cardinality, provisioned DynamoDB, EMF and security trade-offs are in ADRs 0001 to 0004. README still has the generic "cold starts add latency" line (line 71) and generic lessons | **Cold start: no measurement exists in the repo.** The note refers to a figure in your CV; I have not seen its method or data, so I will not invent or copy it. Provide it (decision D4) or measure it (task 1.3, `NEEDS-AWS`). **Cardinality vs cost:** the reasoning exists, a computed mapping does not. Task 1.2 adds a tested calculator |

### Improvements

| # | Note | Status on PR #4 | Gap | Roadmap task |
|---|---|---|---|---|
| 1 | Remote state and environments | Partly. S3 backend with native lockfile, bootstrap stack (`REPO`, validated in `CI`) | One state key (`prod.tfstate`), no dev/prod separation, no guard against applying to the wrong account | 2.1, 2.2 |
| 2 | OIDC pipeline: fmt/validate/plan on PRs, apply on merge | Mostly. OIDC, fmt, validate, `terraform test`, tflint, trivy, gitleaks, saved plan, approval gate (`CI`) | **No `terraform plan` on pull requests** (plan runs only after merge). No drift detection. No rollback workflow. No changelog | 3.1 to 3.4 |
| 3 | Modules | Not started. One root, `for_each` over Lambdas | Split into `data`, `compute`, `api`, `frontend`, `monitoring` | 2.1 |
| 4 | Resilience: DLQ, PITR, checker alarm, `resilience.md`, tested restore | Partly. SQS DLQ plus `checker-errors`, `checker-not-running`, `checker-dlq` alarms exist (`MOCK`) | **No PITR. No `docs/resilience.md`. No restore drill.** ADR 0002 also records "no PITR" as deliberate, which now contradicts the goal | 5.1 to 5.6 |
| 5 | Make the checker honest | Not started | A DOWN result is believed even when the checker itself has lost connectivity. No control probes, no "inconclusive" state | 4.1 to 4.4 |
| 6 | Authentication | Not started (ADR 0004 records this as an accepted risk) | No identity on `POST /register` or `GET /checks`. HTTP API has no usage plans, so "API key with a usage plan" would mean going back to REST (reverses ADR 0001) | 6.1 to 6.5 (decision D1) |
| 7 | Alert quality | **Done** (`MOCK`): alert after N consecutive failures (default 2), one DOWN alert per incident, RECOVERED alert, a test for each | Optional: flap damping and a reminder re-alert for long incidents | 4.5 |

## 3. Audit against the DevOps Engineer Agent principles

Scope note: the agent file is written for a different programme (named AWS accounts, SES, WordPress,
Bedrock AgentCore, Docker-packaged Lambdas). Those parts do not apply to VigilWatch and are **not**
copied here. In particular, the account IDs in that file belong to another project and must not appear
in this repository.

| Principle | Status | Evidence / gap |
|---|---|---|
| IaC for everything; GitOps | Met `REPO` | All infrastructure in Terraform; changes via PR |
| OIDC from GitHub to AWS, no stored keys | Met (config validated in `CI`) | `deploy.yml` uses `role-to-assume`; a policy test forbids static keys |
| Least-privilege IAM | Met for Lambda roles `MOCK`; deploy role needs iteration | Lesson 2 in the agent file applies: the deploy role's S3 action list was written without running Terraform against it and will likely need additions on first apply (`NEEDS-AWS`). See F2 |
| Validate the AWS account ID before any operation | **Gap** | No `allowed_account_ids` on the provider, no account check in the workflows. Task 2.2 |
| Review the Terraform plan before any change | Partly | Saved plan applied after approval on `main`; no plan on PRs. Task 3.1 |
| Never deploy straight to PROD; promote from a lower environment | **Gap** | Single environment. Tasks 2.2, 3.2 |
| Block `terraform destroy` in PROD | Partly | DynamoDB `deletion_protection` only; nothing stops a destroy of the rest. Task 2.2 (policy test; no workflow has a destroy path) |
| S3 backend, separate state per environment, never mix local and remote | Partly | Remote backend yes; per-environment state keys no. The agent file says "DynamoDB locking"; this repo uses S3-native `use_lockfile` (Terraform >= 1.10), which removes a table. A deliberate, documented deviation |
| State verification before apply | Partly | Saved plan prevents plan/apply skew; scheduled drift detection missing. Task 3.3 |
| Fail-fast, multi-stage pipeline with verification between stages | Met `CI` | Lint, tests, validate and scans run in parallel; smoke test after apply |
| Test coverage threshold (agent: 80%) | Met `CI` | 85% gate, 93.9% actual |
| Smoke test after deploy | Defined, not yet run against AWS | `pytest -m e2e` is wired into `deploy.yml`; it has only passed against the local stack |
| Rollback procedure | Partly | Runbook documents revert-and-redeploy; no workflow. Task 3.4 |
| Secrets in Secrets Manager | N/A | The system holds no secrets. State this in the README so it is not read as an omission |
| Lambda packaging via Docker | N/A | Stdlib-only code plus the runtime's boto3, so there are no binary wheels to mismatch. A strength worth documenting |
| API Gateway account-level CloudWatch role (Lesson 7) | **Open risk** | Access logging is enabled on the stage. Whether HTTP APIs need the account-level role the way REST APIs do must be checked on first apply (`NEEDS-AWS`). See F1 |
| Concurrency control on deploy workflows | Met `CI` | `concurrency` group, no cancel-in-progress |
| Release management (versions, changelog) | Partly | Tag per run; no changelog. Task 3.4 |
| Monitoring: four golden signals, SLOs (senior-devops) | **Gap** | Alarms exist but no dashboard and no SLI/SLO definition. Tasks 5.3, 5.4 |
| Anti-patterns | None found | No `latest` tags, no secrets in the repo (gitleaks `CI`), per-function roles, no manual deploy path |

## 4. Findings the review notes do not mention

| ID | Finding | Severity | Why it matters |
|---|---|---|---|
| F1 | HTTP API access logging may fail on first apply for lack of an account-level logging role | Medium, `NEEDS-AWS` | Would fail the first apply with a "CloudWatch Logs role ARN must be set" style error. The fix is small and known; find out early and put a ready-made fix in the runbook |
| F2 | Deploy-role permissions are untested against a real Terraform run | Medium, `NEEDS-AWS` | Expect two or three "not authorized" iterations. Record them as they happen; that is exactly the evidence a reviewer likes |
| F3 | Unit tests cannot catch IAM gaps in the *Lambda* roles | Medium | moto does not enforce policies by default, so a missing `dynamodb:Query` would only surface in production. Task 5.5 adds a moto IAM-enforcement test that runs each handler under the exact policy Terraform will create |
| F4 | The endpoint cap is check-then-write, so simultaneous registrations can exceed it by a few | Low | Make it atomic with a counter item and a conditional write. Task 4.6 |
| F5 | The first merge to `main` will fail the deploy workflow until repository variables exist | Medium, certain | A red run on `main` on day one looks bad. Task 0.2 guards the jobs on the variable being set |
| F6 | The old state file is in git history, and `main` still tracks it | Low | Holds resource IDs and the account ID, not credentials. Merging PR #4 stops tracking it. Back it up first (runbook section 2) |
| F7 | `frontend/assets/vigilwatch_logo.png` is an empty (0 byte) file, on `main` too | Low, very visible | The dashboard header shows alt text; a reviewer sees this first. Task 7.1 |
| F8 | `.trivyignore` lists IDs chosen up front, not from observed findings | Low | Unused suppressions look careless. Task 3.5 trims it to what trivy actually reports |
| F9 | Coverage counts only `lambda/`; the frontend has no coverage figure | Low | Add `node --experimental-test-coverage` to CI |

## 5. Roadmap

Rules for every task: test first (a red commit, then a green commit), one concern per PR, nothing claimed
in docs before it is demonstrated. Sizes: S under half a day, M about a day, L two or more days.

### Phase 0: unblock and land (do first)

| Task | Work | Size | AWS |
|---|---|---|---|
| 0.1 | Restore the toolchain: Python 3.12, Terraform >= 1.10 (CI uses 1.14.3), tflint, Node 22+. Recreate `.venv`. Re-run the full matrix locally and compare it with CI | S | no |
| 0.2 | Guard the `plan`, `apply` and `release` jobs in `deploy.yml` with `if: vars.AWS_DEPLOY_ROLE_ARN != ''` so an unconfigured merge shows "skipped", not a failure. RED: a workflow test asserts the guard | S | no |
| 0.3 | Merge PR #4 (after you back up `terraform/terraform.tfstate`). Everything after goes in small PRs, not another mega-PR | S | no |

### Phase 1: make the documentation honest and specific (review notes 1 to 3)

| Task | Work | Size | AWS |
|---|---|---|---|
| 1.1 | README: reword the free-tier subtitle, add CI and coverage badges, replace the generic trade-offs and lessons with dated, evidence-backed ones that link to ADRs. Add a 2-command "try it without AWS" section (`pip install -r requirements-dev.txt`, `python scripts/local_api.py`). RED: extend `tests/test_docs.py` so every figure in the trade-offs section links to an ADR or script | S | no |
| 1.2 | `scripts/cardinality_cost.py`: a pure function `monthly_cost(endpoints, design)` comparing the old design (one custom metric per URL: `max(0, N - 10) * price`) with the current one (fixed 4 metrics, free tier). Prices are constants with a source and a "list price, us-east-1, verify for af-south-1" note. Unit tests pin the arithmetic (for example 100 URLs at $0.30 each is $27.00 per month; 1,000 URLs is $297.00). The result goes into ADR 0003 as a **computed** table, labelled as such | S | no |
| 1.3 | `scripts/measure_cold_start.py`: force cold starts (update an environment variable), read `REPORT` lines (`Init Duration`, `Duration`) from CloudWatch Logs Insights, report p50/p95 over N cold starts. Unit-test the parser against sample `REPORT` lines. Write `docs/performance.md` with the method and an **empty results table** | M | script no; run `NEEDS-AWS` |
| 1.4 | If you hold the CV cold-start figure: add it to `docs/performance.md` **with its method, region, memory size, runtime and date**, marked "earlier measurement, not reproduced by this repo". Replace it with the script's numbers once 1.3 has run | S | no |

### Phase 2: structure, state and environments (review improvements 1 and 3). Do this before the first apply.

Refactoring Terraform after resources exist forces `terraform state mv` for every moved address. Nothing
from the new stack has been applied yet, so now is the cheapest moment.

| Task | Work | Size | AWS |
|---|---|---|---|
| 2.1 | Modules under `terraform/modules/`: `data` (two tables), `compute` (functions, roles, log groups, schedule, DLQ), `api` (HTTP API, stage, routes, CORS), `frontend` (S3, OAC, CloudFront, config.js), `monitoring` (SNS, alarms, later the dashboard). RED first: rewrite `terraform/tests/` to assert at module boundaries (for example `module.data` outputs) plus a root composition test; confirm they fail, then move the code. Each module gets validated `variables.tf` and an `outputs.tf` | L | no |
| 2.2 | Environments: `terraform/envs/dev` and `terraform/envs/prod`, each with its own `backend.hcl` (distinct state key), `terraform.tfvars` and a thin `main.tf` calling the modules. Provider `allowed_account_ids` from a variable. Resource names carry the environment. Free-tier budget: dev capacity 2, prod capacity 5 (14 of 25 RCU/WCU), with a policy test that sums the tfvars and fails above 25. A workflow test asserts that no workflow has a `terraform destroy` step | M | no |
| 2.3 | ADR 0005 recording decision D2: same account with name suffixes now, designed so that moving prod to a second account changes only `allowed_account_ids`, `backend.hcl` and the OIDC role | S | no |

### Phase 3: pipeline completion (review improvement 2)

| Task | Work | Size | AWS |
|---|---|---|---|
| 3.1 | Plan on pull requests: add a second, **read-only** OIDC role in `bootstrap` (trust: `repo:...:pull_request`; permissions: read-only plus state-bucket read). `ci.yml` runs `terraform plan -detailed-exitcode` for dev on PRs and posts the summary as a PR comment. RED: a workflow test requires the plan step and forbids write permissions on the PR path | M | role and run `NEEDS-AWS` |
| 3.2 | Promotion flow: a merge to `main` builds the bundle once and applies **dev** automatically; `promote-prod.yml` (manual dispatch) takes the same commit SHA and the same saved bundle, requires the `production` environment reviewer, runs the smoke test, and tags the release. RED: tests for "prod applies the artifact built for dev" and "no automatic trigger on prod" | M | run `NEEDS-AWS` |
| 3.3 | `drift.yml`: weekly `terraform plan -detailed-exitcode` per environment; exit code 2 opens a GitHub issue. RED: a workflow test (schedule present, exit code 2 handled, `issues: write` only on that job) | S | run `NEEDS-AWS` |
| 3.4 | `rollback.yml`: manual dispatch with a commit SHA, approval required, redeploys that SHA and runs the smoke test. Add a `CHANGELOG.md` generated from conventional commits at tag time | M | run `NEEDS-AWS` |
| 3.5 | Prune `.trivyignore` to what trivy actually reports. Add checkov only if it finds something trivy does not (avoid duplicate noise) | S | no |

### Phase 4: an honest checker (review improvement 5) and alert polish (7)

Design to implement and record in `docs/adr/0006-checker-honesty.md`:

- A failed **check** means "the target did not answer correctly while the checker was healthy". A failed
  **checker** means "the monitor cannot be trusted right now". The system must never turn the second
  into the first.
- Each run probes two **control targets** that are expected to be up (configurable; default: this
  deployment's own CloudFront `/healthz.txt` and one independent third-party URL). If every control
  probe fails, the run is marked `inconclusive`: no endpoint result is recorded as DOWN, no
  `consecutive_failures` increment, no incident, no target alert. The checker instead emits a
  `ControlProbeFailed` metric that drives a "checker blind" alarm.
- The checker writes a **heartbeat** (`last_successful_run`) every run. The existing
  `checker-not-running` alarm covers "did not run"; the heartbeat plus a freshness SLI covers "ran but
  did not complete".
- Documented limitation: one region and one Lambda still cannot see a regional AWS outage. State that
  plainly. Multi-region probing (a second region running the same Lambda, results compared) is the next
  step and stays out of scope for cost reasons.

| Task | Work | Size | AWS |
|---|---|---|---|
| 4.1 | RED tests: all controls fail means every endpoint result is `inconclusive`, failures not incremented, no incident, `ControlProbeFailed=1` in the EMF record; one control fails and one passes means results are trusted; an endpoint DOWN while controls pass opens an incident as today | M | no |
| 4.2 | Implement control probes in `common/checker.py` (reusing `probe`, with the SSRF guard applied to control URLs too) and the `inconclusive` state in the view and schema. Update `tests/contract/checks_response.schema.json` and the frontend status pill | M | no |
| 4.3 | Heartbeat item and freshness metric; Terraform alarm `checker-blind`; `terraform test` assertion | S | no |
| 4.4 | `docs/adr/0006-checker-honesty.md` with the decision table above and the single-region limitation | S | no |
| 4.5 | Optional alert polish: a reminder alert every N minutes while an incident stays open; flap damping (RECOVERED waits for 2 consecutive UPs) | S | no |
| 4.6 | Atomic endpoint cap (F4): a counter item with a conditional update. RED: a threaded test fires concurrent registrations and asserts the cap holds | S | no |

### Phase 5: resilience, observability and SLOs (review improvement 4)

| Task | Work | Size | AWS |
|---|---|---|---|
| 5.1 | PITR on both tables via a module variable (`enable_pitr`: true for prod, false for dev). **Cost note:** PITR is billed per GB-month and is not part of the always-free tier; with kilobytes of data the charge rounds to cents but is not zero. Record this in ADR 0002 (replacing the "no PITR" line) and in the README cost table, with the price to verify for `af-south-1`. RED: `terraform test` asserts PITR on in prod and off in dev | S | no |
| 5.2 | `docs/resilience.md`: a failure-mode table (component, failure, detection, alarm, recovery, RTO and RPO stated as **targets**, not results). Covers: checker Lambda errors, EventBridge not firing, DynamoDB throttling and corruption, SNS delivery failure, API 5xx, CloudFront or S3 loss, regional outage, bad deploy, state corruption | M | no |
| 5.3 | CloudWatch dashboard (the first 3 dashboards are free) with the four golden signals: latency (API p50/p99, checker duration), traffic (API count, checks run), errors (API 5xx, checker errors, DLQ depth), saturation (DynamoDB consumed vs provisioned capacity, Lambda concurrency). `terraform test` asserts the widgets exist | S | no |
| 5.4 | `docs/slo.md`: SLIs and SLOs for VigilWatch itself (checker freshness: a successful run in the last 10 minutes, 99.5% of the time; API availability 99.5%; API p99 under 500 ms), the error-budget rule, and which alarm burns which budget | S | no |
| 5.5 | **Policy-vs-code test (F3):** a pytest module that builds the exact IAM policy JSON Terraform will create, makes a moto IAM user with that policy, and runs each handler with that user's credentials under moto's IAM enforcement. A missing action fails the test. Label `MOCK` (moto's IAM fidelity is partial) | M | no |
| 5.6 | `scripts/restore_drill.py` plus a runbook procedure: restore the history table to a new table from a point in time, compare item counts and a sample of rollups, delete the copy. Unit-test the comparison logic with moto. Add an empty "Drill log" table to `docs/resilience.md` (date, table, restore point, duration, items compared, result). **The drill itself is `NEEDS-AWS`; the log stays empty until it is run.** | M | script no; run `NEEDS-AWS` |

### Phase 6: authentication (review improvement 6). Decision D1 first.

Recommended: **Cognito user pool plus the HTTP API's native JWT authorizer.** The authorizer adds no
per-request charge, HTTP API stays (ADR 0001 stands), and per-user isolation comes with it, which a shared
API key cannot give. Verify the current Cognito free tier and feature plan before enabling, as its pricing
changed in 2024. WAF is **not** zero-cost (a web ACL and each rule carry fixed monthly fees), so the
zero-cost substitute stays throttling plus the endpoint cap. Offer `enable_waf` as an opt-in variable
defaulting to false, with a test that the default is false.

| Task | Work | Size | AWS |
|---|---|---|---|
| 6.1 | ADR 0007: auth options (Cognito + JWT, shared key, none), cost, trade-offs, decision | S | no |
| 6.2 | RED: handler tests with `requestContext.authorizer.jwt.claims.sub`. No subject means 401 at the handler (defence in depth); endpoints are stored under the owner (`owner_sub`) and `GET /checks` returns only the caller's; a per-user cap replaces the global cap; the endpoint id includes the owner so two users can monitor the same URL | M | no |
| 6.3 | Terraform: user pool, app client (PKCE, no secret), domain prefix, JWT authorizer on both routes; `terraform test` asserts no route is left on `NONE`. A public read-only demo route is optional and explicit | M | no |
| 6.4 | Frontend: Hosted UI redirect with PKCE, token kept in memory (not localStorage), `Authorization` header on calls, sign-out. jsdom tests for callback parsing and for never writing tokens to storage | L | no |
| 6.5 | `docs/security.md`: threat model (assets, actors, abuse cases: SSRF, enumeration, cost abuse), controls mapped to tests, accepted risks. Remove "No authentication" from the README trade-offs and record that WAF is an opt-in paid control | S | no |

### Phase 7: portfolio packaging

| Task | Work | Size | AWS |
|---|---|---|---|
| 7.1 | Add the real logo (F7). Capture dashboard screenshots from `scripts/local_api.py` for the README | S | no |
| 7.2 | Replace the ASCII diagram in the README with a Mermaid diagram; add an "Engineering decisions" index (ADR table with one-line outcomes and the evidence tag) | S | no |
| 7.3 | `docs/interview-notes.md`: the questions a reviewer will probe (why HTTP API, why provisioned DynamoDB, why control probes, what the single-region limitation means, what failed on first apply), each answered in 3 to 5 lines with a link to the evidence. Fill the "what failed on first apply" section **after** the AWS day, with the real errors | S | partly |

### The AWS day (the only work that needs an account)

Do this once Phases 0 to 5 are merged. Each step produces a result that replaces an empty template in the docs.

1. Credentials working (`aws sts get-caller-identity`); `af-south-1` enabled; zero-spend budget created.
2. Bootstrap stack applied; repository variables and the `production` environment set (runbook section 1).
3. State migrated (runbook section 2); first plan reviewed line by line; apply dev.
4. Record every error hit on first apply (F1, F2) and what fixed it, as a dated list in the runbook.
5. Run the e2e smoke test against dev; run `scripts/measure_cold_start.py` (task 1.3); fill `docs/performance.md`.
6. Run the restore drill (task 5.6); fill the drill log in `docs/resilience.md`.
7. Promote to prod through the manual workflow; confirm the approval gate holds.
8. Take screenshots from the live dashboard; add the live URL and badges to the README.

## 6. Decisions needed

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Authentication approach | Cognito + JWT authorizer (Phase 6). Alternative: stay public with throttling and say so. A shared API key is the weakest option, and a usage plan would require REST (reversing ADR 0001) |
| D2 | Environments | Dev and prod in one account with name suffixes now; separate accounts only if you want stronger isolation (each account has its own free tier, but creating them is your task) |
| D3 | PITR cost | Accept a few cents per month for prod only; the one deliberate departure from "$0 exactly" |
| D4 | Cold-start figure from the CV | Send the method (region, memory, runtime, number of cold starts, how it was measured) and it is documented as an earlier measurement; otherwise it stays unclaimed until task 1.3 runs |
| D5 | Delivery shape | Land PR #4 first, then one PR per phase. Phase 2 is the largest and should go before any apply |

## 7. Suggested order

`0.1 to 0.3`, then `1.1 to 1.2` (fast, high-visibility wins), then `2.1 to 2.3` (before any apply), then
`4.x` (the strongest interview story, fully testable offline), then `3.x`, `5.x`, `6.x`, then the AWS day,
then `7.x`. Phases 1, 4 and 5 touch different files from Phase 2 and can proceed in parallel with its review.
