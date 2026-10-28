# VigilWatch runbook

Commands assume a shell at the repository root with AWS credentials for the target account.

## 1. Bootstrap (once per AWS account)

The bootstrap stack creates the Terraform state bucket (which also holds the built bundles and the
release records), the GitHub Actions deploy role and a read-only plan role. It
uses local state because it creates the remote state location. Its state is small and
contains no secrets; keep a copy somewhere safe (password manager or a private store).

1. Enable the region: `af-south-1` is opt-in (Account settings -> AWS Regions).
2. Apply the bootstrap stack:

   ```bash
   terraform -chdir=terraform/bootstrap init
   terraform -chdir=terraform/bootstrap apply
   terraform -chdir=terraform/bootstrap output -raw state_bucket
   terraform -chdir=terraform/bootstrap output -raw deploy_role_arn
   terraform -chdir=terraform/bootstrap output -raw plan_role_arn
   ```

3. Create `terraform/envs/dev/backend.hcl` and `terraform/envs/prod/backend.hcl` from the `backend.hcl.example` next to
   each, with the bucket name. Each environment has its own state key (`vigilwatch/envs/dev.tfstate`, `vigilwatch/envs/prod.tfstate`).
4. In GitHub (Settings -> Secrets and variables -> Actions -> Variables) add:
   `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, `AWS_ACCOUNT_ID` (the only account Terraform may touch; never committed),
   `AWS_PLAN_ROLE_ARN` (pull request plans and the drift check; without it they are skipped), and
   optionally `NOTIFICATION_EMAIL`. After the first prod deploy, register one URL on the prod dashboard and add it as
   `E2E_READONLY_URL`. Prod's smoke test is read-only, so it reads that URL back instead of registering one. It fails
   without it, so the first prod smoke job is expected to fail with that message: set the variable, then re-run only
   the smoke job (it has no AWS access and does not apply anything again).
5. In GitHub (Settings -> Environments) create `production`, add yourself as a required
   reviewer (the approval gate before every prod apply), and under Deployment branches and tags
   choose "Selected branches and tags" with the single rule `main`. The deploy role trusts `main`
   and this environment only. A job can name an environment from any branch, so the reviewer and
   the branch rule are what keep the write role away from unreviewed code. Dev applies run as
   `main` in no environment; do not create another environment for them.
6. Cost backstop: in AWS Billing -> Budgets, create a budget from the "Zero spend budget"
   template. Two budgets are free.

## 2. Migrating an existing deployment

Read this before merging if you have the earlier stack deployed (REST API, local state).

> **Back up your state first.** Earlier commits tracked `terraform/terraform.tfstate` in git.
> This branch stops tracking it, so when you pull or merge it, **git deletes that file from
> your working tree.** Copy `terraform/terraform.tfstate` (and `.backup`) somewhere outside the
> repository *before* you pull.

The earlier stack cannot be adopted in place: every resource now lives inside a module (a new Terraform
address) and carries the environment in its name (`vigilwatch-prod-...`). Moving each of them with
`terraform state mv` and renaming live resources would be riskier than starting clean, and there is
almost nothing to carry over (the old table held a single seed row; monitored URLs are re-registered).
So the new environments are created next to the old stack, and the old stack is retired afterwards.
The environments use state keys under `vigilwatch/envs/`, which no earlier pipeline wrote. A state object directly under `vigilwatch/` in
the state bucket belongs to the old stack: leave it alone until step 4.
`NEEDS-AWS`: this procedure has not been run.

1. Back up `terraform/terraform.tfstate`, then pull/merge.
2. Complete the bootstrap above and deploy `dev`, then `prod` (section 3).
3. Re-register your monitored URLs on the new dashboard and confirm the alert email subscription.
4. Retire the old stack from a checkout of the commit it was deployed from (the last commit before this
   branch), with your backed-up state file restored at `terraform/terraform.tfstate`:

   ```bash
   cd terraform
   terraform init
   terraform plan -destroy    # read it: only old-stack resources (its tables were never protected)
   terraform destroy
   ```

5. Delete the local state files once the old stack is gone.

Optional: the old state is still in git history. It holds resource IDs and the account ID, not
credentials. Rewriting history (`git filter-repo`) is possible but not required.

## 3. First deploy (new account)

**Through the pipeline (the normal path).** Every pull request gets a read-only dev plan as a comment
(`pr-plan.yml`). Merging to `main` deploys dev (`deploy-dev.yml`): CI, then the commit's bundle is built
and stored as `bundles/<sha>.zip` in the state bucket, planned, applied, smoke-tested, and recorded in
`releases/dev`. To ship it, run **Promote to prod** (Actions -> Promote to prod -> Run workflow) with
the commit field empty: it deploys the commit in `releases/dev` with the stored bundle, never a
rebuild, waits for your approval on the `production` environment, runs the read-only smoke test,
records `releases/prod` and tags a release with its changelog. Each run's summary shows the release
checklist (docs/RELEASE_CHECKLIST.md).

**Locally** (before the pipeline is configured). Build the bundle once; the same file goes to every
environment you deploy:

```bash
python scripts/build_bundle.py          # prints bundle_path and bundle_sha256, writes vigilwatch.tfvars.json
cd terraform/envs/dev                   # start with dev; envs/prod is identical in shape
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan -var-file=../../.build/vigilwatch.tfvars.json -var 'allowed_account_ids=["<your-account-id>"]' -var notification_email=you@example.com
terraform apply tfplan
terraform output dashboard_url
API_URL_DEV=$(terraform output -raw api_base_url) DASHBOARD_URL_DEV=$(terraform output -raw dashboard_url) \
  pytest -m e2e ../../../tests/e2e --env=dev
```

## 4. Day-2 operations

| Task | How |
|---|---|
| See recent checker runs | CloudWatch Logs group `/aws/lambda/vigilwatch-<env>-uptime-check` |
| Run the checker now | `aws lambda invoke --function-name "$(terraform -chdir=terraform/envs/prod output -raw checker_function_name)" out.json` |
| Disable a monitored URL | Set `enabled` to false on its item in the `endpoints` table |
| Remove a monitored URL | Delete its item from the `endpoints` table (history expires via TTL). The cap counter (`_system#count` in the same table) is bookkeeping: leave it alone, it repairs itself the next time a registration is rejected as over the limit |
| Change check interval / thresholds / cap / throttling | Set `check_interval_minutes`, `failure_threshold`, `recovery_threshold`, `reminder_minutes`, `max_endpoints`, `api_throttle_rate` or `api_throttle_burst` in that environment's `terraform.tfvars` (unset means the module default), then plan/apply in `terraform/envs/<env>` |
| Inspect failed runs | `aws sqs receive-message --queue-url "$(terraform -chdir=terraform/envs/prod output -raw checker_dlq_url)"` |
| A "Infrastructure drift detected" issue | The weekly `drift.yml` found a resource that differs from its state (a console change). Read the plan in the issue, then either put the change into code and deploy it, or undo it by redeploying the released commit (`rollback.yml` with the commit in `releases/prod`). Close the issue once the next drift run is clean |
| Which commit runs where | `aws s3 cp s3://<state bucket>/releases/dev -` (and `releases/prod`): the commit, then the SHA-256 of its bundle |

## 5. Alarms

All alarms notify the environment's SNS topic (`terraform output sns_topic_arn`). `<env>` is `dev` or `prod`; dev has only the two
alarms that use free Lambda metrics (ADR 0005).

| Alarm | Meaning | First response |
|---|---|---|
| `vigilwatch-<env>-checker-errors` | The checker raised: it could not process at least one endpoint (DynamoDB/SNS error, bug). Endpoint downtime alone never triggers this | Read the checker log group for the stack trace; check DynamoDB throttling metrics |
| `vigilwatch-<env>-checker-not-running` | No checker invocation for 30 minutes. Monitoring is blind | Check the EventBridge rule is enabled, the target exists, and the Lambda permission is present (`terraform plan` shows drift) |
| `vigilwatch-<env>-checker-dlq` | A scheduled run failed and was dead-lettered | Inspect the DLQ message for the error, fix, then purge the queue |
| `vigilwatch-<env>-checker-blind` | Every target failed and none of the control URLs answered: the checker cannot see the internet. Targets are shown INCONCLUSIVE and no target alerts go out meanwhile (ADR 0006). Prod only, because only prod publishes the metric | Check the Lambda has outbound access, then the control URLs in the function environment; the dashboard shows the INCONCLUSIVE pill while it lasts |
| `vigilwatch-<env>-api-5xx` | The public API returned 5 or more server errors in 5 minutes | Check API access logs (`/aws/apigateway/vigilwatch-<env>-http`) and the function logs |

## 6. Rollback

- **Prod, fastest:** run **Roll back prod** (`rollback.yml`) with the full commit id of the last good
  release (`git rev-list -n 1 v2.<n>`). It redeploys that commit's Terraform and the bundle dev
  stored for it, through the same plan, `production` approval and smoke test, and records it in
  `releases/prod`. Code and infrastructure roll back together. Then fix forward on `main`.
- **Through main:** revert the commit (`git revert <sha>`) and push. Dev deploys the revert;
  promote it as usual.
- **Urgent, pipeline unavailable:** check out the last good commit locally, rebuild its bundle and
  apply it from the environment directory with the same backend. Pass the alert address the
  pipeline uses (`NOTIFICATION_EMAIL`): without it the plan deletes the email subscription.

  ```bash
  python scripts/build_bundle.py
  cd terraform/envs/prod
  terraform init -backend-config=backend.hcl
  terraform plan -out=tfplan -var-file=../../.build/vigilwatch.tfvars.json -var 'allowed_account_ids=["<your-account-id>"]' -var notification_email=you@example.com
  terraform apply tfplan
  ```
- **Corrupted state:** the state bucket is versioned. List versions with
  `aws s3api list-object-versions --bucket <state bucket> --prefix vigilwatch/envs/prod.tfstate`,
  then restore by copying the last good version over the current object. Run `terraform plan`
  and confirm it shows no unexpected changes before applying anything.
- **Stuck lock:** with S3 native locking the lock is a `.tflock` object next to the state.
  Confirm no apply is running (check Actions), then `terraform force-unlock <LOCK_ID>`.

## 7. Cost guardrails

- DynamoDB stays **provisioned**. Both environments share one 25-unit free tier: dev uses 2 per table and prod 5, and a test sums the committed values across environments.
- Keep CloudWatch alarms at 10 or fewer **in total** (dev has 2, prod 5) and metrics low-cardinality (no per-URL dimensions). Ten custom metrics are free and one
  environment publishes seven, so only prod does (`metrics_enabled = false` in dev).
- Log retention is 14 days at most (validated).
- `max_endpoints` (<= 50, default 10) bounds checker runtime, writes and outbound requests.
- API throttling (`api_throttle_rate`, `api_throttle_burst`) bounds request charges after the
  first year.
- The zero-spend budget from the bootstrap section emails you if anything starts costing money.

## 8. Teardown

```bash
cd terraform/envs/dev                    # development can be torn down; prod keeps its protection
terraform apply -var-file=../../.build/vigilwatch.tfvars.json -var 'allowed_account_ids=["<your-account-id>"]' -var dynamodb_deletion_protection=false   # lift table protection first
terraform destroy -var-file=../../.build/vigilwatch.tfvars.json -var 'allowed_account_ids=["<your-account-id>"]'
```

No workflow runs `terraform destroy`: tearing an environment down is always a deliberate local action.

The bootstrap stack's state bucket has `prevent_destroy`. Remove that line deliberately if you
really want to delete it.
