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
        if self.table.get_item(Key={"endpoint_id": COUNTER_ID}).get("Item"):
            return
        try:
            self.table.put_item(
                Item={"endpoint_id": COUNTER_ID, "n": self.count()},
                ConditionExpression="attribute_not_exists(endpoint_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise  # someone else created it first, which is fine

    def _reconcile(self, max_endpoints: int) -> bool:
        """Repair a counter that disagrees with the real count. True if a slot is now free.

        Safe against concurrent registrations: the counter is only rewritten if it still holds the
        value seen before counting. Creating an endpoint changes the counter, so any registration
        that lands in between makes the write fail and the repair stand down.
        """
        item = self.table.get_item(Key={"endpoint_id": COUNTER_ID}, ConsistentRead=True).get("Item")
        actual = self.count()
        if item is None:
            return self._restore_missing_counter(actual, max_endpoints)
        seen = int(item["n"])
        if actual != seen:
            try:
                self.table.update_item(
                    Key={"endpoint_id": COUNTER_ID},
                    UpdateExpression="SET n = :actual",
                    ConditionExpression="n = :seen",
                    ExpressionAttributeValues={":actual": actual, ":seen": seen},
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
                return True  # the counter moved under us; just try the creation again
        return actual < max_endpoints

    def repair_counter(self, attempts: int = 5) -> int:
        """Set the counter to the real count, for a restore. Returns the value written.

        Like _reconcile, it writes only if the counter still holds the value read before counting,
        so a registration landing in between makes it stand down and count again. It never deletes
        the counter: a registration racing a missing counter would start it again from zero.
        """
        for _ in range(attempts):
            item = self.table.get_item(Key={"endpoint_id": COUNTER_ID}, ConsistentRead=True).get(
                "Item"
            )
            actual = self.count()
            try:
                if item is None:
                    self.table.put_item(
                        Item={"endpoint_id": COUNTER_ID, "n": actual},
                        ConditionExpression="attribute_not_exists(endpoint_id)",
                    )
                elif "n" not in item:
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
                        ExpressionAttributeValues={":actual": actual, ":seen": item["n"]},
                    )
                return actual
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        raise RuntimeError(f"the endpoint counter kept changing over {attempts} attempts")

    def _restore_missing_counter(self, actual: int, max_endpoints: int) -> bool:
        try:
            self.table.put_item(
                Item={"endpoint_id": COUNTER_ID, "n": actual},
                ConditionExpression="attribute_not_exists(endpoint_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return True
        return actual < max_endpoints

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
