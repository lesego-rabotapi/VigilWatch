"""Back up a DynamoDB table to a JSON Lines file: one item per line, in DynamoDB's own typed form.

Point-in-time recovery is not used (it is billed, decision D3), so this logical backup is the way
back from a deleted or damaged endpoints table. History is not backed up: it is TTL data that the
checker rebuilds. The file is lossless (numbers, sets and nulls keep their types) and the same table
always gives the same bytes. It holds the monitored URLs, so keep it out of the repository.

    python scripts/backup_tables.py --table vigilwatch-prod-endpoints --out backups/endpoints.jsonl
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import boto3

SETS = ("SS", "NS", "BS")


def key_names(client, table: str) -> list[str]:
    schema = client.describe_table(TableName=table)["Table"]["KeySchema"]
    return [k["AttributeName"] for k in sorted(schema, key=lambda k: k["KeyType"] != "HASH")]


def canonical(item: dict) -> str:
    """One line per item, independent of the order DynamoDB returned attributes and set members."""
    stable = {
        name: {kind: sorted(v) if kind in SETS else v for kind, v in value.items()}
        for name, value in item.items()
    }
    return json.dumps(stable, sort_keys=True, separators=(",", ":"))


def scan(client, table: str):
    for page in client.get_paginator("scan").paginate(TableName=table, ConsistentRead=True):
        yield from page["Items"]


def backup(table: str, out: Path, client=None) -> int:
    client = client or boto3.client("dynamodb")
    keys = key_names(client, table)
    items = sorted(scan(client, table), key=lambda i: [canonical({k: i[k]}) for k in keys])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    partial.write_text("".join(canonical(i) + "\n" for i in items), encoding="utf-8")
    partial.replace(out)  # a backup that stopped halfway never looks complete
    return len(items)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    count = backup(args.table, args.out)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"backed up {count} items from {args.table} to {args.out} (sha256 {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
