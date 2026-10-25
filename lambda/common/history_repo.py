"""Check history in the history table: raw checks (C#) and daily rollups (D#).

Daily rollups keep the 30-day uptime query to at most 30 small items, which keeps reads inside the
always-free provisioned capacity. Incidents share the table but live in incidents_repo.
"""

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key

from common.dynamo import plain
from common.retention import RAW_TTL, ROLLUP_TTL, UPTIME_WINDOW_DAYS
from common.status import INCONCLUSIVE, counts_as_up
from common.timefmt import epoch, iso

# Operational data about the checker itself lives beside the endpoint history, under a reserved id.
SYSTEM_ID = "_system"
HEARTBEAT_SK = "H#checker"


class HistoryRepository:
    def __init__(self, table):
        self.table = table

    def record(
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
            "expires_at": epoch(now + RAW_TTL),
        }
        if status_code is not None:
            row["status_code"] = int(status_code)
        if latency_ms is not None:
            row["latency_ms"] = int(round(latency_ms))
        self.table.put_item(Item=row)
        if status == INCONCLUSIVE:
            return  # not evidence of up or down, so it stays out of the uptime figure

        self.table.update_item(
            Key={"endpoint_id": endpoint_id, "sk": f"D#{now.date().isoformat()}"},
            UpdateExpression="ADD #total :one, #up :up SET expires_at = :exp",
            ExpressionAttributeNames={"#total": "total", "#up": "up"},
            ExpressionAttributeValues={
                ":one": 1,
                ":up": 1 if counts_as_up(status) else 0,
                ":exp": epoch(now + ROLLUP_TTL),
            },
        )

    def recent(self, endpoint_id: str, limit: int = 20) -> list[dict]:
        page = self.table.query(
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
        page = self.table.query(
            KeyConditionExpression=Key("endpoint_id").eq(endpoint_id)
            & Key("sk").between(f"D#{start}", f"D#{end}"),
        )
        total = sum(int(r["total"]) for r in page["Items"])
        if total == 0:
            return None
        up = sum(int(r["up"]) for r in page["Items"])
        return up * 100.0 / total

    def record_heartbeat(self, now: datetime, details: dict) -> None:
        """The latest completed checker run (one item, overwritten each time)."""
        self.table.put_item(
            Item={
                "endpoint_id": SYSTEM_ID,
                "sk": HEARTBEAT_SK,
                "last_run": iso(now),
                "expires_at": epoch(now + ROLLUP_TTL),
                **details,
            }
        )

    def heartbeat(self) -> dict | None:
        item = self.table.get_item(Key={"endpoint_id": SYSTEM_ID, "sk": HEARTBEAT_SK}).get("Item")
        return plain(item) if item else None
