# Interview notes

The questions a reviewer is most likely to ask, each answered briefly with a link to the evidence. Evidence
tags: `CI` (a pipeline job proves it), `MOCK` (a test against a simulated AWS), `REPO` (a document or file),
`NEEDS-AWS` (not provable until deployed).

### Why serverless, and why these services?
No servers to patch and nothing running between checks, which fits a job that wakes every five minutes.
HTTP API, provisioned DynamoDB and Lambda on arm64 were each picked because the cheaper option was also the simpler one.
Each choice has a decision record with the alternative that lost. `REPO`
See [ADR 0001](adr/0001-http-api-over-rest-api.md) and [ADR 0002](adr/0002-provisioned-dynamodb-with-rollups.md).

### How do you know it stays inside the free tier?
Capacity, alarms, metrics and dashboards of both environments are added up against one account's allowance.
The script fails CI if the sum goes over, so a new alarm cannot slip past unnoticed.
API Gateway and S3 are the only lines that can cost money after the first year, and both are bounded. `CI`
See [free_tier_budget.py](../scripts/free_tier_budget.py) and the cost table in the [README](../README.md#cost).

### Why not tag every metric with the URL being checked?
Each distinct dimension value is a separate billed metric, so the bill would grow with every URL anyone registers.
With one dimension the count is fixed at seven. At 100 URLs the other design costs $27.00 a month, at 1,000 it costs $297.00.
Those figures are computed from the list price, not measured. `REPO`
See [ADR 0003](adr/0003-emf-metrics-without-per-endpoint-dimensions.md) and [cardinality_cost.py](../scripts/cardinality_cost.py).

### What stops the monitor from reporting false outages?
If every target fails, the checker probes control URLs. When none answers, results are INCONCLUSIVE.
Nothing is counted, no incident opens, no alert is sent, and an alarm tells the owner the checker is blind.
Every row of the decision table is a test. `MOCK`
See [ADR 0006](adr/0006-checker-honesty.md).

### How do you prevent server-side request forgery?
Only http and https, no credentials in the URL, and every resolved address must be globally routable.
The check runs at registration and again before every probe, because DNS can change in between.
Redirects are never followed. The residual DNS-rebinding window is written down as an accepted risk. `MOCK`
See [ADR 0004](adr/0004-zero-cost-security-tradeoffs.md) and [urlguard.py](../lambda/common/urlguard.py).

### How does sign-in work, and what does it not protect?
Cognito with a JWT authorizer on both routes, the code flow with PKCE, and the token kept in memory only.
Each user sees only their own endpoints, and the id includes the owner, so a wrong owner gets a 404.
The login flow itself cannot be proven offline. `NEEDS-AWS`
See [ADR 0007](adr/0007-authentication.md) and [security.md](security.md).

### How does a change reach production?
The commit is built once, dev deploys it, and the smoke test records the release.
Prod deploys only a commit dev released, with the exact stored bundle, after a reviewer approves. No workflow can destroy anything.
Rollback redeploys an earlier released commit through the same gates. `CI`
See [ADR 0009](adr/0009-pipeline-and-promotion.md) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

### How do you test infrastructure without an AWS account?
`terraform test` runs every module and environment against a mocked provider, asserting what each guarantees.
Policy tests read the workflow files and fail on a wildcard action or an account id in code.
The exact IAM policies are enforced against each handler under a simulated AWS. `MOCK`
See [ADR 0005](adr/0005-environments-and-modules.md) and the [audit](AUDIT_AND_ROADMAP.md).

### What happens if the endpoints table is lost?
Deletion protection guards prod. A logical backup restores the table, and the history refills by itself because it is TTL data.
Point-in-time recovery was rejected as it is billed, so the recovery point is the last backup.
The recovery times are targets until the restore drill has been run. `NEEDS-AWS`
See [resilience.md](resilience.md).

### What is proven, and what is not?
Everything is tagged. Every layer of tests runs in CI on every change. Anything that needs a real account is marked and listed.
The first deployment will produce IAM and logging iterations that are expected, and they are logged when they happen. `NEEDS-AWS`
See the [roadmap](AUDIT_AND_ROADMAP.md) and [performance.md](performance.md).
