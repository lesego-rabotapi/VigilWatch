r"""Write a backup made by backup_tables.py back into a DynamoDB table.

Each item is put whole, so restoring twice leaves the same table. Items in the table that are not
in the backup are left alone. The whole file is checked before anything is written (typed values,
key types, no key twice): a damaged backup writes nothing.

Items the application keeps for itself (ids starting with `_`, such as the cap counter) are not
restored: a stale counter could be lower than the real count and let registrations pass the cap.
After writing, the restore sets the live counter to the real count with the application's own
repair. Pause registrations while a restore runs: one landing before that repair counts against a
partly restored table and could pass the cap.

    python scripts/restore_tables.py --table vigilwatch-prod-endpoints \
        --from backups/endpoints.jsonl
"""

import argparse
import base64
import binascii
import json
import re
import sys
import time
from decimal import Context, Decimal, InvalidOperation
from pathlib import Path

import boto3

from backup_tables import TYPES

# The application's own rules for its bookkeeping items, so the two cannot drift apart.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))
from common.endpoints_repo import _RESERVED_PREFIX, EndpointRepository  # noqa: E402

BATCH = 25  # BatchWriteItem's limit
MAX_ATTEMPTS = 8  # about 70 seconds of backoff per batch before a throttled restore gives up


def key_types(client, table: str) -> dict[str, str]:
    """Key attribute name to its type (S, N or B), hash key first."""
    description = client.describe_table(TableName=table)["Table"]
    types = {a["AttributeName"]: a["AttributeType"] for a in description["AttributeDefinitions"]}
    schema = sorted(description["KeySchema"], key=lambda k: k["KeyType"] != "HASH")
    return {k["AttributeName"]: types[k["AttributeName"]] for k in schema}


_EXACT = Context(prec=100)  # the default 28 digits would round before the 38-digit check
_NUMBER = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")


def _number(text) -> Decimal:
    """A DynamoDB number: plain notation, at most 38 significant digits, 1E-130 to 1E126."""
    if not isinstance(text, str) or not _NUMBER.fullmatch(text):
        raise ValueError
    number = Decimal(text)
    digits = number.normalize(_EXACT).as_tuple().digits
    if number and (len(digits) > 38 or not -130 <= number.adjusted() <= 125):
        raise ValueError
    return number


def _distinct(members) -> list:
    if len(set(members)) != len(members):
        raise ValueError  # a set holds each member once
    return members


def _binary(text) -> bytes:
    if not isinstance(text, str):
        raise ValueError
    return base64.b64decode(text, validate=True)


def decode(value) -> dict:
    """A typed value from the backup, checked as DynamoDB would, with binary back to bytes."""
    try:
        if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in TYPES:
            raise ValueError
        ((kind, inner),) = value.items()
        if kind in ("SS", "NS", "BS") and (not isinstance(inner, list) or not inner):
            raise ValueError  # a set is a non-empty list
        if kind == "S" and isinstance(inner, str):
            return value
        if kind == "N":
            _number(inner)
            return value
        if kind == "SS" and all(isinstance(s, str) for s in inner):
            _distinct(inner)
            return value
        if kind == "NS":
            _distinct([_number(n).normalize(_EXACT) for n in inner])
            return value
        if kind == "B":
            return {"B": _binary(inner)}
        if kind == "BS":
            return {"BS": _distinct([_binary(b) for b in inner])}
        if kind == "M" and isinstance(inner, dict):
            return {"M": {k: decode(v) for k, v in inner.items()}}
        if kind == "L" and isinstance(inner, list):
            return {"L": [decode(v) for v in inner]}
        if (kind == "NULL" and inner is True) or (kind == "BOOL" and isinstance(inner, bool)):
            return value
    except (ValueError, InvalidOperation, binascii.Error):
        pass
    raise ValueError(f"not a typed DynamoDB value: {value!r}")


def _key_value(value: dict):
    """A key as DynamoDB compares it: 1 and 1.0 are the same number."""
    ((kind, inner),) = value.items()
    return (kind, _number(inner).normalize(_EXACT) if kind == "N" else inner)


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
            if item[name][kind] in ("", b""):
                raise ValueError(f"{where}: {name} is empty, which no key may be")
        key = tuple(_key_value(item[k]) for k in keys)
        if key in seen:
            raise ValueError(f"{where}: the key {key} appears twice")
        seen.add(key)
        items.append(item)
    return items


def restorable(items: list[dict], keys: dict[str, str]) -> list[dict]:
    """In the endpoints table, everything but the application's own bookkeeping (ids starting with
    `_`). Other tables, such as history and its `_system` heartbeat, are restored whole."""
    if list(keys) != ["endpoint_id"]:
        return items
    return [i for i in items if not i["endpoint_id"].get("S", "").startswith(_RESERVED_PREFIX)]


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
    items = restorable(read_backup(path, keys), keys)
    write(client, table, items)
    if list(keys) == ["endpoint_id"]:
        # The same region and endpoint as the client the restore was given.
        dynamodb = boto3.resource(
            "dynamodb", region_name=client.meta.region_name, endpoint_url=client.meta.endpoint_url
        )
        EndpointRepository(dynamodb.Table(table)).repair_counter()
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
