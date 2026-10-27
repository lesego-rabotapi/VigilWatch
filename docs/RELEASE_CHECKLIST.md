# Release checklist

Every deploy prints the matching section into its GitHub job summary (`scripts/checklist.py`):
the pre-deployment list with the plan, the post-deployment list after the smoke test. The
pipeline enforces the items marked (enforced); the rest are for the person approving or checking.

## Pre-deployment

- [ ] CI passed on this commit: lint, unit, mock, contract and policy tests, `terraform test` for every module and environment, frontend tests, secret and IaC scans (enforced: deploy-dev runs `ci.yml` first).
- [ ] The commit is on `main` (enforced), and for prod it is the commit dev last released, `releases/dev` in the state bucket (enforced by promote-prod).
- [ ] The bundle hash in the summary is the one dev deployed: prod fetches `bundles/<sha>.zip`, never rebuilds (enforced).
- [ ] Read the plan. Nothing is destroyed or replaced that should not be; prod's DynamoDB tables keep deletion protection (enforced by `terraform test`) and show no replacement.
- [ ] The plan does not remove the alert email subscription: `NOTIFICATION_EMAIL` is set.
- [ ] Free tier still holds: at most 25 DynamoDB units, 10 alarms and 10 custom metrics across both environments (enforced by the free-tier tests).
- [ ] Prod only: the previous release's commit is known, so `rollback.yml` can be run at once if needed.

## Post-deployment

- [ ] The smoke test ran every expected test and skipped none (enforced: `scripts/check_junit.py`).
- [ ] Prod only: `E2E_READONLY_URL` is set and its checks were returned by the API.
- [ ] The dashboard loads and shows recent checks for a known URL.
- [ ] The checker ran in the last 10 minutes: its heartbeat is fresh and the `checker-not-running` alarm is OK.
- [ ] No VigilWatch alarm is in ALARM state (`aws cloudwatch describe-alarms --state-value ALARM --alarm-name-prefix vigilwatch-`).
- [ ] The release is recorded in `releases/<environment>` (enforced); for prod, the release tag exists.
- [ ] If anything above fails on prod, run `rollback.yml` with the previous release's commit (docs/RUNBOOK.md, section 6).
