"""Prove a backup restores, and time it, without touching the live table.

Creates a scratch table with the source table's key, restores the backup into it, compares the
item count and a sample with the backup, and deletes the scratch table whatever happens. It prints
one row for the drill log in docs/resilience.md; the time is the restore part of the recovery time.
The scratch table uses at most 5 read and 5 write units for a few minutes, inside the free tier
(25 units, 14 used by dev and prod).

    python scripts/restore_drill.py --table vigilwatch-prod-endpoints --from backups/endpoints.jsonl
"""

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import boto3

import restore_tables
from backup_tables import canonical, key_names, scan

MAX_UNITS = 5


@dataclass
class DrillResult:
    scratch: str
    items: int
    sampled: int
    seconds: float
    problems: list[str] = field(default_factory=list)


def choose(items: list[dict], sample: int) -> list[dict]:
    """The same items on every run: evenly spaced through the backup, or all of a small one."""
    if len(items) <= sample:
        return items
    step = len(items) / sample
    return [items[int(n * step)] for n in range(sample)]


def compare(backup: list[dict], restored: list[dict], keys: list[str], sample: int) -> list[str]:
    problems = []
    if len(backup) != len(restored):
        problems.append(f"{len(backup)} items in the backup, {len(restored)} restored")

    def key(item):
        return canonical({k: item[k] for k in keys})

    found = {key(item): canonical(item) for item in restored}
    for item in choose(backup, sample):
        if found.get(key(item)) != canonical(item):
            problems.append(f"item {key(item)} was not restored as backed up")
    return problems


def _scratch_table(client, source: str, name: str) -> None:
    table = client.describe_table(TableName=source)["Table"]
    keys = {k["AttributeName"] for k in table["KeySchema"]}
    units = table.get("ProvisionedThroughput", {})
    client.create_table(
        TableName=name,
        KeySchema=table["KeySchema"],
        AttributeDefinitions=[
            a for a in table["AttributeDefinitions"] if a["AttributeName"] in keys
        ],
        BillingMode="PROVISIONED",
        ProvisionedThroughput={
            "ReadCapacityUnits": min(units.get("ReadCapacityUnits") or MAX_UNITS, MAX_UNITS),
            "WriteCapacityUnits": min(units.get("WriteCapacityUnits") or MAX_UNITS, MAX_UNITS),
        },
    )
    client.get_waiter("table_exists").wait(TableName=name)


def drill(source: str, backup_path: Path, client=None, sample: int = 25) -> DrillResult:
    client = client or boto3.client("dynamodb")
    keys = key_names(client, source)
    items = restore_tables.read_backup(backup_path, keys)
    scratch = f"{source}-drill-{datetime.now(UTC):%Y%m%d%H%M%S}"
    _scratch_table(client, source, scratch)
    try:
        started = time.monotonic()
        restore_tables.write(client, scratch, items)
        seconds = time.monotonic() - started
        restored = list(scan(client, scratch))
    finally:
        client.delete_table(TableName=scratch)
    return DrillResult(
        scratch=scratch,
        items=len(items),
        sampled=len(choose(items, sample)),
        seconds=seconds,
        problems=compare(items, restored, keys, sample),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", required=True, help="the live table the backup came from")
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=25)
    args = parser.parse_args(argv)
    result = drill(args.table, args.source, sample=args.sample)
    for problem in result.problems:
        print(f"drill failed: {problem}")
    digest = hashlib.sha256(args.source.read_bytes()).hexdigest()[:12]
    outcome = "fail" if result.problems else "pass"
    print("| Date | Table | Backup sha256 | Items | Sampled | Restore seconds | Result |")
    print(
        f"| {datetime.now(UTC):%Y-%m-%d} | {args.table} | {digest} | {result.items} "
        f"| {result.sampled} | {result.seconds:.1f} | {outcome} |"
    )
    return 1 if result.problems else 0


if __name__ == "__main__":
    sys.exit(main())
