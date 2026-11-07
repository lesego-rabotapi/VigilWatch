"""The cost of a per-endpoint metric dimension, as arithmetic that can be checked by hand.

Inputs are CloudWatch's list price for a custom metric ($0.30 per metric per month for the first
10,000, us-east-1) and the 10 custom metrics the free tier includes. The numbers are computed, not
measured, and the price must be checked for af-south-1 before being quoted as that region's.
"""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import cardinality_cost
import pytest

import uptime_check

pytestmark = pytest.mark.req("VW-019")

ADR = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "adr"
    / "0003-emf-metrics-without-per-endpoint-dimensions.md"
)


@pytest.mark.parametrize(
    "urls, expected",
    [
        (0, "0.00"),
        (5, "0.00"),
        (10, "0.00"),  # exactly the free allowance
        (11, "0.30"),  # one metric over
        (100, "27.00"),
        (1000, "297.00"),
    ],
)
def test_one_metric_per_url_is_billed_beyond_the_free_ten(urls, expected):
    assert cardinality_cost.per_endpoint_cost(urls) == Decimal(expected)


def test_each_extra_metric_per_url_multiplies_the_bill():
    # 100 URLs x 3 metrics = 300 metrics, 290 billable
    assert cardinality_cost.per_endpoint_cost(100, metrics_per_url=3) == Decimal("87.00")


def test_the_fixed_dimension_costs_nothing_however_many_urls_are_monitored():
    assert cardinality_cost.fixed_dimension_cost() == Decimal("0.00")
    assert cardinality_cost.FIXED_METRICS <= cardinality_cost.FREE_METRICS


def test_the_fixed_metric_count_is_what_the_checker_really_emits():
    summary = {"checked": 1, "down": 0, "degraded": 0, "inconclusive": 0}
    os.environ.setdefault("AWS_LAMBDA_FUNCTION_NAME", "vigilwatch-test-uptime-check")
    line = json.loads(uptime_check._emf(summary, [10.0], datetime.now(UTC), "healthy"))
    emitted = line["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    assert len(emitted) == cardinality_cost.FIXED_METRICS


@pytest.mark.parametrize("bad", [-1, 1.5])
def test_a_negative_or_fractional_url_count_is_refused(bad):
    with pytest.raises(ValueError):
        cardinality_cost.per_endpoint_cost(bad)


def test_the_table_is_what_adr_0003_publishes():
    adr = ADR.read_text(encoding="utf-8")
    assert cardinality_cost.markdown_table() in adr, "run: python scripts/cardinality_cost.py"
    assert "computed" in adr.lower()
