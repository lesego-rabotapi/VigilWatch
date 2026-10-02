"""Turn a raw HTTP probe result into an endpoint health status."""

from dataclasses import dataclass

UP = "UP"
DEGRADED = "DEGRADED"
DOWN = "DOWN"


@dataclass(frozen=True)
class CheckResult:
    status_code: int | None
    latency_ms: float | None
    error: str | None = None


def classify(result: CheckResult, expected_status: int = 200, degraded_ms: float = 1000) -> str:
    if result.error or result.status_code is None:
        return DOWN
    if result.status_code != expected_status:
        return DOWN
    if result.latency_ms is not None and result.latency_ms >= degraded_ms:
        return DEGRADED
    return UP


def counts_as_up(status: str) -> bool:
    """A slow-but-correct response still counts towards uptime."""
    return status in (UP, DEGRADED)
