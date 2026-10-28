# Resilience

What can fail, how each failure is noticed, and how to recover. The recovery time (RTO) and the data
that can be lost (RPO) below are **targets**, not measured: `NEEDS-AWS` until the drill log at the end
has a row and the first incidents have been timed. The drill measures only the restore step of the
endpoints table.

## What is backed up, and what is not

| Data | Protection | Notes |
|---|---|---|
| Endpoints table (the monitored URLs, their state, the cap counter) | Logical backup with `scripts/backup_tables.py`, taken by hand; deletion protection on prod's tables | Take one after changing the list, and weekly. Keep it outside the repository (`backups/` is ignored): it holds the URLs |
| History table (raw checks, daily rollups, incidents) | None, deliberately | TTL data: raw checks expire after 48 h and rollups and incidents after 31 d. After a loss the checker refills it, and the uptime percentages restart |
| Terraform state | Versioned S3 bucket | Restore an earlier version (runbook, section 6) |
| Code and bundles | Git, and `bundles/<sha>.zip` in the state bucket | Every release is recorded in `releases/history/<env>/<sha>` |

**No point-in-time recovery (decision D3).** DynamoDB point-in-time recovery is billed for every GB
it keeps and has no free tier, and export to S3 requires it. The project stays at $0, so the endpoints
table is protected by deletion protection in prod and the logical backup instead. The cost is the RPO:
whatever changed since the last backup. The table holds at most 50 small items, so a backup takes
seconds and can be taken often.

## Failure modes

| Failure | Detected by | Recovery | RTO target | RPO target |
|---|---|---|---|---|
| The endpoints table is deleted or damaged | API errors (`vigilwatch-<env>-api-5xx`), checker errors (`vigilwatch-<env>-checker-errors`) | `terraform apply` recreates an empty table; then `scripts/restore_tables.py` from the latest backup | 1 hour | The last backup |
| The history table is lost | The dashboard shows no history while the checker keeps running | `terraform apply` recreates it; the checker refills it | 15 minutes to resume checking | All history (accepted: it is TTL data) |
| The checker stops running (rule disabled, permission removed) | `vigilwatch-<env>-checker-not-running` | Runbook, section 5; `terraform apply` restores the rule and the permission | 30 minutes | None restored: missed checks are not backfilled |
| The checker cannot reach the internet | `vigilwatch-<env>-checker-blind` (prod only) | Targets show INCONCLUSIVE and no false alerts go out (ADR 0006); fix the function's outbound access | 15 minutes after the cause is fixed | None |
| A scheduled run fails | `vigilwatch-<env>-checker-dlq` | Read the dead-lettered message, fix the cause, purge the queue | 1 hour | That run's checks |
| The API returns server errors | `vigilwatch-<env>-api-5xx`, the dashboard, the `api-5xx` saved query | Read the function logs; if a deploy caused it, roll back | 30 minutes | None |
| A bad deploy | The smoke test fails before the release is recorded; the alarms above | `rollback.yml` with the previous release's commit (runbook, section 6) | 30 minutes, including the approval | None: code and configuration only |
| Terraform state is damaged or deleted | `terraform plan` fails or wants to recreate everything | Restore the previous object version (runbook, section 6) | 1 hour | The last apply |
| The region (af-south-1) is down | Everything at once; the alarms are in the same region and may stay silent | Single region by design (ADR 0006). Wait, or bootstrap and apply in another region and restore the latest backup | 1 day, by hand | The last backup |

## Back up, restore and drill

```bash
python scripts/backup_tables.py --table vigilwatch-prod-endpoints --out backups/endpoints-$(date +%F).jsonl
python scripts/restore_tables.py --table vigilwatch-prod-endpoints --from backups/endpoints-2026-10-28.jsonl
python scripts/restore_drill.py --table vigilwatch-prod-endpoints --from backups/endpoints-2026-10-28.jsonl
```

- The backup is one item per line in DynamoDB's typed JSON, so numbers, sets and nulls survive. The same
  table always gives the same bytes, and the command prints the file's SHA-256.
- The restore checks the whole file before writing, puts whole items (restoring twice changes nothing), and
  leaves items that are not in the backup alone.
- The drill never touches the live table. It restores into a scratch table named
  `<table>-drill-<timestamp>`, compares the item count and a fixed sample with the backup, prints the
  time the restore took, and deletes the scratch table even when something fails. The scratch table uses
  at most 5 read and 5 write units for a few minutes, inside the free tier (dev and prod use 14 of 25).

Run a drill after the first prod deploy, then every quarter and after any change to the scripts or the
table, and paste its last line into the log below.

## Drill log

`NEEDS-AWS`: no drill has run yet. Paste each drill's printed row under this header, newest last. A
failed drill is logged too.

| Date | Table | Backup sha256 | Items | Sampled | Restore seconds | Result |
|---|---|---|---|---|---|---|
