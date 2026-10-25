# VigilWatch runbook

Commands assume a shell at the repository root with AWS credentials for the target account.

## 1. Bootstrap (once per AWS account)

The bootstrap stack creates the Terraform state bucket and the GitHub Actions deploy role. It
uses local state because it creates the remote state location. Its state is small and
contains no secrets; keep a copy somewhere safe (password manager or a private store).

1. Enable the region: `af-south-1` is opt-in (Account settings -> AWS Regions).
2. Apply the bootstrap stack:

   ```bash
   terraform -chdir=terraform/bootstrap init
   terraform -chdir=terraform/bootstrap apply
   terraform -chdir=terraform/bootstrap output -raw state_bucket
   terraform -chdir=terraform/bootstrap output -raw deploy_role_arn
   ```

3. Create `terraform/envs/dev/backend.hcl` and `terraform/envs/prod/backend.hcl` from the `backend.hcl.example` next to
   each, with the bucket name. Each environment has its own state key (`vigilwatch/dev.tfstate`, `vigilwatch/prod.tfstate`).
4. In GitHub (Settings -> Secrets and variables -> Actions -> Variables) add:
   `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, `AWS_ACCOUNT_ID` (the only account Terraform may touch; never committed), and
   optionally `NOTIFICATION_EMAIL`.
5. In GitHub (Settings -> Environments) create `production` and add yourself as a required
   reviewer. This is the approval gate before every apply.
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
`NEEDS-AWS`: this procedure has not been run.

1. Back up `terraform/terraform.tfstate`, then pull/merge.
2. Complete the bootstrap above and deploy `dev`, then `prod` (section 3).
3. Re-register your monitored URLs on the new dashboard and confirm the alert email subscription.
4. Retire the old stack from a checkout of the commit it was deployed from (the last commit before this
   branch), with your backed-up state file restored at `terraform/terraform.tfstate`:

   ```bash
   cd terraform
   terraform init
   terraform apply -var dynamodb_deletion_protection=false   # lift table protection first
   terraform plan -destroy                                    # read it: only old-stack resources
   terraform destroy
   ```

5. Delete the local state files once the old stack is gone.

Optional: the old state is still in git history. It holds resource IDs and the account ID, not
credentials. Rewriting history (`git filter-repo`) is possible but not required.

## 3. First deploy (new account)

After bootstrap, either push to `main` (CI -> plan -> approval -> apply), or locally. Build the bundle once;
the same file goes to every environment you deploy:

```bash
python scripts/build_bundle.py          # prints bundle_path and bundle_sha256, writes vigilwatch.tfvars.json
cd terraform/envs/dev                   # start with dev; envs/prod is identical in shape
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan -var-file=../../.build/vigilwatch.tfvars.json -var 'allowed_account_ids=["<your-account-id>"]' -var notification_email=you@example.com
terraform apply tfplan
terraform output dashboard_url
API_URL=$(terraform output -raw api_base_url) DASHBOARD_URL=$(terraform output -raw dashboard_url) \
  pytest -m e2e ../tests/e2e
```

## 4. Day-2 operations

| Task | How |
|---|---|
| See recent checker runs | CloudWatch Logs group `/aws/lambda/vigilwatch-uptime-check` |
| Run the checker now | `aws lambda invoke --function-name "$(terraform -chdir=terraform/envs/prod output -raw checker_function_name)" out.json` |
| Disable a monitored URL | Set `enabled` to false on its item in the `endpoints` table |
| Remove a monitored URL | Delete its item from the `endpoints` table (history expires via TTL). The cap counter (`_system#count` in the same table) is bookkeeping: leave it alone, it repairs itself the next time a registration is rejected as over the limit |
| Change check interval / threshold / cap | Variables `check_interval_minutes`, `failure_threshold`, `max_endpoints`, then plan/apply |
| Inspect failed runs | `aws sqs receive-message --queue-url "$(terraform -chdir=terraform/envs/prod output -raw checker_dlq_url)"` |

## 5. Alarms

All alarms notify the environment's SNS topic (`terraform output sns_topic_arn`). `<env>` is `dev` or `prod`; dev has only the two
alarms that use free Lambda metrics (ADR 0005).

| Alarm | Meaning | First response |
|---|---|---|
| `vigilwatch-<env>-checker-errors` | The checker raised: it could not process at least one endpoint (DynamoDB/SNS error, bug). Endpoint downtime alone never triggers this | Read the checker log group for the stack trace; check DynamoDB throttling metrics |
| `vigilwatch-<env>-checker-not-running` | No checker invocation for 30 minutes. Monitoring is blind | Check the EventBridge rule is enabled, the target exists, and the Lambda permission is present (`terraform plan` shows drift) |
| `vigilwatch-<env>-checker-dlq` | A scheduled run failed and was dead-lettered | Inspect the DLQ message for the error, fix, then purge the queue |
| `vigilwatch-<env>-checker-blind` | Every target failed and none of the control URLs answered: the checker cannot see the internet. Targets are shown INCONCLUSIVE and no target alerts go out meanwhile (ADR 0006). Prod only, because only prod publishes the metric | Check the Lambda has outbound access, then the control URLs in the function environment; the dashboard shows the INCONCLUSIVE pill while it lasts |
| `vigilwatch-<env>-api-5xx` | The public API returned 5 or more server errors in 5 minutes | Check API access logs (`/aws/apigateway/vigilwatch-http`) and the function logs |

## 6. Rollback

- **Application or infrastructure change:** revert the commit on `main` (`git revert <sha>`)
  and push. The pipeline plans the previous configuration and applies it after approval. The
  Lambda bundle is built from the same commit, so code and infrastructure roll back together.
- **Urgent, pipeline unavailable:** check out the last good commit locally and run
  `terraform plan -out=tfplan` then `terraform apply tfplan` with the same backend.
- **Corrupted state:** the state bucket is versioned. List versions with
  `aws s3api list-object-versions --bucket <state bucket> --prefix vigilwatch/prod.tfstate`,
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
