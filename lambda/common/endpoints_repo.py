"""The endpoints table: one item per monitored URL (partition key endpoint_id).

Two caps are enforced with counter items in the same table: one for all endpoints together
(`_system#count`, which bounds the checker's work and so the cost) and one per user
(`_owner#<sub>`, so one user cannot take the whole global cap). Creating an endpoint and
incrementing both counters happen in one DynamoDB transaction whose conditions are "counter below
its cap", so concurrent registrations cannot overshoot either: DynamoDB serialises them. Counters
are bookkeeping, not data: counting and listing skip them, and if one drifts (an item deleted by
hand, or a table that predates it) it is rebuilt from the real item count.
"""

from datetime import datetime

from botocore.exceptions import ClientError

from common.dynamo import plain
from common.timefmt import iso

COUNTER_ID = "_system#count"
OWNER_COUNTER_PREFIX = "_owner#"
_RESERVED_PREFIX = "_"


def owner_counter_id(owner: str) -> str:
    return f"{OWNER_COUNTER_PREFIX}{owner}"


class EndpointLimitReached(Exception):
    """The global cap: args[0] is the limit."""


class OwnerLimitReached(EndpointLimitReached):
    """The registering user's own cap: args[0] is the limit."""


def _is_endpoint(item: dict) -> bool:
    return not item["endpoint_id"].startswith(_RESERVED_PREFIX)


class EndpointRepository:
    def __init__(self, table):
        self.table = table

    def get(self, endpoint_id: str) -> dict | None:
        item = self.table.get_item(Key={"endpoint_id": endpoint_id}).get("Item")
        return plain(item) if item else None

    def count(self, owner: str | None = None) -> int:
        """Number of real endpoints, all or one user's. Strongly consistent: it feeds the caps'
        repair path."""
        expression = "NOT begins_with(endpoint_id, :reserved)"
        values = {":reserved": _RESERVED_PREFIX}
        if owner is not None:
            expression += " AND owner_sub = :owner"
            values[":owner"] = owner
        total, kwargs = (
            0,
            {
                "Select": "COUNT",
                "ConsistentRead": True,
                "FilterExpression": expression,
                "ExpressionAttributeValues": values,
            },
        )
        while True:
            page = self.table.scan(**kwargs)
            total += page["Count"]
            if "LastEvaluatedKey" not in page:
                return total
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    # ---- the cap counters: owner None is the global one -------------------

    @staticmethod
    def _counter_key(owner: str | None) -> dict:
        return {"endpoint_id": COUNTER_ID if owner is None else owner_counter_id(owner)}

    def _ensure_counter(self, owner: str | None = None) -> None:
        """Create the counter from the real item count if it does not exist yet."""
        if self._read_counter(owner, consistent=False) is None:  # a conditional create
            self._write_count(None, self.count(owner), owner)  # False: created by someone else

    def _read_counter(self, owner: str | None = None, consistent: bool = True) -> dict | None:
        key = self._counter_key(owner)
        return self.table.get_item(Key=key, ConsistentRead=consistent).get("Item")

    def _write_count(self, seen: dict | None, actual: int, owner: str | None = None) -> bool:
        """Set the counter to `actual` if it still is as read (`seen`). False if it moved.

        Creating an endpoint changes the counter, so a registration landing between the read and
        this write makes the write fail and the caller stand down.
        """
        key = self._counter_key(owner)
        try:
            if seen is None:
                self.table.put_item(
                    Item={**key, "n": actual},
                    ConditionExpression="attribute_not_exists(endpoint_id)",
                )
            elif "n" not in seen:  # an item edited by hand, without its number
                self.table.update_item(
                    Key=key,
                    UpdateExpression="SET n = :actual",
                    ConditionExpression="attribute_not_exists(n)",
                    ExpressionAttributeValues={":actual": actual},
                )
            else:
                self.table.update_item(
                    Key=key,
                    UpdateExpression="SET n = :actual",
                    ConditionExpression="n = :seen",
                    ExpressionAttributeValues={":actual": actual, ":seen": seen["n"]},
                )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return False
        return True

    def _reconcile(self, limit: int, owner: str | None = None) -> bool:
        """Repair a counter that disagrees with the real count. True if a slot is now free.

        Safe against concurrent registrations (see _write_count).
        """
        seen = self._read_counter(owner)
        actual = self.count(owner)
        if seen is not None and seen.get("n") == actual:
            return actual < limit  # nothing to repair
        if not self._write_count(seen, actual, owner):
            return True  # the counter moved under us; just try the creation again
        return actual < limit

    def _repair_one(self, owner: str | None, attempts: int) -> int:
        for _ in range(attempts):
            seen = self._read_counter(owner)
            actual = self.count(owner)
            if self._write_count(seen, actual, owner):
                return actual
        raise RuntimeError(f"the endpoint counter kept changing over {attempts} attempts")

    def _owners(self) -> set[str]:
        """Every user with an endpoint or a counter."""
        owners, kwargs = set(), {"ProjectionExpression": "endpoint_id, owner_sub"}
        while True:
            page = self.table.scan(**kwargs)
            for item in page["Items"]:
                if item["endpoint_id"].startswith(OWNER_COUNTER_PREFIX):
                    owners.add(item["endpoint_id"][len(OWNER_COUNTER_PREFIX) :])
                elif _is_endpoint(item) and item.get("owner_sub"):
                    owners.add(item["owner_sub"])
            if "LastEvaluatedKey" not in page:
                return owners
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def repair_counter(self, attempts: int = 5) -> int:
        """Set every counter to its real count, after a restore. Returns the global count.

        Each write retries when a registration lands in between, and no counter is deleted: a
        registration racing a missing counter would start it again from zero.
        """
        total = self._repair_one(None, attempts)
        for owner in sorted(self._owners()):
            self._repair_one(owner, attempts)
        return total

    def _create(
        self, item: dict, max_endpoints: int, owner: str | None, max_per_owner: int | None
    ) -> None:
        """Atomically add the endpoint and bump the counters, or raise ClientError."""
        name = self.table.name

        def bump(owner_or_none, limit):
            return {
                "Update": {
                    "TableName": name,
                    "Key": self._counter_key(owner_or_none),
                    "UpdateExpression": "SET n = if_not_exists(n, :zero) + :one",
                    "ConditionExpression": "attribute_not_exists(n) OR n < :cap",
                    "ExpressionAttributeValues": {":zero": 0, ":one": 1, ":cap": limit},
                }
            }

        operations = [
            {
                "Put": {
                    "TableName": name,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(endpoint_id)",
                }
            },
            bump(None, max_endpoints),
        ]
        if owner is not None and max_per_owner is not None:
            operations.append(bump(owner, max_per_owner))
        self.table.meta.client.transact_write_items(TransactItems=operations)

    def put(
        self,
        endpoint_id: str,
        url: str,
        now: datetime,
        expected_status: int = 200,
        max_endpoints: int = 10,
        owner: str | None = None,
        max_per_owner: int | None = None,
    ) -> tuple[dict, bool]:
        """Create the endpoint if new. Returns (item, created).

        Raises OwnerLimitReached at the user's cap, EndpointLimitReached at the global one.
        """
        existing = self.get(endpoint_id)
        if existing:
            return existing, False
        per_owner = owner is not None and max_per_owner is not None
        self._ensure_counter()
        if per_owner:
            self._ensure_counter(owner)

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
        if owner is not None:
            item["owner_sub"] = owner
        for attempt in (1, 2):
            try:
                self._create(item, max_endpoints, owner, max_per_owner)
                return item, True
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "TransactionCanceledException":
                    raise
                codes = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
                if codes and codes[0] == "ConditionalCheckFailed":
                    existing = self.get(endpoint_id)  # created by a concurrent registration
                    if existing:
                        return existing, False
                # Which cap refused it: the reasons follow the operations' order.
                owner_full = per_owner and len(codes) > 2 and codes[2] == "ConditionalCheckFailed"
                global_full = not owner_full or (
                    len(codes) > 1 and codes[1] == "ConditionalCheckFailed"
                )
                if attempt == 1:
                    freed = (not global_full or self._reconcile(max_endpoints)) and (
                        not owner_full or self._reconcile(max_per_owner, owner)
                    )
                    if freed:
                        continue  # a counter had drifted above the real count; try once more
                if global_full:
                    raise EndpointLimitReached(max_endpoints) from exc
                raise OwnerLimitReached(max_per_owner) from exc
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
