# VigilWatch: implementation plan (stages 0 to 12)

**Source documents:** `docs/AUDIT_AND_ROADMAP.md` (audit and gap analysis, commit `c3f7201`, PR #4) plus the attached
`SDLC_Process`, `DevOps_Engineer_Agent`, `SDET_Engineer_Agent`, `SDET_unit_test`, `SDET_integration_test`,
`Three_Layer_Feature_Debugging`, `AWS_Python_Dev` and `Agentic_Project_Manager` files.
**Branch:** `claude/vigilwatch-review-plan-0c24b4`. **PR #4:** open, CI green, mergeable.
**Constraint:** no AWS account yet. Everything is built and proven offline (unit, moto, `terraform test`, jsdom, CI);
anything that needs AWS is isolated in Stage 10 and Stages 11 to 12.

## Context

The audit found that `main` cannot deploy, and PR #4 fixes that but is unmerged. Beyond the PR, the roadmap lists
what is still missing for a portfolio-grade project: an honest checker, modules, environments, a promotion pipeline,
resilience evidence, authentication and specific (not generic) documentation. The attached principles add process rules:
test-first with traceability to requirements, a formal test taxonomy, three-layer debugging, build-once promotion,
and no production endpoints in test code. This plan turns both into ordered, testable work.

## Decisions (resolved)

| ID | Decision | Consequence |
|---|---|---|
| D1 | **Cognito + JWT authorizer** | Stage 8. Verify the current Cognito free tier and `af-south-1` availability before the first apply |
| D2 | **DEV + PROD in one account**, no SIT | SIT dropped: a third environment pushes alarms past the free 10 and adds plumbing for a one-person project. Recorded in ADR 0005. Prod approval by the owner stands in for UAT sign-off |
| D3 | **No PITR, stay at exactly $0** | Resilience uses a logical backup and restore script for the one durable table, plus a drill. Note: DynamoDB export to S3 needs PITR, so it is not an option |
| D4 | Cold-start figure from the CV | Still pending from you (method, region, memory, runtime, N). Until supplied, the repo ships a measurement script and an empty results table |
| D5 | LocalStack integration and canary deploy | **Both included, last** (Stages 11 and 12), droppable without affecting anything else |

## Principles applied

| Source | Rule | How this plan applies it |
|---|---|---|
| SDLC | TDD mandatory; tests before code | Every task is RED commit (shown failing), GREEN commit, REFACTOR commit |
| SDLC | Requirements, HLD, LLD before development | Stage 2 adds `requirements.md` with IDs, an OpenAPI spec and sequence diagrams that include exception paths |
| SDLC / SDET | Unit coverage above 80%; mocks run without AWS | Gate raised from 85% to **90%** (current 93.9%), per the SDET strategy pack |
| SDLC / SDET | **No PROD endpoints in test code** | URLs come only from environment variables or Terraform outputs at run time. A policy test fails on any `execute-api` or `cloudfront.net` literal under `tests/` |
| SDLC / DevOps | No hardcoded credentials or environment values | Terraform parameterised per environment; a policy test forbids literals |
| SDLC | UAT before PROD | `promote-prod` needs the `production` environment approval plus a signed UAT checklist |
| SDET | Test taxonomy and "all tests must be marked" | Markers `unit`, `mock`, `integration`, `e2e`, `smoke`, `contract`, `policy`, `bdd`, `negative`, `boundary`, `security`; a collection hook fails on an unmarked test |
| SDET | BVA, equivalence partitioning, negative tests at least as many as positive, decision tables for 3 or more conditions | Stage 3 (inputs) and Stage 4 (alert state-machine decision table). Counts reported in the CI summary |
| SDET | BDD with Gherkin for user-facing behaviour | `tests/features/*.feature` (pytest-bdd), each scenario tagged with a requirement ID |
| SDET | Proxy-first: never call services directly in E2E | Satisfied in intent: VigilWatch's API Gateway *is* the proxy under test. A policy test forbids `boto3` imports under `tests/e2e/`. A separate proxy stack is not built (recorded in ADR 0005) |
| SDET | Environment-aware E2E (`--env`), PROD read-only, cleanup | Stage 3.6 and Stage 6 |
| Three-layer debugging | Write path, read path, display path each need their own test | Every feature in Stages 4 and 8 carries a W/R/D test row (matrix below). Stage 7 adds the "dashboard shows no data" runbook protocol |
| AWS_Python_Dev | Reuse boto3 clients across invocations; structured logging; structured errors; input validation; moto | Stage 3.2 to 3.4 |
| DevOps | Validate account ID; review plan; promote, never deploy straight to prod; block destroy in prod; per-environment state; state verification; rollback; checklists | Stages 5, 6, 10 |
| DevOps lessons | 2: iterate IAM on evidence. 3 and 4: verify the package in the Lambda runtime. 7: API Gateway account-level logging role | Stage 6 (package verification), Stage 10 (IAM iteration log, apigw role check) |
| CI gate integrity | A gate that skipped is not green | Stage 6.7: the smoke job fails if any e2e test skipped; workflow tests forbid `continue-on-error` and `\|\| true` |
| APM | Stages with dependencies, acceptance criteria, state tracking | This document; copied to `docs/plans/vigilwatch-improvement.md` in Stage 1 so progress is tracked in git |

**Deliberately not adopted** (with reasons, recorded in ADR 0005 and ADR 0008): the agent file's AWS account IDs, SES, WordPress and
AgentCore material (other projects); SIT and Business-Owner/Tech-Lead dual approval (single maintainer); Powertools, Lambda layers
and SnapStart (adds packaging and X-Ray cost; SnapStart for Python is billed, verify current pricing); Docker-packaged Lambdas and Secrets
Manager (stdlib-only code, no secrets; Cognito app client has no secret); a DynamoDB lock table (S3 native `use_lockfile`);
Lesson 5 "deploy despite failing tests" (gates stay strict); HATEOAS (two routes, no hierarchy).

## Environment configuration (APM requirement)

| Setting | DEV | PROD |
|---|---|---|
| AWS account | one account, ID supplied by you at Stage 10 (never committed) | same account |
| Region | `af-south-1` (variable) | `af-south-1` |
| Trigger | auto on push to `main` (`deploy-dev.yml`) | manual (`promote-prod.yml`), same commit SHA and same bundle bytes as DEV |
| Approval | none | `production` environment reviewer + signed UAT checklist |
| State key | `vigilwatch/dev.tfstate` | `vigilwatch/prod.tfstate` |
| DynamoDB capacity (RCU/WCU per table) | 2 | 5 (14 of 25 free units used; a policy test sums the tfvars) |
| Alarms | 3 (checker-errors, checker-not-running, checker-blind) | 5 (adds checker-dlq, api-5xx); 8 of 10 free |
| Destroy | allowed locally only | no workflow has a destroy step; `deletion_protection` on tables |

## Stage progress

| # | Stage | Depends on | Size | Needs AWS | Status |
|---|---|---|---|---|---|
| 0 | Toolchain install and baseline | none | S | no | ✅ COMPLETE |
| 1 | Land PR #4 and repo guardrails | 0 | S | no | 🔄 IN PROGRESS (1.2, 1.3 done and pushed; 1.1, 1.4 need you) |
| 2 | Requirements, design and traceability | 1 | M | no | ✅ COMPLETE |
| 3 | Quality foundation (taxonomy, SOLID, cold start, errors, E2E harness) | 2 | L | no | ✅ COMPLETE |
| 4 | Honest checker, alert state machine, atomic cap | 3 | M | no | ⏳ PENDING |
| 5 | Terraform modules and environments | 3 | L | no | ⏳ PENDING |
| 6 | Pipeline, promotion, rollback, drift, gate integrity | 5 | L | partly (runs) | ⏳ PENDING |
| 7 | Resilience, observability, SLOs | 4, 5 | M | partly (drill) | ⏳ PENDING |
| 8 | Authentication (Cognito) | 3, 5 | L | partly (login) | ⏳ PENDING |
| 9 | Documentation and portfolio packaging | 4 to 8 | M | no | ⏳ PENDING |
| 10 | AWS day: deploy, integration test, UAT, ship | 5 to 9 | M | **yes** | ⏳ PENDING |
| 11 | Optional: integration layer (LocalStack or moto server) | 3 | M | no | ⏳ PENDING |
| 12 | Optional: canary deploy (Lambda alias + CodeDeploy) | 10 | M | **yes** | ⏳ PENDING |

Stages 4 and 5 can run in parallel after Stage 3. Stages 11 and 12 come last and can be dropped.

## Execution protocol (applies to every task)

1. **RED:** write the failing test, run it, show the failure, commit (`test(<area>): ...`).
2. **GREEN:** minimum code to pass, commit (`feat|fix(<area>): ...`).
3. **REFACTOR:** clean up with tests green, commit (`refactor: ...`).
4. One PR per stage, branch `stage-N-<name>` from the updated base. CI must be green; the stage's acceptance gate is ticked in the PR.
5. Evidence tags in docs: `CI`, `MOCK`, `REPO`, `NEEDS-AWS`. Nothing unmeasured is published.
6. Commits end with the Co-Authored-By trailer. No push, merge or repository-setting change without your explicit go-ahead at that moment.

---

## Stage 0: toolchain install and baseline (do first on approval)

Installs change your machine, so this runs only after you approve the plan. Windows UAC prompts may appear; I cannot click them.

| Task | Work |
|---|---|
| 0.1 | `winget install --id Hashicorp.Terraform -e` (1.16.6 available), `winget install --id Python.Python.3.12 -e --scope user` (3.12.10), `winget install --id TerraformLinters.tflint -e` (0.65.0). All three IDs were confirmed with a read-only `winget search` |
| 0.2 | Open a fresh shell (new PATH). Python's Store alias can shadow the real one, so use `py -3.12`. Verify: `terraform version`, `py -3.12 --version`, `tflint --version`. If PATH is stale in this session, call the executables by full path |
| 0.3 | Delete the broken `.venv` (its base interpreter is gone; it is git-ignored), then `py -3.12 -m venv .venv` and `.venv\Scripts\python -m pip install -r requirements-dev.txt`; `cd frontend && npm ci` (Node 24 is present; CI uses 22) |
| 0.4 | Run the full matrix and compare with CI on `c3f7201`: `pytest --cov` (191 passed, 93.9%), `ruff check . && ruff format --check .`, `terraform fmt -check -recursive`, `terraform init -backend=false && validate && test` (10/10), `npm test` (10/10) |
| 0.5 | Terraform version policy: local is 1.16.6, CI pins 1.14.3. Create `.terraform-version` as the single source of truth; RED test asserts CI's `TF_VERSION` equals it; bump CI if 1.16.6 passes all of 0.4 |
| 0.6 | Not installed now: Docker Desktop (`Docker.DockerDesktop` 4.96.3). It needs virtualisation and a restart, which is your action, and only Stage 11 needs it |

**Acceptance:** every command in 0.4 passes locally with the same counts as CI; versions recorded in the PR description.

## Stage 1: land PR #4 and repo guardrails

| Task | Work | RED first |
|---|---|---|
| 1.1 | You back up `terraform/terraform.tfstate` from your main checkout (merge deletes it from the working tree) | n/a (your action) |
| 1.2 | `deploy.yml`: guard `plan`, `apply`, `release` with `if: vars.AWS_DEPLOY_ROLE_ARN != ''` so an unconfigured merge shows "skipped", not a failure | workflow test asserts the guard |
| 1.3 | Commit `docs/AUDIT_AND_ROADMAP.md` and this plan as `docs/plans/vigilwatch-improvement.md` | docs test: relative links resolve |
| 1.4 | Merge PR #4 once you approve. Branch protection (require CI) only if you ask: it changes repository settings | n/a |

**Acceptance:** `main` has the fixed repo; the first deploy run on `main` is green or skipped, never red.
**Depends on:** 0. **Blocks:** everything.

## Stage 2: requirements, design and traceability (SDLC stages 1 to 3)

| Task | Work | RED first |
|---|---|---|
| 2.1 | `docs/design/requirements.md`: about 15 user stories `VW-001..` (register URL, scheduled check, status, uptime, incident, alert, recovery, SSRF protection, cap, access control, resilience, observability), each with acceptance criteria | `tests/test_traceability.py`: every `VW-nnn` is referenced by at least one test; every `req("VW-nnn")` marker points to an existing story |
| 2.2 | `docs/openapi.yaml` (OpenAPI 3.1) for `POST /register` and `GET /checks`, including error schemas. It becomes the source of truth; `scripts/export_schema.py` exports `tests/contract/checks_response.schema.json` from it | drift test: exported schema equals the committed one; handler responses validate against the OpenAPI components |
| 2.3 | `docs/design/sequences.md`: Mermaid sequence diagrams for register, scheduled check and alert, each showing the business-exception and unexpected-exception paths (SDLC rule) | docs test: every diagram has an `alt` or `else` branch |
| 2.4 | `tests/features/*.feature` (pytest-bdd): monitoring, alerting, access; `Scenario Outline` tables for status partitions. Steps call handlers through the mock layer | features fail until steps exist |
| 2.5 | Register the `req` marker; tag existing tests with the story they prove | traceability test above |

**Acceptance:** a requirement-to-test matrix is generated (`scripts/traceability.py`) with no uncovered story; OpenAPI and schema cannot drift.
**Depends on:** 1.

## Stage 3: quality foundation (SDLC stages 4 and 5; AWS_Python_Dev)

| Task | Work | RED first |
|---|---|---|
| 3.1 | **Test taxonomy.** `tests/integration/` becomes `tests/mock/` (those tests are moto-based); `tests/integration/` is reserved for LocalStack or deployed runs. Register all markers in `pytest.ini`; a `pytest_collection_modifyitems` hook auto-marks by directory and **fails on any unmarked test** | `-m unit` must run with moto never imported; a test asserts every collected item has a layer marker |
| 3.2 | **Cold start.** Replace per-invocation `Repo()` and `boto3.resource/client` construction with lazily cached clients (`functools.lru_cache`, plus a reset fixture for tests). Add stdlib structured JSON logging with the request ID | test: two handler invocations create the DynamoDB resource once; log lines are valid JSON with a request ID |
| 3.3 | **SOLID refactor, no behaviour change.** Split `repo.py` into endpoint, history and incident repositories; split `checker.py` into `probe.py`, `alerts.py` and the state machine; small `Protocol` interfaces for injection. All existing tests must stay green untouched | existing 191 tests are the safety net; add a structural test (no module imports upward) |
| 3.4 | **Error model.** An `AppError` hierarchy (`ValidationError` 400, `NotFoundError` 404, `LimitError` 429, `UnauthorizedError` 401) and one handler wrapper; responses gain a stable `code` field (additive, frontend unchanged) | one test per error class; OpenAPI error schema updated |
| 3.5 | **Test-design coverage.** Add BVA, EP and negative tests: URL length 2047/2048/2049; port 0/1/65535/65536; `expected_status` 99/100/599/600; endpoint cap n-1/n/n+1; `FAILURE_THRESHOLD` 0/1/10/11; degraded boundary 999.9/1000. Tag `boundary`, `negative`, `security`. CI summary prints negative-to-positive counts | tests written before any code change they require |
| 3.6 | **E2E harness (API proxy pattern).** `tests/e2e/config.py` + `--env` option; `tests/proxies/{base,local,dev}_proxy.py` (no prod proxy); `is_read_only` for prod skips writes; cleanup fixture; unique test data. No URL literals in tests | policy tests: no URL literals, no `boto3` in `tests/e2e/` |
| 3.7 | Raise the coverage gate to 90% (`fail_under`); add frontend coverage (`node --experimental-test-coverage`, gate 80%) | pyproject test asserts the thresholds |

**Acceptance:** all tests marked; `pytest -m unit` runs in under 5 seconds with no AWS libraries; coverage at least 90% (Python) and 80% (frontend); no behaviour change other than the additive `code` field.
**Depends on:** 2.

## Stage 4: honest checker and alert quality

Design record `docs/adr/0006-checker-honesty.md`: a failed **check** means the target answered wrongly while the checker was healthy; a failed
**checker** means the monitor cannot be trusted. Control probes (the deployment's own `/healthz.txt` plus one independent URL) run each cycle;
if all fail the run is `inconclusive`: no DOWN recorded, no failure counted, no incident, no target alert. A heartbeat is written every run.
The single-region limitation is documented, not hidden.

Alert decision table (SDET rule for three or more conditions), written as the test parameter set:

| Status is DOWN | Controls healthy | Failures >= threshold | Incident open | Result |
|---|---|---|---|---|
| no | yes | n/a | no | UP/DEGRADED, reset failures |
| no | yes | n/a | yes | close incident, send RECOVERED |
| yes | yes | no | no | count failure, no alert |
| yes | yes | yes | no | open incident, send DOWN once |
| yes | yes | yes | yes | no new alert (reminder only if enabled) |
| yes | no | any | any | `inconclusive`, no change, `ControlProbeFailed=1` |

Three-layer test matrix for this stage (Three-Layer Feature Debugging):

| Feature | Write path | Read path | Display path |
|---|---|---|---|
| Inconclusive state | checker stores `inconclusive`, heartbeat item (mock) | `GET /checks` returns it; schema updated; route exists in `terraform test` | status pill shows "Inconclusive" (jsdom) |
| Heartbeat and freshness | heartbeat written each run (mock) | `checker-blind` alarm exists and targets SNS (`terraform test`) | n/a (ops signal) |
| Atomic endpoint cap | concurrent registrations never exceed the cap (threaded mock test) | `POST /register` returns 429 at the cap | error message shown to the user (jsdom) |

| Task | Work |
|---|---|
| 4.1 | RED: decision-table tests above plus the three-layer rows |
| 4.2 | Control probes and `inconclusive` in `checker.py`/state machine; heartbeat item; view and OpenAPI/schema additions; frontend pill and legend |
| 4.3 | `checker-blind` alarm and `ControlProbeFailed` EMF metric (module `monitoring` after Stage 5; added to the current root first if Stage 5 is not merged) |
| 4.4 | Atomic cap with a counter item and conditional update |
| 4.5 | Optional alert polish: reminder every N minutes while an incident is open; RECOVERED after 2 consecutive UPs (flap damping) |
| 4.6 | ADR 0006 with the table and the limitation |

**Acceptance:** a simulated control-probe outage produces zero false DOWN alerts; every row of the decision table is a passing test; ADR written.
**Depends on:** 3.

## Stage 5: Terraform modules and environments

Done before the first apply: moving resources after they exist forces `terraform state mv` for every address.

| Task | Work | RED first |
|---|---|---|
| 5.1 | Modules under `terraform/modules/`: `data`, `compute`, `api`, `frontend`, `monitoring`, each with validated variables and outputs | rewrite `terraform/tests/` to assert at module boundaries plus a root composition test; confirm failing, then move code |
| 5.2 | `terraform/envs/dev` and `envs/prod`: thin `main.tf`, `terraform.tfvars`, own `backend.hcl` (distinct state key). Resource names carry the environment | `terraform test` per environment; policy test sums tfvars: capacity at most 25, alarms at most 10 across environments |
| 5.3 | Provider `allowed_account_ids` from a variable; no workflow has `terraform destroy`; prod tables keep `deletion_protection` | tests for each |
| 5.4 | **Build once.** `scripts/build_bundle.py` produces a deterministic zip and `bundle.sha256`; Terraform takes `bundle_path` and `bundle_sha256` instead of `archive_file` at plan time, so prod deploys the exact bytes dev ran | test: two builds of the same tree are byte-identical; Terraform test asserts hash wiring |
| 5.5 | Policy-vs-code test (finding F3): build the exact IAM policy JSON, create a moto IAM user with it, run each handler under moto IAM enforcement. A missing action fails the test. Evidence tag `MOCK` | test is the deliverable |
| 5.6 | ADR 0005: environments (D2) and the account-ID, proxy and SIT decisions | docs test |

**Acceptance:** `terraform test` green per module and per environment; `terraform validate` green for both environments; policy test green; no resource address left in the root.
**Depends on:** 3.

## Stage 6: pipeline, promotion, rollback, drift and gate integrity (DevOps Stage 6)

| Task | Work | RED first |
|---|---|---|
| 6.1 | Rename and split to the DevOps layout: `deploy-dev.yml` (auto on `main`), `promote-prod.yml` (manual, environment approval, same SHA and bundle), `rollback.yml` (manual, SHA input, approval), `drift.yml` (weekly), `ci.yml` | extend `tests/test_workflows.py` per file |
| 6.2 | Plan on pull requests: a second **read-only** OIDC role in `bootstrap` (trust `pull_request`); `terraform plan -detailed-exitcode` for dev, summary posted as a PR comment | test: PR path has no write permissions and no apply |
| 6.3 | Package verification (Lesson 3 and 4): build the bundle, then import every handler module and call each with a synthetic event inside the `public.ecr.aws/lambda/python:3.12` image on the CI runner | job must fail when a module is deliberately broken (mutation check) |
| 6.4 | Account guard: workflows run `aws sts get-caller-identity` and fail unless the account matches the `AWS_ACCOUNT_ID` repository variable | workflow test |
| 6.5 | `drift.yml`: exit code 2 opens an issue (`issues: write` on that job only) | workflow test |
| 6.6 | `rollback.yml` redeploys a given SHA's saved bundle, then runs the smoke tests; `CHANGELOG.md` generated at tag time | workflow test |
| 6.7 | **CI gate integrity.** The smoke job fails if any e2e test skipped or fewer than N ran; workflow tests forbid `continue-on-error`, `\|\| true` and `-auto-approve`; prod runs only read-only smoke tests | workflow tests; a deliberately unset `API_URL` must turn the job red |
| 6.8 | Pre- and post-deployment checklists in `docs/RELEASE_CHECKLIST.md`, rendered into the job summary | docs test |

**Acceptance:** all workflow policy tests green; package-verification mutation check proven; PR-plan, drift, rollback and promote jobs are `NEEDS-AWS` to run, validated by policy tests only.
**Depends on:** 5.

## Stage 7: resilience, observability and SLOs

| Task | Work | RED first |
|---|---|---|
| 7.1 | `scripts/backup_tables.py` and `restore_tables.py` (logical dump of the **endpoints** table to JSONL; history is TTL data and re-creatable) | moto round-trip: dump, wipe, restore, compare; restore is idempotent |
| 7.2 | `scripts/restore_drill.py`: restores into a scratch table, compares counts and a sample, deletes it. A drill log table in `docs/resilience.md` stays **empty until run** | comparison logic tested with moto |
| 7.3 | `docs/resilience.md`: failure-mode table with detection, alarm, recovery, and RTO/RPO stated as **targets**. Explicitly says there is no point-in-time restore (D3) and why | docs test |
| 7.4 | Golden-signals CloudWatch dashboard (module `monitoring`); saved Logs Insights queries (`aws_cloudwatch_query_definition`) for triage | `terraform test` asserts widgets and queries exist |
| 7.5 | `docs/slo.md`: checker freshness (successful run in the last 10 min, 99.5%), API availability 99.5%, p99 under 500 ms; error-budget rule; alarm-to-SLO map | docs test |
| 7.6 | Runbook protocol **"dashboard shows no data"** from the three-layer skill, with exact commands: write path (`aws dynamodb get-item` on the endpoints and history tables), read path (`aws apigatewayv2 get-routes`, `curl` the route), display path (inspect the raw JSON against the schema) | docs test checks the three headings |
| 7.7 | An IAM iteration log section in the runbook (Lesson 2) with a table: date, error, permission added, reason | docs test |

**Acceptance:** backup, restore and drill logic proven with moto; resilience doc complete with targets only; dashboard and queries asserted by `terraform test`; drill log empty and labelled `NEEDS-AWS`.
**Depends on:** 4 (heartbeat), 5.

## Stage 8: authentication (Cognito + JWT authorizer)

Verify before enabling: current Cognito free tier and feature plan, and `af-south-1` availability (`NEEDS-AWS`). WAF is not free, so the zero-cost substitutes stay
throttling and per-user caps; `enable_waf` exists as an opt-in variable defaulting to false.

| Feature | Write path | Read path | Display path |
|---|---|---|---|
| Owner-scoped endpoints | stored with `owner_sub` (mock) | `GET /checks` returns only the caller's; routes use the JWT authorizer (`terraform test`: no route on `NONE`) | signed-out and signed-in states, token never written to storage (jsdom) |

| Task | Work | RED first |
|---|---|---|
| 8.1 | ADR 0007 (options and decision) | docs test |
| 8.2 | Handlers read `requestContext.authorizer.jwt.claims.sub`; missing subject returns 401; endpoint id includes the owner; per-user cap replaces the global cap. EP partitions: valid, missing, empty, wrong type | mock tests, `negative` and `security` markers |
| 8.3 | Terraform: user pool, app client (PKCE, no secret), hosted-UI domain, JWT authorizer on both routes; CSP `connect-src` extended for Cognito | `terraform test` |
| 8.4 | Frontend: hosted-UI redirect with PKCE, token held in memory, `Authorization` header, sign-out | jsdom tests |
| 8.5 | `docs/security.md`: threat model, controls mapped to tests, accepted risks | docs test |

**Acceptance:** no route is unauthenticated; cross-user access returns 404 or 403 in tests (IDOR test pattern); the login flow is `NEEDS-AWS` and is verified in Stage 10.
**Depends on:** 3, 5.

## Stage 9: documentation and portfolio packaging

| Task | Work |
|---|---|
| 9.1 | README: reword the "always-free" subtitle (API Gateway's free tier lasts 12 months), CI and coverage badges, a two-command "try it without AWS" path (`python scripts/local_api.py`), Mermaid architecture diagram, engineering-decisions index with evidence tags |
| 9.2 | `scripts/cardinality_cost.py` with pinned arithmetic tests (100 URLs at $0.30 each is $27.00 per month; 1,000 is $297.00; list price, us-east-1, verify for `af-south-1`); results into ADR 0003 labelled **computed** |
| 9.3 | `scripts/measure_cold_start.py` (parse `REPORT` lines, p50/p95, unit-tested on samples) and `docs/performance.md` with an empty results table; your CV figure goes in only with its method (D4) |
| 9.4 | Replace the generic trade-offs and lessons in the README with dated, linked, evidence-tagged ones |
| 9.5 | `docs/interview-notes.md` (the questions a reviewer will probe, each answered in 3 to 5 lines with links) |
| 9.6 | Add the real logo (the file is 0 bytes on `main`); screenshots from the local stack |

**Acceptance:** docs tests green; every number in the README links to an ADR, script or test; no unmeasured figure published.
**Depends on:** 4 to 8.

## Stage 10: AWS day (deploy, integration test, UAT, ship)

Needs credentials working (`aws sts get-caller-identity`), `af-south-1` enabled, a zero-spend budget. This is SDLC Stage 7: integration tests on DEV, then UAT, then promote.

| Step | Work | Evidence produced |
|---|---|---|
| 10.1 | Bootstrap stack, repository variables (`AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, `AWS_ACCOUNT_ID`, `NOTIFICATION_EMAIL`), `production` environment with you as reviewer | runbook checklist ticked |
| 10.2 | State migration (runbook section 2), first plan read line by line, apply DEV | plan summary in the PR |
| 10.3 | Record every first-apply error and fix in the IAM/apply iteration log. Check the API Gateway account-level logging role (DevOps Lesson 7) | dated log |
| 10.4 | Integration and smoke tests on DEV (`pytest -m "integration or smoke" --env=dev`); sign-in flow; confirm the DOWN and RECOVERED emails arrive | test report |
| 10.5 | `measure_cold_start.py` and the restore drill; fill `docs/performance.md` and the drill log | measured numbers only |
| 10.6 | **UAT checklist** (docs/UAT.md): you walk through the requirement stories and sign off in the PR; this stands in for the Business Owner gate | signed checklist |
| 10.7 | `promote-prod.yml` with approval; read-only prod smoke; post-deployment checklist; tag release | prod green |
| 10.8 | Live URL, screenshots and badges into the README | README |

**Acceptance:** DEV and PROD deployed through the pipeline; no manual console changes; every `NEEDS-AWS` item in the docs replaced by a recorded result.
**Depends on:** 5 to 9.

## Stage 11: optional integration layer

Spike first (about an hour): confirm what runs free. LocalStack's current edition, licensing and auth requirements and which services (EventBridge, Lambda, API Gateway v2) it covers must be checked before committing; **fallback: moto server mode**, which needs no Docker and gives genuine cross-process HTTP.

| Task | Work | RED first |
|---|---|---|
| 11.1 | Spike and record the outcome in an ADR | n/a |
| 11.2 | `tests/integration/` against the chosen backend: scheduled checker over real DynamoDB + SNS + SQS endpoints; handlers invoked through a local HTTP adapter | tests marked `integration`, skipped locally when the backend is absent but **failing in CI if skipped** |
| 11.3 | CI job `integration` | workflow test |

**Depends on:** 3 (and Docker, only if LocalStack is chosen).

## Stage 12: optional canary deploy

Lambda alias with weighted routing and CodeDeploy (free for Lambda), automatic rollback on the existing `api-5xx` and `checker-errors` alarms, `Canary10Percent5Minutes`
for prod. Integrations and the EventBridge target point at the alias. Asserted by `terraform test`; **behaviour only provable on AWS**, so it runs after Stage 10.

## Test strategy summary

| Layer | Marker | Backend | Runs in | Gate |
|---|---|---|---|---|
| Unit | `unit` | none | every PR | Python coverage at least 90% |
| Mock | `mock` | moto | every PR | included in coverage |
| Contract | `contract` | OpenAPI-derived schema | every PR | schema drift fails |
| Policy | `policy` | repo files, workflow YAML, Terraform | every PR | zero violations |
| BDD | `bdd` | mock layer | every PR | every scenario tagged with a requirement |
| Infrastructure | n/a | `terraform test`, mocked provider | every PR | all runs pass |
| Frontend | n/a | node:test + jsdom | every PR | coverage at least 80% |
| Integration | `integration` | LocalStack or moto server, then DEV | CI (Stage 11), DEV (Stage 10) | no skips in CI |
| E2E / smoke | `e2e`, `smoke` | deployed API, `--env` | post-deploy | no skips; prod read-only |

## Verification

Offline, after every stage:

```bash
pytest --cov                       # all layers; fails below 90%; fails on unmarked or skipped-in-CI tests
ruff check . && ruff format --check .
terraform -chdir=terraform/envs/dev init -backend=false && terraform -chdir=terraform/envs/dev validate && terraform -chdir=terraform/envs/dev test
terraform -chdir=terraform/envs/prod init -backend=false && terraform -chdir=terraform/envs/prod validate
npm --prefix frontend ci && npm --prefix frontend test
python scripts/traceability.py     # no uncovered requirement
python scripts/local_api.py        # manual check in the browser: register, chart, error messages
```

CI reproduces all of the above on a clean checkout and is the source of truth. Mutation checks (inject a wildcard IAM action, break a handler import, unset `API_URL`)
prove that the policy, package-verification and gate-integrity checks fail when they should. After Stage 10, repeat with `--env=dev`, then a read-only prod smoke.

## Risks and open items

- **Tooling:** installs need your UAC approval; PATH may need a new session.
- **Stage 5 churn:** modules touch every `.tf` file and test. Mitigation: RED tests first, one PR, no apply before it merges.
- **Cognito (Stage 8):** pricing, tier and region availability unverified (`NEEDS-AWS`); hosted-UI domain prefixes are globally unique.
- **First apply (Stage 10):** expect IAM and API Gateway logging iterations (F1, F2). The plan budgets for them rather than assuming success.
- **LocalStack (Stage 11):** licensing and coverage unverified; the moto-server fallback is already planned.
- **Open input from you:** the CV cold-start method (D4), and your AWS account ID and credentials at Stage 10 (the account ID is never committed).

**Navigation:** Previous: `docs/AUDIT_AND_ROADMAP.md`. Next: Stage 0.

## Progress log

| Date | Stage | Result | Evidence |
|---|---|---|---|
| 2026-10-24 | 0 | Installed Terraform 1.16.6, Python 3.12.10, tflint 0.65.0 (winget); venv and frontend deps rebuilt | local run: ruff clean; 196 pytest passed at 93.88% coverage; `terraform test` 10/10 on 1.16.6; bootstrap valid; frontend 10/10 |
| 2026-10-24 | 0.5 | `.terraform-version` is the single pin; CI and deploy workflows follow it | `tests/test_workflows.py::test_terraform_version_has_a_single_source_of_truth` |
| 2026-10-24 | 1.2 | `plan`, `apply`, `release` skip until `AWS_DEPLOY_ROLE_ARN` is set | `tests/test_workflows.py::test_aws_jobs_are_skipped_not_failed_until_the_repository_is_configured` |
| 2026-10-24 | 1.3 | Audit and this plan committed under `docs/` | `tests/test_docs.py` |
| 2026-10-24 | 2.1, 2.5 | 19 user stories (`VW-001..019`) with acceptance criteria; every test layer cites the IDs it proves; matrix generated and drift-tested | `tests/test_traceability.py`, `docs/design/traceability.md` |
| 2026-10-24 | 2.2 | `docs/openapi.yaml` (3.1) is the source of truth; JSON Schema is exported from it; handler errors validated against the `Error` schema | `tests/contract/test_openapi.py` |
| 2026-10-24 | 2.3 | Four sequence diagrams with business-error and unexpected-error paths; all four parse and render in Mermaid 11 (checked in a browser) | `tests/test_design_docs.py` |
| 2026-10-24 | 2.4 | 33 Gherkin scenarios (monitoring, alerting, status) run against the real handlers on moto; a threshold mutation fails 2 of them | `tests/step_defs`, `tests/features` |
| 2026-10-24 | 2 gate | 280 tests pass, coverage 94.26%, ruff clean, no uncovered requirement | local run |
| 2026-10-25 | 3.1 | One layer per test, enforced at collection; moto tests moved to `tests/mock`; `pytest -m unit` never imports moto | `tests/test_taxonomy.py` |
| 2026-10-25 | 3.2 | boto3 clients created once per execution environment (3 invocations built 3 resources, now 1); JSON logs with request IDs; ADR 0008 records Powertools, native JSON logs and SnapStart as not adopted. **No speed-up is claimed: it is unmeasured until task 9.3 runs** | `tests/mock/test_client_reuse.py`, `tests/unit/test_logs.py` |
| 2026-10-25 | 3.3 | `repo.py` and `checker.py` split into single-purpose modules with enforced dependency layers; the alert state machine is unit-tested with in-memory fakes; no behaviour change (all earlier tests passed untouched) | `tests/unit/test_architecture.py`, `test_state_machine.py` |
| 2026-10-25 | 3.4 | Typed `AppError`s, stable error `code`, JSON 500 that never leaks internals (**one deliberate behaviour change**: unexpected failures used to be a bare gateway error) | `tests/unit/test_api_errors.py`, `tests/mock/test_error_codes.py` |
| 2026-10-25 | 3.5 | Boundary and hostile-input tests found two real defects, both fixed: unvalidated settings, and a deeply nested JSON body that became a 500 (and could trip the `api-5xx` alarm). Handler-level injection and boundary tests already passed. Test mix is reported in CI | `tests/unit/test_boundaries.py`, `scripts/test_mix.py` |
| 2026-10-25 | 3.6 | E2E harness: `--env` local/dev/prod, addresses only from environment variables, proxies, read-only prod. Run against the local stack: `local` 6 passed; `prod` 4 smoke passed and 2 write tests skipped | `tests/unit/test_e2e_harness.py`, `tests/test_e2e_policy.py` |
| 2026-10-25 | 3.7 | `app.js` is now tested (it was invisible to coverage). Gates: Python 90% (actual 96.6%), frontend lines 90 / functions 90 / branches 80 (actual 97.5 / 100 / 85.5), proven to fail when unmet | `tests/test_quality_gates.py`, `frontend/tests/app.test.js` |
| 2026-10-25 | 3 gate | 486 pytest tests, 18 frontend tests, 10 terraform tests; unit layer 179 tests in 4.2 s; ruff clean | local run |
