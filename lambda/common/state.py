"""Fold one probe result into an endpoint's health, incident and alert state."""

from datetime import datetime

from common.ports import CheckStore, Publisher
from common.settings import Settings
from common.status import DOWN, CheckResult, classify
from common.timefmt import iso


def apply_result(
    endpoint: dict,
    result: CheckResult,
    repo: CheckStore,
    publish: Publisher,
    now: datetime,
    settings: Settings,
) -> str:
    """Persist one probe result and drive the incident/alert state machine. Returns the status."""
    endpoint_id = endpoint["endpoint_id"]
    url = endpoint["url"]
    status = classify(result, int(endpoint.get("expected_status", 200)), settings.degraded_ms)
    repo.record_check(endpoint_id, now, status, result.status_code, result.latency_ms)

    failures = int(endpoint.get("consecutive_failures", 0))
    open_start = endpoint.get("open_incident_start")
    fields = {
        "status": status,
        "last_check": iso(now),
        "last_status_code": result.status_code,
        "last_latency_ms": None if result.latency_ms is None else int(round(result.latency_ms)),
        "last_error": result.error,
    }

    def alert(event: str) -> None:
        sent = publish(
            f"[VigilWatch] {event}: {url}",
            {
                "event": event,
                "url": url,
                "endpoint_id": endpoint_id,
                "status_code": result.status_code,
                "error": result.error,
                "consecutive_failures": failures,
                "incident_start": open_start,
                "timestamp": iso(now),
            },
        )
        if sent:
            fields["last_alert_sent"] = iso(now)

    if status == DOWN:
        failures += 1
        if failures >= settings.failure_threshold and not open_start:
            open_start = repo.open_incident(endpoint_id, now)
            fields["open_incident_start"] = open_start
            alert("DOWN")
    else:
        failures = 0
        if open_start:
            repo.close_incident(endpoint_id, open_start, now)
            fields["open_incident_start"] = None
            alert("RECOVERED")

    fields["consecutive_failures"] = failures
    repo.update_endpoint(endpoint_id, **fields)
    return status
