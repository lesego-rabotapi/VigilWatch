# ADR 0003: EMF metrics without per-endpoint dimensions

- Status: accepted (2026-10-02)

## Context

The first checker called `PutMetricData` with an `Endpoint` dimension. Every distinct dimension
value is a separate custom metric; CloudWatch includes 10 for free and bills each additional
one monthly. Metric count would grow with every URL anyone registered on a public dashboard,
and every `PutMetricData` call is an API request.

## Decision

The checker prints one Embedded Metric Format (EMF) log line per run, namespace `VigilWatch`,
with a single dimension `Service=uptime-check` and four metrics: `ChecksRun`, `EndpointsDown`,
`EndpointsDegraded`, `AvgLatencyMs` (seven by Stage 4: `EndpointsInconclusive`,
`RunsCompleted` and `ControlProbeFailed` were added for [ADR 0006](0006-checker-honesty.md)). Per-endpoint detail lives in DynamoDB and the logs.

Amended 2026-10-27: the dimension is now `FunctionName` (the checker's own function name, for
example `vigilwatch-prod-uptime-check`). Dev and prod share one account, and with a fixed `Service`
value a dev run would feed prod's `checker-blind` alarm. Still one value per environment, so the
metric count per environment is unchanged.

## Consequences

- A fixed seven custom metrics, inside the free tier, regardless of how many URLs are monitored.
- No `cloudwatch:PutMetricData` permission is needed; metrics come from the log line the
  function already writes.
- Per-endpoint latency graphs come from the dashboard (DynamoDB), not CloudWatch.
- A test asserts the EMF directive has no per-endpoint dimension.

## What the per-endpoint design would have cost

Computed by `scripts/cardinality_cost.py` (`computed`, not measured): CloudWatch's list price of $0.30
per custom metric per month beyond the 10 free ones, us-east-1, and either one metric per URL (a lower bound) or all seven
checker metrics carrying the dimension, which is what the first checker did. The price is not yet verified
for af-south-1 (`NEEDS-AWS`).

| Design | URLs monitored | Metrics per URL | Custom metrics | Monthly cost (USD, computed) |
|---|---|---|---|---|
| `Endpoint` dimension, one metric per URL (lower bound) | 10 | 1 | 10 | $0.00 |
| `Endpoint` dimension, one metric per URL (lower bound) | 100 | 1 | 100 | $27.00 |
| `Endpoint` dimension, one metric per URL (lower bound) | 1,000 | 1 | 1,000 | $297.00 |
| `Endpoint` dimension on every checker metric | 100 | 7 | 700 | $207.00 |
| `Endpoint` dimension on every checker metric | 1,000 | 7 | 7,000 | $2097.00 |
| Fixed `FunctionName` dimension (this project) | any | n/a | 7 | $0.00 |
