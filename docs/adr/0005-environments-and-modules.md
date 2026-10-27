# ADR 0005: Modules, and two environments in one account

- Status: accepted (2026-10-25)

## Context

The stack was one flat Terraform root. That made three things hard: changing infrastructure safely
(no way to see which part a change touches), proving it (one large test file asserting everything), and
promoting a release (one environment, so "production" was the only place a change could be tried).
Moving resources into modules after the first apply costs a `terraform state mv` per address, so this was
done before any apply.

There is one AWS account and one free tier. Every limit below is shared by everything deployed in it.

## Decision

**Modules.** `terraform/modules/` holds `alerts`, `data`, `compute`, `api`, `frontend` and `monitoring`,
each with validated inputs, outputs and its own `terraform test` suite, and `vigilwatch`, which composes
them into one environment. A test at the module boundary says what that module guarantees; the
composition test says only how they are wired and that two environments cannot collide.

**Environments.** `terraform/envs/dev` and `terraform/envs/prod` are thin roots: a provider, a backend and
one module call, with the values that distinguish them in a committed `terraform.tfvars`. They declare no
resources, which a test enforces. Resource names carry the environment (`vigilwatch-dev-...`), and each has
its own state key.

**No SIT.** A third environment would add alarms beyond the free ten and plumbing for a project with one
maintainer. The owner's approval of the production promotion stands in for a business sign-off.

**Account guard.** The provider takes `allowed_account_ids` from a required variable, so Terraform refuses
to run against any other account whatever credentials are in the shell. The ID is supplied at plan time
(`AWS_ACCOUNT_ID` repository variable) and never committed; a test fails on any 12-digit number in
infrastructure code.

**Build once.** `scripts/build_bundle.py` produces a byte-reproducible zip and its hash. Terraform deploys
that file (`bundle_path`, `bundle_sha256`) rather than zipping at plan time, so production receives the exact
bytes development ran. A promotion that rebuilt could ship something nobody tested.

**Sizing for one free tier.**

| Resource | Free per account | dev | prod | Total |
|---|---|---|---|---|
| DynamoDB provisioned units (per table, two tables each) | 25 | 2 | 5 | 14 |
| CloudWatch alarms | 10 | 2 | 5 | 7 |
| CloudWatch custom metrics (the checker publishes seven) | 10 | 0 | 7 | 7 |

Fourteen custom metrics would cost money, so the checker has a `METRICS_ENABLED` switch and dev turns it off.
That removes dev's `checker-blind` alarm, which alarms on a custom metric. Dev keeps the two alarms that use
free Lambda metrics. A test sums the committed values across both environments, so exceeding any row fails CI.

**Production safety.** Prod tables keep deletion protection. No workflow contains a destroy step; a test
enforces that too. Tearing an environment down is a deliberate local action (runbook section 8).

**Not adopted: a proxy stack for end-to-end tests.** The API Gateway in front of the functions is already the
proxy under test, and the end-to-end harness reaches it only by a configured address.

## Consequences

- Every resource address changed and every name gained an environment. The earlier deployment cannot be
  adopted in place; the runbook retires it instead (section 2).
- Modules call each other in both directions (the API needs the dashboard origin; the dashboard needs the API
  address). Terraform accepts this because the resource graph itself has no cycle, and `terraform validate` in
  CI would reject it if one appeared.
- The same code in dev and prod means dev exercises what prod runs, except where the table above says it does
  not: dev has no custom metrics, so the honest-checker alarm is exercised only in prod. That gap is
  recorded rather than hidden.
- Production no longer accepts browser calls from `http://localhost:3000`: the old single stack allowed it by
  default, and prod sets `extra_cors_origins = []`. Local dashboard work points at dev, which keeps that
  origin. To allow it in prod again, add it to `extra_cors_origins` in `envs/prod/terraform.tfvars`.
- `NEEDS-AWS`: everything here is proven with a mocked provider. Whether the first real apply of both
  environments succeeds is verified in Stage 10.
