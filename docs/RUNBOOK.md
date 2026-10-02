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

3. Create `terraform/backend.hcl` from `terraform/backend.hcl.example` with the bucket name.
4. In GitHub (Settings -> Secrets and variables -> Actions -> Variables) add:
   `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`, and optionally `NOTIFICATION_EMAIL`.
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

The new configuration keeps the same Terraform addresses (and names) for the S3 bucket, its
policy and public-access block, and the CloudFront distribution, so those are updated in place
and the dashboard URL stays the same. The SNS topic and the EventBridge rule keep their
addresses but are renamed, so Terraform replaces them. Everything else from the old stack (REST
API resources, the old Lambdas, the old shared IAM role, the old check table and seed item, the
unused VPC, the OAI and the S3 website configuration) is no longer in the configuration, so
Terraform destroys it.

1. Back up `terraform/terraform.tfstate`, then pull/merge.
2. Complete the bootstrap above.
3. Put the backed-up state file back at `terraform/terraform.tfstate`, then move it into S3:

   ```bash
   cd terraform
   terraform init -backend-config=backend.hcl -migrate-state
   terraform state list          # now read from S3
   ```

4. Plan and **read the plan**. Expect destroys only for old-stack resources:

   ```bash
   terraform plan -out=tfplan -var notification_email=you@example.com
   terraform apply tfplan
   ```

5. Remove the local copies of the state once `terraform state list` works from S3.
6. The API URL changes (HTTP API replaces the REST API). The dashboard picks up the new URL
   from the generated `config.js`; nothing to edit by hand.
7. Monitored URLs are not migrated (the old table only held a seed row). Re-register them
   from the dashboard.
8. If you set `notification_email`, confirm the subscription from the email AWS sends.

Optional: the old state is still in git history. It holds resource IDs and the account ID, not
credentials. Rewriting history (`git filter-repo`) is possible but not required.

## 3. First deploy (new account)

After bootstrap, either push to `main` (CI -> plan -> approval -> apply), or locally:

```bash
cd terraform
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan -var notification_email=you@example.com
terraform apply tfplan
terraform output dashboard_url
API_URL=$(terraform output -raw api_base_url) DASHBOARD_URL=$(terraform output -raw dashboard_url) \
  pytest -m e2e ../tests/e2e
```

## 4. Day-2 operations

| Task | How |
|---|---|
| See recent checker runs | CloudWatch Logs group `/aws/lambda/vigilwatch-uptime-check` |
| Run the checker now | `aws lambda invoke --function-name "$(terraform -chdir=terraform output -raw checker_function_name)" out.json` |
| Disable a monitored URL | Set `enabled` to false on its item in the `endpoints` table |
| Remove a monitored URL | Delete its item from the `endpoints` table (history expires via TTL) |
| Change check interval / threshold / cap | Variables `check_interval_minutes`, `failure_threshold`, `max_endpoints`, then plan/apply |
| Inspect failed runs | `aws sqs receive-message --queue-url "$(terraform -chdir=terraform output -raw checker_dlq_url)"` |

## 5. Alarms

All alarms notify the SNS topic (`terraform output sns_topic_arn`).

| Alarm | Meaning | First response |
|---|---|---|
| `vigilwatch-checker-errors` | The checker raised: it could not process at least one endpoint (DynamoDB/SNS error, bug). Endpoint downtime alone never triggers this | Read the checker log group for the stack trace; check DynamoDB throttling metrics |
| `vigilwatch-checker-not-running` | No checker invocation for 30 minutes. Monitoring is blind | Check the EventBridge rule is enabled, the target exists, and the Lambda permission is present (`terraform plan` shows drift) |
| `vigilwatch-checker-dlq` | A scheduled run failed and was dead-lettered | Inspect the DLQ message for the error, fix, then purge the queue |
| `vigilwatch-api-5xx` | The public API returned 5 or more server errors in 5 minutes | Check API access logs (`/aws/apigateway/vigilwatch-http`) and the function logs |

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

- DynamoDB stays **provisioned** (`dynamodb_capacity` <= 12 per table is enforced by validation and tests).
- Keep CloudWatch alarms at 10 or fewer and metrics low-cardinality (no per-URL dimensions).
- Log retention is 14 days at most (validated).
- `max_endpoints` (<= 50, default 10) bounds checker runtime, writes and outbound requests.
- API throttling (`api_throttle_rate`, `api_throttle_burst`) bounds request charges after the
  first year.
- The zero-spend budget from the bootstrap section emails you if anything starts costing money.

## 8. Teardown

```bash
cd terraform
terraform apply -var dynamodb_deletion_protection=false   # lift table protection first
terraform destroy
```

The bootstrap stack's state bucket has `prevent_destroy`. Remove that line deliberately if you
really want to delete it.
