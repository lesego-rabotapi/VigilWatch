r"""Write a backup made by backup_tables.py back into a DynamoDB table.

Each item is put whole, so restoring twice leaves the same table. Items in the table that are not
in the backup are left alone. The whole file is checked before anything is written: a damaged
backup writes nothing. The endpoint counter (`_system#count`) is restored with the rest; it repairs
itself the next time a registration is refused as over the limit (runbook, section 4).

    python scripts/restore_tables.py --table vigilwatch-prod-endpoints \
        --from backups/endpoints.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

import boto3

from backup_tables import key_names

BATCH = 25  # BatchWriteItem's limit


def read_backup(path: Path, keys: list[str]) -> list[dict]:
    items = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}, line {number}: not JSON ({error.msg})") from None
        if not isinstance(item, dict) or not all(k in item for k in keys):
            raise ValueError(f"{path}, line {number}: not an item with the key {', '.join(keys)}")
        items.append(item)
    return items


def write(client, table: str, items: list[dict], pause: float = 0.5) -> None:
    for start in range(0, len(items), BATCH):
        requests = {table: [{"PutRequest": {"Item": i}} for i in items[start : start + BATCH]]}
        attempt = 0
        while requests:
            # Provisioned capacity is small (2 to 5 units): unprocessed items are retried slower.
            requests = client.batch_write_item(RequestItems=requests).get("UnprocessedItems")
            if requests:
                attempt += 1
                time.sleep(min(pause * 2**attempt, 20))


def restore(table: str, path: Path, client=None) -> int:
    client = client or boto3.client("dynamodb")
    items = read_backup(path, key_names(client, table))
    write(client, table, items)
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
