"""Scheduled uptime checker (EventBridge -> Lambda).

Probes every enabled endpoint in parallel, then persists results serially
(boto3 resources are not thread-safe). Endpoint downtime is data, not an
error; the invocation only fails when VigilWatch itself could not process an
endpoint, so the Lambda Errors alarm means "the monitor is broken".
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from common import logs
from common.checker import Settings, apply_result, make_publisher, probe
from common.controls import check_controls
from common.repo import Repo
from common.status import DEGRADED, DOWN, INCONCLUSIVE, UP, classify

logger = logs.get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _emf(summary: dict, latencies: list[float], now: datetime, controls: str) -> str:
    values = {
        "ChecksRun": summary["checked"],
        "EndpointsDown": summary["down"],
        "EndpointsDegraded": summary["degraded"],
        "EndpointsInconclusive": summary["inconclusive"],
        "RunsCompleted": 1,
    }
    if controls in ("healthy", "failed"):  # only when connectivity was actually checked
        values["ControlProbeFailed"] = 1 if controls == "failed" else 0
    if latencies:
        values["AvgLatencyMs"] = round(sum(latencies) / len(latencies), 1)
    units = {"AvgLatencyMs": "Milliseconds"}
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(now.timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "VigilWatch",
                        # A single low-cardinality dimension keeps this at a fixed
                        # number of custom metrics, whatever is being monitored.
                        "Dimensions": [["Service"]],
                        "Metrics": [
                            {"Name": name, "Unit": units.get(name, "Count")} for name in values
                        ],
                    }
                ],
            },
            "Service": "uptime-check",
            **values,
        }
    )


def _judge_connectivity(settings: Settings, statuses: list[str]) -> tuple[str, bool]:
    """('disabled' | 'not_needed' | 'healthy' | 'failed', whether DOWN results can be trusted).

    Controls are only probed when something is down and nothing answered: a target that answered
    correctly already proves the checker can reach the internet.
    """
    if not settings.control_urls:
        return "disabled", True
    anything_down = DOWN in statuses
    anything_answered = any(status in (UP, DEGRADED) for status in statuses)
    if not anything_down or anything_answered:
        return "not_needed", True
    report = check_controls(settings.control_urls, probe, timeout=settings.timeout_s)
    return ("healthy", True) if report.healthy else ("failed", False)


def lambda_handler(event, context):
    logs.bind(context)
    settings = Settings.from_env()
    repo = Repo()
    publish = make_publisher()
    now = utcnow()

    endpoints = [e for e in repo.list_enabled_endpoints() if e.get("url")]
    results = []
    if endpoints:
        workers = max(1, min(settings.max_workers, len(endpoints)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(
                pool.map(lambda e: probe(e["url"], timeout=settings.timeout_s), endpoints)
            )

    statuses = [
        classify(result, int(endpoint.get("expected_status", 200)), settings.degraded_ms)
        for endpoint, result in zip(endpoints, results, strict=True)
    ]
    controls, controls_ok = _judge_connectivity(settings, statuses)

    summary = {
        "checked": len(endpoints),
        "up": 0,
        "degraded": 0,
        "down": 0,
        "inconclusive": 0,
        "errors": 0,
    }
    counter = {UP: "up", DEGRADED: "degraded", DOWN: "down", INCONCLUSIVE: "inconclusive"}
    for endpoint, result in zip(endpoints, results, strict=True):
        try:
            status = apply_result(
                endpoint, result, repo, publish, now, settings, controls_ok=controls_ok
            )
        except Exception:
            summary["errors"] += 1
            logger.exception(
                "failed to process endpoint",
                extra={"fields": {"endpoint_id": endpoint.get("endpoint_id")}},
            )
            continue
        summary[counter[status]] += 1

    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    repo.record_heartbeat(now, {**summary, "controls": controls})
    print(_emf(summary, latencies, now, controls))
    logger.info("run complete", extra={"fields": {**summary, "controls": controls}})

    if summary["errors"]:
        raise RuntimeError(
            f"{summary['errors']} of {summary['checked']} endpoints failed internally"
        )
    return summary
