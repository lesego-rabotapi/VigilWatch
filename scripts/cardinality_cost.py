"""What a per-endpoint metric dimension would cost, as a table (computed, never measured).

Every distinct dimension value is its own custom metric. The first 10 are free; the rest are billed
at CloudWatch's list price for the first 10,000 metrics. The price is the us-east-1 list price and
must be checked for af-south-1 before it is quoted as that region's. Standard library only.

    python scripts/cardinality_cost.py     # the table published in docs/adr/0003-*.md
"""

import argparse
from decimal import Decimal

PRICE_PER_METRIC_MONTH = Decimal("0.30")  # USD, first 10,000 metrics, us-east-1 list price
FREE_METRICS = 10
FIXED_METRICS = 7  # what lambda/uptime_check.py _emf emits under its one FunctionName value
EXAMPLE_URLS = (10, 100, 1000)
WORST_CASE_URLS = (100, 1000)

_CENTS = Decimal("0.01")


def per_endpoint_cost(urls: int, metrics_per_url: int = 1) -> Decimal:
    """Monthly USD when every monitored URL is its own dimension value."""
    if isinstance(urls, bool) or not isinstance(urls, int) or urls < 0:
        raise ValueError(f"urls must be a whole number of 0 or more, not {urls!r}")
    billable = max(0, urls * metrics_per_url - FREE_METRICS)
    return (billable * PRICE_PER_METRIC_MONTH).quantize(_CENTS)


def fixed_dimension_cost() -> Decimal:
    """Monthly USD with one dimension value per environment, however many URLs there are."""
    return (max(0, FIXED_METRICS - FREE_METRICS) * PRICE_PER_METRIC_MONTH).quantize(_CENTS)


def markdown_table() -> str:
    rows = [
        "| Design | URLs monitored | Metrics per URL | Custom metrics "
        "| Monthly cost (USD, computed) |",
        "|---|---|---|---|---|",
    ]
    for label, per_url, counts in (
        ("`Endpoint` dimension, one metric per URL (lower bound)", 1, EXAMPLE_URLS),
        ("`Endpoint` dimension on every checker metric", FIXED_METRICS, WORST_CASE_URLS),
    ):
        for urls in counts:
            rows.append(
                f"| {label} | {urls:,} | {per_url} | {urls * per_url:,} "
                f"| ${per_endpoint_cost(urls, per_url)} |"
            )
    rows.append(
        "| Fixed `FunctionName` dimension (this project) | any | n/a "
        f"| {FIXED_METRICS} | ${fixed_dimension_cost()} |"
    )
    return "\n".join(rows)


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    print(markdown_table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
