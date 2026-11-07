"""Back up a DynamoDB table to a JSON Lines file: one item per line, in DynamoDB's own typed form.

Point-in-time recovery is not used (it is billed, decision D3), so this logical backup is the way
back from a deleted or damaged endpoints table. History is not backed up: it is TTL data that the
checker rebuilds. The file is lossless (numbers, sets, binary and nulls keep their types; binary is
base64) and the same table always gives the same bytes, on any platform. It holds the monitored
URLs, so keep it out of the repository.

    python scripts/backup_tables.py --table vigilwatch-prod-endpoints --out backups/endpoints.jsonl
"""

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import boto3

TYPES = {"S", "N", "B", "SS", "NS", "BS", "M", "L", "NULL", "BOOL"}


def key_names(client, table: str) -> list[str]:
    schema = client.describe_table(TableName=table)["Table"]["KeySchema"]
    return [k["AttributeName"] for k in sorted(schema, key=lambda k: k["KeyType"] != "HASH")]


def encode(value: dict) -> dict:
    """A typed value as JSON: binary as base64, sets sorted, at every depth."""
    ((kind, inner),) = value.items()
    if kind == "B":
        return {"B": base64.b64encode(inner).decode()}
    if kind == "BS":
        return {"BS": sorted(base64.b64encode(b).decode() for b in inner)}
    if kind in ("SS", "NS"):
        return {kind: sorted(inner)}
    if kind == "M":
        return {"M": {k: encode(v) for k, v in inner.items()}}
    if kind == "L":
        return {"L": [encode(v) for v in inner]}
    return {kind: inner}


def canonical(item: dict) -> str:
    """One line per item, independent of the order DynamoDB returned attributes and set members."""
    return json.dumps(
        {k: encode(v) for k, v in item.items()}, sort_keys=True, separators=(",", ":")
    )


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
    partial.write_bytes("".join(canonical(i) + "\n" for i in items).encode("utf-8"))  # LF anywhere
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
