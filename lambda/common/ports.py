"""Contracts between components, so each can be tested with an in-memory fake."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

# publish(subject, payload) -> True when the alert was delivered to the topic.
Publisher = Callable[[str, dict], bool]


class CheckStore(Protocol):
    """What the incident/alert state machine needs from storage."""

    def record_check(
        self,
        endpoint_id: str,
        now: datetime,
        status: str,
        status_code: int | None,
        latency_ms: float | None,
    ) -> None: ...

    def open_incident(self, endpoint_id: str, start: datetime) -> str: ...

    def close_incident(self, endpoint_id: str, start_iso: str, end: datetime) -> None: ...

    def update_endpoint(self, endpoint_id: str, **fields) -> None: ...
