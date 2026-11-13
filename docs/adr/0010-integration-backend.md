# ADR 0010: Integration tests run against a moto server

- Status: accepted (2026-11-13)

## Context

The mock layer patches boto3 inside the test process with `mock_aws`. That proves the handlers' logic, but nothing
crosses a network boundary: no HTTP, no serialisation, no separate service holding state. The plan reserved an
integration layer for an emulated backend, with LocalStack as the first candidate and moto in server mode as the
fallback. The layer has to run in CI on a stock runner, cost nothing, and need nothing from a laptop beyond Python.

## Decision

**Use the moto server.** `tests/integration/` starts `ThreadedMotoServer` on a free local port and points boto3 at it
with `AWS_ENDPOINT_URL`. Every DynamoDB, SNS and SQS call then travels over HTTP to a separate service, and the
tables are the same ones the Terraform data module creates. The handlers are called through the local HTTP adapter
that `scripts/local_api.py` already uses (API Gateway's payload v2.0 event, one signed-in user), so the API tests go
through a real socket on both sides. Probe targets are small local web servers whose status code a test changes.

**Skip on a laptop, fail in CI.** Without `moto[server]` (Flask), the layer skips locally. When `CI=true` it fails
instead, and the `integration` job also passes pytest's JUnit report through `scripts/check_junit.py`, so a skipped
or missing test turns the job red.

**Its own CI job.** The `python` job runs `-m "not integration"`; the `integration` job runs `-m integration`. A
failure names the layer that broke.

## Not adopted

| Option | Reason | Revisit when |
|---|---|---|
| LocalStack | Its current editions, licensing and sign-in requirements for CI were not checked, and it needs Docker, which a laptop run would also have to install. Coverage of the services used here is **UNVERIFIED** | A needed service (for example EventBridge scheduling or API Gateway v2 routing) must be exercised and moto cannot |
| `mock_aws` in the integration layer | Already the mock layer. A test that never crosses a socket is not an integration test, and a policy test rejects `mock_aws` under `tests/integration/` | Never |
| Testing the EventBridge schedule and API Gateway here | moto's server does not run them as AWS does, so the schedule is invoked by calling the handler and API Gateway is the local adapter. Their real behaviour stays **NEEDS-AWS** and belongs to Stage 10 | The DEV deployment exists |

## Consequences

- Real network calls make this layer slower than the mock layer (about 25 seconds for ten tests, measured once on a
  laptop; not a budget).
- The layer shows that the handlers work against a service speaking the AWS wire protocol. It does not show that
  IAM policies allow the calls; the IAM enforcement tests and Stage 10 cover that.
