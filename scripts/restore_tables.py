r"""Write a backup made by backup_tables.py back into a DynamoDB table.

Each item is put whole, so restoring twice leaves the same table. Items in the table that are not
in the backup are left alone. The whole file is checked before anything is written (typed values,
key types, no key twice): a damaged backup writes nothing.

The endpoint cap counter (`_system#count`) is not restored: a stale one could be lower than the
real count and let registrations pass the cap. The restore deletes it instead, and the application
rebuilds it from the real item count on the next registration.

    python scripts/restore_tables.py --table vigilwatch-prod-endpoints \
        --from backups/endpoints.jsonl
"""

import argparse
import base64
import binascii
import json
import sys
import time
from pathlib import Path

import boto3

from backup_tables import TYPES

BATCH = 25  # BatchWriteItem's limit
MAX_ATTEMPTS = 8  # about two minutes of backoff before a throttled restore gives up
BOOKKEEPING = "_system#"  # items the application derives, never restored
COUNTER_KEY = {"endpoint_id": {"S": "_system#count"}}


def key_types(client, table: str) -> dict[str, str]:
    """Key attribute name to its type (S, N or B), hash key first."""
    description = client.describe_table(TableName=table)["Table"]
    types = {a["AttributeName"]: a["AttributeType"] for a in description["AttributeDefinitions"]}
    schema = sorted(description["KeySchema"], key=lambda k: k["KeyType"] != "HASH")
    return {k["AttributeName"]: types[k["AttributeName"]] for k in schema}


def decode(value) -> dict:
    """A typed value from the backup, checked, with binary turned back into bytes."""
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in TYPES:
        raise ValueError(f"not a typed DynamoDB value: {value!r}")
    ((kind, inner),) = value.items()
    try:
        if kind == "B":
            return {"B": base64.b64decode(inner, validate=True)}
        if kind == "BS":
            return {"BS": [base64.b64decode(b, validate=True) for b in inner]}
    except (binascii.Error, TypeError):
        raise ValueError(f"binary that is not base64 in a typed value: {value!r}") from None
    if kind == "M":
        return {"M": {k: decode(v) for k, v in inner.items()}}
    if kind == "L":
        return {"L": [decode(v) for v in inner]}
    return value


def read_backup(path: Path, keys: dict[str, str]) -> list[dict]:
    items, seen = [], set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path}, line {number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{where}: not JSON ({error.msg})") from None
        if not isinstance(raw, dict) or not all(k in raw for k in keys):
            raise ValueError(f"{where}: not an item with the key {', '.join(keys)}")
        try:
            item = {name: decode(value) for name, value in raw.items()}
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
        for name, kind in keys.items():
            if next(iter(item[name])) != kind:
                raise ValueError(f"{where}: {name} must be of type {kind}")
        key = tuple(json.dumps(raw[k], sort_keys=True) for k in keys)
        if key in seen:
            raise ValueError(f"{where}: the key {key} appears twice")
        seen.add(key)
        items.append(item)
    return items


def restorable(items: list[dict]) -> list[dict]:
    """Everything but the bookkeeping the application rebuilds itself."""
    return [i for i in items if not i.get("endpoint_id", {}).get("S", "").startswith(BOOKKEEPING)]


def write(client, table: str, items: list[dict], pause: float = 0.5) -> None:
    for start in range(0, len(items), BATCH):
        requests = {table: [{"PutRequest": {"Item": i}} for i in items[start : start + BATCH]]}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            # Provisioned capacity is small (2 to 5 units): unprocessed items are retried slower.
            requests = client.batch_write_item(RequestItems=requests).get("UnprocessedItems")
            if not requests:
                break
            if attempt == MAX_ATTEMPTS:
                left = sum(len(r) for r in requests.values())
                raise RuntimeError(
                    f"{table} still throttled after {MAX_ATTEMPTS} attempts: {left} items not "
                    f"written. Raise its capacity for the restore, or retry when it is quiet"
                )
            time.sleep(min(pause * 2**attempt, 20))


def restore(table: str, path: Path, client=None) -> int:
    client = client or boto3.client("dynamodb")
    keys = key_types(client, table)
    items = restorable(read_backup(path, keys))
    write(client, table, items)
    if list(keys) == list(COUNTER_KEY):
        client.delete_item(TableName=table, Key=COUNTER_KEY)  # rebuilt from the real count
    return len(items)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", required=True)
    parser.add_argument("--from", dest="source", type=Path, required=True)
    args = parser.parse_args(argv)
    count = restore(args.table, args.source)
    print(f"restored {count} items from {args.source} to {args.table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
