"""One object for all DynamoDB access, composed from three single-purpose repositories.

Two tables (see terraform/dynamo.tf):

  endpoints  PK endpoint_id                                    -> EndpointRepository
  history    PK endpoint_id, SK one of
               C#<iso>   raw check result           (TTL 48 h)   -> HistoryRepository
               D#<date>  daily rollup {total, up}   (TTL 31 d)   -> HistoryRepository
               I#<iso>   incident                   (TTL 31 d)   -> IncidentRepository

Handlers use this facade, and the state machine depends only on the CheckStore protocol, so the
repositories can be used and tested separately.
"""

import os
from datetime import datetime

from common import aws
from common.dynamo import plain
from common.endpoints_repo import EndpointLimitReached, EndpointRepository
from common.history_repo import HistoryRepository
from common.incidents_repo import IncidentRepository
from common.timefmt import iso, parse_iso

__all__ = ["EndpointLimitReached", "Repo", "iso", "parse_iso", "plain"]


class Repo:
    def __init__(self, endpoints_table: str | None = None, history_table: str | None = None):
        dynamodb = aws.dynamodb_resource()
        self.endpoints = dynamodb.Table(endpoints_table or os.environ["ENDPOINTS_TABLE"])
        self.history = dynamodb.Table(history_table or os.environ["HISTORY_TABLE"])
        self._endpoints = EndpointRepository(self.endpoints)
        self._history = HistoryRepository(self.history)
        self._incidents = IncidentRepository(self.history)

    # ---- endpoints -------------------------------------------------------

    def get_endpoint(self, endpoint_id: str) -> dict | None:
        return self._endpoints.get(endpoint_id)

    def count_endpoints(self) -> int:
        return self._endpoints.count()

    def put_endpoint(
        self,
        endpoint_id: str,
        url: str,
        now: datetime,
        expected_status: int = 200,
        max_endpoints: int = 10,
    ) -> tuple[dict, bool]:
        return self._endpoints.put(endpoint_id, url, now, expected_status, max_endpoints)

    def list_enabled_endpoints(self) -> list[dict]:
        return self._endpoints.list_enabled()

    def update_endpoint(self, endpoint_id: str, **fields) -> None:
        self._endpoints.update(endpoint_id, **fields)

    # ---- history ---------------------------------------------------------

    def record_check(
        self,
        endpoint_id: str,
        now: datetime,
        status: str,
        status_code: int | None,
        latency_ms: float | None,
    ) -> None:
        self._history.record(endpoint_id, now, status, status_code, latency_ms)

    def recent_checks(self, endpoint_id: str, limit: int = 20) -> list[dict]:
        return self._history.recent(endpoint_id, limit)

    def uptime_30d(self, endpoint_id: str, now: datetime) -> float | None:
        return self._history.uptime_30d(endpoint_id, now)

    def record_heartbeat(self, now: datetime, details: dict) -> None:
        self._history.record_heartbeat(now, details)

    def heartbeat(self) -> dict | None:
        return self._history.heartbeat()

    # ---- incidents -------------------------------------------------------

    def open_incident(self, endpoint_id: str, start: datetime) -> str:
        return self._incidents.open(endpoint_id, start)

    def close_incident(self, endpoint_id: str, start_iso: str, end: datetime) -> None:
        self._incidents.close(endpoint_id, start_iso, end)

    def incidents(self, endpoint_id: str, limit: int = 20) -> list[dict]:
        return self._incidents.list(endpoint_id, limit)
