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
`EndpointsDegraded`, `AvgLatencyMs`. Per-endpoint detail lives in DynamoDB and the logs.

## Consequences

- A fixed four custom metrics, inside the free tier, regardless of how many URLs are monitored.
- No `cloudwatch:PutMetricData` permission is needed; metrics come from the log line the
  function already writes.
- Per-endpoint latency graphs come from the dashboard (DynamoDB), not CloudWatch.
- A test asserts the EMF directive has no per-endpoint dimension.
