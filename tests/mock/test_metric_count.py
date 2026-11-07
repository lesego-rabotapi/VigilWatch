"""The cost arithmetic assumes a fixed metric count; the checker must really emit that many."""

import json
from datetime import UTC, datetime

import pytest

import cardinality_cost
import uptime_check

pytestmark = pytest.mark.req("VW-019")


def test_the_fixed_metric_count_is_what_the_checker_really_emits(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "vigilwatch-test-uptime-check")
    summary = {"checked": 1, "down": 0, "degraded": 0, "inconclusive": 0}
    line = json.loads(uptime_check._emf(summary, [10.0], datetime.now(UTC), "healthy"))
    emitted = line["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    assert len(emitted) == cardinality_cost.FIXED_METRICS
