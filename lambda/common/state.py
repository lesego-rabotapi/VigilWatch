"""Fold one probe result into an endpoint's health, incident and alert state."""

from datetime import datetime

from common.ports import CheckStore, Publisher
from common.settings import Settings
from common.status import DOWN, INCONCLUSIVE, CheckResult, classify
from common.timefmt import iso


def apply_result(
    endpoint: dict,
    result: CheckResult,
    repo: CheckStore,
    publish: Publisher,
    now: datetime,
    settings: Settings,
    controls_ok: bool = True,
) -> str:
    """Persist one probe result and drive the incident/alert state machine. Returns the status.

    `controls_ok` is False when the checker's own connectivity checks failed. A DOWN result is then
    recorded as INCONCLUSIVE and changes nothing else: it is not a failure to count, an incident to
    open or close, or a reason to alert. An answering target proves connectivity, so only DOWN is
    affected.
    """
    endpoint_id = endpoint["endpoint_id"]
    url = endpoint["url"]
    status = classify(result, int(endpoint.get("expected_status", 200)), settings.degraded_ms)
    if status == DOWN and not controls_ok:
        repo.record_check(endpoint_id, now, INCONCLUSIVE, result.status_code, result.latency_ms)
        repo.update_endpoint(
            endpoint_id,
            status=INCONCLUSIVE,
            last_check=iso(now),
            last_status_code=result.status_code,
            last_latency_ms=None if result.latency_ms is None else int(round(result.latency_ms)),
            last_error=result.error,
        )
        return INCONCLUSIVE
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
