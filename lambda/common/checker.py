"""Probe an endpoint and fold the result into its health, incident and alert state."""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import boto3

from common.repo import Repo, iso
from common.status import DOWN, CheckResult, classify
from common.urlguard import UnsafeURL, validate

logger = logging.getLogger(__name__)

USER_AGENT = "VigilWatch/1.0 (+https://github.com/lesego-rabotapi/VigilWatch)"


@dataclass(frozen=True)
class Settings:
    degraded_ms: float = 1000
    failure_threshold: int = 2
    timeout_s: float = 5
    max_workers: int = 10

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            degraded_ms=float(os.environ.get("DEGRADED_MS", cls.degraded_ms)),
            failure_threshold=int(os.environ.get("FAILURE_THRESHOLD", cls.failure_threshold)),
            timeout_s=float(os.environ.get("PROBE_TIMEOUT_S", cls.timeout_s)),
            max_workers=int(os.environ.get("MAX_WORKERS", cls.max_workers)),
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report 3xx as-is. Following redirects would let a public URL bounce the probe inward."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def probe(
    url: str,
    timeout: float = 5,
    validator: Callable[[str], str] = validate,
) -> CheckResult:
    """Single GET. Never raises: every failure becomes CheckResult.error."""
    try:
        url = validator(url)
    except UnsafeURL as exc:
        return CheckResult(status_code=None, latency_ms=None, error=str(exc))

    request = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
    started = time.perf_counter()
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        status_code = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return CheckResult(status_code=None, latency_ms=None, error=str(reason) or type(exc).__name__)
    return CheckResult(status_code=status_code, latency_ms=(time.perf_counter() - started) * 1000)


Publisher = Callable[[str, dict], bool]


def make_publisher(topic_arn: str | None = None) -> Publisher:
    topic_arn = topic_arn or os.environ.get("SNS_TOPIC_ARN")
    if not topic_arn:
        return lambda subject, payload: False

    sns = boto3.client("sns")

    def publish(subject: str, payload: dict) -> bool:
        # SNS subjects: ASCII, no newlines, at most 100 characters.
        safe_subject = subject.encode("ascii", "replace").decode().replace("\n", " ")[:100]
        try:
            sns.publish(
                TopicArn=topic_arn,
                Subject=safe_subject,
                Message=json.dumps(payload, indent=2),
            )
        except Exception:
            logger.exception("failed to publish alert")
            return False
        return True

    return publish


def apply_result(
    endpoint: dict,
    result: CheckResult,
    repo: Repo,
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
