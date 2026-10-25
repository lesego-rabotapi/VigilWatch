"""The endpoints table: one item per monitored URL (partition key endpoint_id)."""

from datetime import datetime

from botocore.exceptions import ClientError

from common.dynamo import plain
from common.timefmt import iso


class EndpointLimitReached(Exception):
    pass


class EndpointRepository:
    def __init__(self, table):
        self.table = table

    def get(self, endpoint_id: str) -> dict | None:
        item = self.table.get_item(Key={"endpoint_id": endpoint_id}).get("Item")
        return plain(item) if item else None

    def count(self) -> int:
        total, kwargs = 0, {"Select": "COUNT"}
        while True:
            page = self.table.scan(**kwargs)
            total += page["Count"]
            if "LastEvaluatedKey" not in page:
                return total
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def put(
        self,
        endpoint_id: str,
        url: str,
        now: datetime,
        expected_status: int = 200,
        max_endpoints: int = 10,
    ) -> tuple[dict, bool]:
        """Create the endpoint if new. Returns (item, created)."""
        existing = self.get(endpoint_id)
        if existing:
            return existing, False
        if self.count() >= max_endpoints:
            raise EndpointLimitReached(max_endpoints)

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
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(endpoint_id)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return self.get(endpoint_id), False
        return item, True

    def list_enabled(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            page = self.table.scan(**kwargs)
            items.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [plain(i) for i in items if i.get("enabled", True)]

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
