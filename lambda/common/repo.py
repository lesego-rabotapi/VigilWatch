"""DynamoDB access for VigilWatch.

Two tables (see terraform/dynamo.tf):

  endpoints  PK endpoint_id
  history    PK endpoint_id, SK one of
               C#<iso>   raw check result           (TTL 48 h)
               D#<date>  daily rollup {total, up}   (TTL 31 d)
               I#<iso>   incident                   (TTL 31 d)

Daily rollups keep the 30-day uptime query to at most 30 small items, which
keeps reads inside the always-free provisioned capacity.
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common.status import counts_as_up

RAW_TTL = timedelta(hours=48)
ROLLUP_TTL = timedelta(days=31)
UPTIME_WINDOW_DAYS = 30


class EndpointLimitReached(Exception):
    pass


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def plain(value):
    """Convert DynamoDB Decimals (recursively) into int/float."""
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


class Repo:
    def __init__(self, endpoints_table: str | None = None, history_table: str | None = None):
        dynamodb = boto3.resource("dynamodb")
        self.endpoints = dynamodb.Table(endpoints_table or os.environ["ENDPOINTS_TABLE"])
        self.history = dynamodb.Table(history_table or os.environ["HISTORY_TABLE"])

    # ---- endpoints -------------------------------------------------------

    def get_endpoint(self, endpoint_id: str) -> dict | None:
        item = self.endpoints.get_item(Key={"endpoint_id": endpoint_id}).get("Item")
        return plain(item) if item else None

    def count_endpoints(self) -> int:
        total, kwargs = 0, {"Select": "COUNT"}
        while True:
            page = self.endpoints.scan(**kwargs)
            total += page["Count"]
            if "LastEvaluatedKey" not in page:
                return total
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def put_endpoint(
        self,
        endpoint_id: str,
        url: str,
        now: datetime,
        expected_status: int = 200,
        max_endpoints: int = 10,
    ) -> tuple[dict, bool]:
        """Create the endpoint if new. Returns (item, created)."""
        existing = self.get_endpoint(endpoint_id)
        if existing:
            return existing, False
        if self.count_endpoints() >= max_endpoints:
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
            self.endpoints.put_item(
                Item=item, ConditionExpression="attribute_not_exists(endpoint_id)"
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return self.get_endpoint(endpoint_id), False
        return item, True

    def list_enabled_endpoints(self) -> list[dict]:
        items, kwargs = [], {}
        while True:
            page = self.endpoints.scan(**kwargs)
            items.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [plain(i) for i in items if i.get("enabled", True)]

    def update_endpoint(self, endpoint_id: str, **fields) -> None:
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
        self.endpoints.update_item(**kwargs)

    # ---- history ---------------------------------------------------------

    def record_check(
        self,
        endpoint_id: str,
        now: datetime,
        status: str,
        status_code: int | None,
        latency_ms: float | None,
    ) -> None:
        row = {
            "endpoint_id": endpoint_id,
            "sk": f"C#{iso(now)}",
            "status": status,
            "expires_at": _epoch(now + RAW_TTL),
        }
        if status_code is not None:
            row["status_code"] = int(status_code)
        if latency_ms is not None:
            row["latency_ms"] = int(round(latency_ms))
        self.history.put_item(Item=row)

        self.history.update_item(
            Key={"endpoint_id": endpoint_id, "sk": f"D#{now.date().isoformat()}"},
            UpdateExpression="ADD #total :one, #up :up SET expires_at = :exp",
            ExpressionAttributeNames={"#total": "total", "#up": "up"},
            ExpressionAttributeValues={
                ":one": 1,
                ":up": 1 if counts_as_up(status) else 0,
                ":exp": _epoch(now + ROLLUP_TTL),
            },
        )

    def recent_checks(self, endpoint_id: str, limit: int = 20) -> list[dict]:
        page = self.history.query(
            KeyConditionExpression=Key("endpoint_id").eq(endpoint_id) & Key("sk").begins_with("C#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [
            {
                "checked_at": row["sk"][2:],
                "status": row["status"],
                "status_code": row.get("status_code"),
                "latency_ms": row.get("latency_ms"),
            }
            for row in plain(page["Items"])
        ]

    def uptime_30d(self, endpoint_id: str, now: datetime) -> float | None:
        start = (now - timedelta(days=UPTIME_WINDOW_DAYS - 1)).date().isoformat()
        end = now.date().isoformat()
        page = self.history.query(
            KeyConditionExpression=Key("endpoint_id").eq(endpoint_id)
            & Key("sk").between(f"D#{start}", f"D#{end}"),
        )
        total = sum(int(r["total"]) for r in page["Items"])
        if total == 0:
            return None
        up = sum(int(r["up"]) for r in page["Items"])
        return up * 100.0 / total

    # ---- incidents -------------------------------------------------------

    def open_incident(self, endpoint_id: str, start: datetime) -> str:
        start_iso = iso(start)
        self.history.put_item(
            Item={
                "endpoint_id": endpoint_id,
                "sk": f"I#{start_iso}",
                "resolved": False,
                "expires_at": _epoch(start + ROLLUP_TTL),
            }
        )
        return start_iso

    def close_incident(self, endpoint_id: str, start_iso: str, end: datetime) -> None:
        duration = int((end - parse_iso(start_iso)).total_seconds())
        self.history.update_item(
            Key={"endpoint_id": endpoint_id, "sk": f"I#{start_iso}"},
            UpdateExpression=(
                "SET resolved = :t, end_time = :end, duration_s = :d, expires_at = :exp"
            ),
            ExpressionAttributeValues={
                ":t": True,
                ":end": iso(end),
                ":d": duration,
                ":exp": _epoch(end + ROLLUP_TTL),
            },
        )

    def incidents(self, endpoint_id: str, limit: int = 20) -> list[dict]:
        page = self.history.query(
            KeyConditionExpression=Key("endpoint_id").eq(endpoint_id) & Key("sk").begins_with("I#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [
            {
                "start_time": row["sk"][2:],
                "end_time": row.get("end_time"),
                "resolved": bool(row.get("resolved", False)),
                "duration_s": row.get("duration_s"),
            }
            for row in plain(page["Items"])
        ]
