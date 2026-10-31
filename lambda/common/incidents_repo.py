"""Incidents (I# items) in the history table."""

from datetime import datetime

from boto3.dynamodb.conditions import Key

from common.dynamo import plain
from common.retention import ROLLUP_TTL
from common.timefmt import epoch, iso, parse_iso


class IncidentRepository:
    def __init__(self, table):
        self.table = table

    def open(self, endpoint_id: str, start: datetime) -> str:
        start_iso = iso(start)
        self.table.put_item(
            Item={
                "endpoint_id": endpoint_id,
                "sk": f"I#{start_iso}",
                "resolved": False,
                "expires_at": epoch(start + ROLLUP_TTL),
            }
        )
        return start_iso

    def close(self, endpoint_id: str, start_iso: str, end: datetime) -> None:
        duration = int((end - parse_iso(start_iso)).total_seconds())
        self.table.update_item(
            Key={"endpoint_id": endpoint_id, "sk": f"I#{start_iso}"},
            UpdateExpression=(
                "SET resolved = :t, end_time = :end, duration_s = :d, expires_at = :exp"
            ),
            ExpressionAttributeValues={
                ":t": True,
                ":end": iso(end),
                ":d": duration,
                ":exp": epoch(end + ROLLUP_TTL),
            },
        )

    def list(self, endpoint_id: str, limit: int = 20) -> list[dict]:
        page = self.table.query(
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
