"""The endpoints table: one item per monitored URL (partition key endpoint_id).

The endpoint cap is enforced with a counter item (`_system#count`) in the same table. Creating an
endpoint and incrementing the counter happen in one DynamoDB transaction whose condition is
"counter below the cap", so concurrent registrations cannot overshoot: DynamoDB serialises them.
The counter is bookkeeping, not data: counting and listing skip it, and if it drifts (an item
deleted by hand, or a table that predates the counter) it is rebuilt from the real item count.
"""

from datetime import datetime

from botocore.exceptions import ClientError

from common.dynamo import plain
from common.timefmt import iso

COUNTER_ID = "_system#count"
_RESERVED_PREFIX = "_"


class EndpointLimitReached(Exception):
    pass


def _is_endpoint(item: dict) -> bool:
    return not item["endpoint_id"].startswith(_RESERVED_PREFIX)


class EndpointRepository:
    def __init__(self, table):
        self.table = table

    def get(self, endpoint_id: str) -> dict | None:
        item = self.table.get_item(Key={"endpoint_id": endpoint_id}).get("Item")
        return plain(item) if item else None

    def count(self) -> int:
        """Number of real endpoints. Strongly consistent: it feeds the cap's repair path."""
        total, kwargs = (
            0,
            {
                "Select": "COUNT",
                "ConsistentRead": True,
                "FilterExpression": "NOT begins_with(endpoint_id, :reserved)",
                "ExpressionAttributeValues": {":reserved": _RESERVED_PREFIX},
            },
        )
        while True:
            page = self.table.scan(**kwargs)
            total += page["Count"]
            if "LastEvaluatedKey" not in page:
                return total
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    # ---- the cap counter -------------------------------------------------

    def _ensure_counter(self) -> None:
        """Create the counter from the real item count if it does not exist yet."""
        if self._read_counter() is None:
            self._write_count(None, self.count())  # False: someone else created it first, fine

    def _read_counter(self) -> dict | None:
        return self.table.get_item(Key={"endpoint_id": COUNTER_ID}, ConsistentRead=True).get("Item")

    def _write_count(self, seen: dict | None, actual: int) -> bool:
        """Set the counter to `actual` if it still is as read (`seen`). False if it moved.

        Creating an endpoint changes the counter, so a registration landing between the read and
        this write makes the write fail and the caller stand down.
        """
        try:
            if seen is None:
                self.table.put_item(
                    Item={"endpoint_id": COUNTER_ID, "n": actual},
                    ConditionExpression="attribute_not_exists(endpoint_id)",
                )
            elif "n" not in seen:  # an item edited by hand, without its number
                self.table.update_item(
                    Key={"endpoint_id": COUNTER_ID},
                    UpdateExpression="SET n = :actual",
                    ConditionExpression="attribute_not_exists(n)",
                    ExpressionAttributeValues={":actual": actual},
                )
            else:
                self.table.update_item(
                    Key={"endpoint_id": COUNTER_ID},
                    UpdateExpression="SET n = :actual",
                    ConditionExpression="n = :seen",
                    ExpressionAttributeValues={":actual": actual, ":seen": seen["n"]},
                )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return False
        return True

    def _reconcile(self, max_endpoints: int) -> bool:
        """Repair a counter that disagrees with the real count. True if a slot is now free.

        Safe against concurrent registrations (see _write_count).
        """
        seen = self._read_counter()
        actual = self.count()
        moved = (seen is None or seen.get("n") != actual) and not self._write_count(seen, actual)
        if moved:
            return True  # the counter moved under us; just try the creation again
        return actual < max_endpoints

    def repair_counter(self, attempts: int = 5) -> int:
        """Set the counter to the real count, after a restore. Returns the value written.

        It retries when a registration lands in between, and never deletes the counter: a
        registration racing a missing counter would start it again from zero.
        """
        for _ in range(attempts):
            seen = self._read_counter()
            actual = self.count()
            if self._write_count(seen, actual):
                return actual
        raise RuntimeError(f"the endpoint counter kept changing over {attempts} attempts")

    def _create(self, item: dict, max_endpoints: int) -> None:
        """Atomically add the endpoint and bump the counter, or raise ClientError."""
        name = self.table.name
        self.table.meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": name,
                        "Item": item,
                        "ConditionExpression": "attribute_not_exists(endpoint_id)",
                    }
                },
                {
                    "Update": {
                        "TableName": name,
                        "Key": {"endpoint_id": COUNTER_ID},
                        "UpdateExpression": "SET n = if_not_exists(n, :zero) + :one",
                        "ConditionExpression": "attribute_not_exists(n) OR n < :cap",
                        "ExpressionAttributeValues": {":zero": 0, ":one": 1, ":cap": max_endpoints},
                    }
                },
            ]
        )

    def put(
        self,
        endpoint_id: str,
        url: str,
        now: datetime,
        expected_status: int = 200,
        max_endpoints: int = 10,
    ) -> tuple[dict, bool]:
        """Create the endpoint if new. Returns (item, created). Raises EndpointLimitReached."""
        existing = self.get(endpoint_id)
        if existing:
            return existing, False
        self._ensure_counter()

        item = {
            "endpoint_id": endpoint_id,
            "url": url,
            "method": "GET",
            "expected_status": expected_status,
            "enabled": True,
            "created_at": iso(now),
            "status": "UNKNOWN",
            "consecutive_failures": 0,
        }
        for attempt in (1, 2):
            try:
                self._create(item, max_endpoints)
                return item, True
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "TransactionCanceledException":
                    raise
                codes = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
                if codes and codes[0] == "ConditionalCheckFailed":
                    existing = self.get(endpoint_id)  # created by a concurrent registration
                    if existing:
                        return existing, False
                if attempt == 1 and self._reconcile(max_endpoints):
                    continue  # the counter had drifted above the real count; try once more
                raise EndpointLimitReached(max_endpoints) from exc
        raise EndpointLimitReached(max_endpoints)  # pragma: no cover (loop always returns/raises)

    def list_enabled(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            page = self.table.scan(**kwargs)
            items.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [plain(i) for i in items if _is_endpoint(i) and i.get("enabled", True)]

    def update(self, endpoint_id: str, **fields) -> None:
        """SET fields with a value, REMOVE fields passed as None."""
        names, values, sets, removes = {}, {}, [], []
        for i, (field, value) in enumerate(fields.items()):
            names[f"#f{i}"] = field
            if value is None:
                removes.append(f"#f{i}")
            else:
                values[f":v{i}"] = value
                sets.append(f"#f{i} = :v{i}")
        expression = " ".join(
            part
            for part in (
                "SET " + ", ".join(sets) if sets else "",
                "REMOVE " + ", ".join(removes) if removes else "",
            )
            if part
        )
        kwargs = {
            "Key": {"endpoint_id": endpoint_id},
            "UpdateExpression": expression,
            "ExpressionAttributeNames": names,
        }
        if values:
            kwargs["ExpressionAttributeValues"] = values
        self.table.update_item(**kwargs)
