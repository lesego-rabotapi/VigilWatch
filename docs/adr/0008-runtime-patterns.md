# ADR 0008: Lambda runtime patterns

- Status: accepted (2026-10-25)

## Context

Three small functions run on `python3.12`/arm64 with only the standard library and the boto3 that ships with the
runtime. Two runtime concerns matter: how much work happens on every invocation, and whether one request can be
followed through the logs. Several popular answers exist (Lambda Powertools, SnapStart, Lambda's native JSON log
format). Each adds cost, packaging or unverified behaviour.

## Decision

**Reuse clients.** `common.aws` creates the DynamoDB resource and SNS client lazily and keeps them cached for the
life of the execution environment. Warm invocations skip client construction. Creation is lazy so that importing a
module stays cheap and tests can start mocking AWS before any client exists; the test fixture resets the cache so a
client never outlives the mock it was built in.

**Structured logs from the standard library.** `common.logs` writes one JSON object per line (level, message,
logger, time, request ID, exception). Handlers bind the request ID from the Lambda context at the start of each
invocation. Inside Lambda it reformats the runtime's own handler, so each line is written once.

## Not adopted

| Option | Reason | Revisit when |
|---|---|---|
| Lambda Powertools (Logger, Tracer, Metrics, Idempotency) | Needs a layer or packaged dependency, brings a tracer that incurs X-Ray cost, and the two pieces used here (structured logs, EMF metrics) take about 100 lines of stdlib. Registration is already idempotent by design | Batch processing or distributed idempotency is needed |
| Lambda's native JSON log format (`log_format = "JSON"`) | The checker prints an EMF metrics line with `print`. How the runtime wraps such a line in JSON mode, and whether CloudWatch still extracts the metrics, is unverified. Getting it wrong silently loses the metrics. **NEEDS-AWS** | After the first deployment, by comparing the metrics with the format switched |
| SnapStart for Python | Snapshot caching and restore are billed under Lambda pricing (verify the current page), so they are not free-tier work, and start-up here is small because the code is dependency-light | A measured cold start (task 9.3) shows a problem worth paying for |

## Consequences

- Fewer client constructions per request. The size of the gain is **not measured yet**: no numbers are claimed until
  `scripts/measure_cold_start.py` has run against a deployment.
- Logs are searchable by field in CloudWatch Logs Insights and correlated by `request_id`.
- Anything logged before `bind()` is called in an invocation has no request ID; handlers bind first.
