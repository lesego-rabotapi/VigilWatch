"""Scheduled uptime checker (EventBridge -> Lambda).

Probes every enabled endpoint in parallel, then persists results serially
(boto3 resources are not thread-safe). Endpoint downtime is data, not an
error; the invocation only fails when VigilWatch itself could not process an
endpoint, so the Lambda Errors alarm means "the monitor is broken".
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from common.checker import Settings, apply_result, make_publisher, probe
from common.repo import Repo
from common.status import DEGRADED, DOWN, UP

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _emf(summary: dict, latencies: list[float], now: datetime) -> str:
    values = {
        "ChecksRun": summary["checked"],
        "EndpointsDown": summary["down"],
        "EndpointsDegraded": summary["degraded"],
    }
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


def lambda_handler(event, context):
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

    summary = {"checked": len(endpoints), "up": 0, "degraded": 0, "down": 0, "errors": 0}
    counter = {UP: "up", DEGRADED: "degraded", DOWN: "down"}
    for endpoint, result in zip(endpoints, results, strict=True):
        try:
            status = apply_result(endpoint, result, repo, publish, now, settings)
        except Exception:
            summary["errors"] += 1
            logger.exception("failed to process endpoint %s", endpoint.get("endpoint_id"))
            continue
        summary[counter[status]] += 1

    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    print(_emf(summary, latencies, now))
    logger.info("run complete %s", json.dumps(summary))

    if summary["errors"]:
        raise RuntimeError(
            f"{summary['errors']} of {summary['checked']} endpoints failed internally"
        )
    return summary
