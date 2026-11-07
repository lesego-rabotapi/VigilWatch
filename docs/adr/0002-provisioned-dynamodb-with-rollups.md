# ADR 0002: Provisioned DynamoDB with daily rollups

- Status: accepted (2026-10-02)

## Context

The project must cost nothing to run. The DynamoDB always-free tier covers 25 RCU and 25 WCU of
**provisioned** capacity and 25 GB of storage; on-demand requests are billed from the first one.
The dashboard needs 30-day uptime. With a check every 5 minutes, that is about 8,640 raw items per
endpoint, and reading them on every 15-second poll would exceed the free read capacity quickly.

## Decision

- Two tables, `endpoints` and `history`, each provisioned at 5 RCU / 5 WCU (20 of 25 used).
- `history` stores three item types under one partition per endpoint: raw checks (`C#`,
  48 h TTL), daily rollups (`D#`, `ADD total, up`, 31 d TTL) and incidents (`I#`, 31 d TTL).
- Uptime is computed from at most 30 rollup items; the chart uses the last 20 raw checks.
- Expiry uses DynamoDB TTL, whose deletes are free.

## Consequences

- Reads per poll are small and bounded (one GetItem plus three small Queries).
- Writes per check: one PutItem (raw) and one UpdateItem (rollup), plus one endpoint update.
  At 10 endpoints every 5 minutes this is far below 5 WCU.
- Provisioned tables can throttle under sudden load. API throttling and the endpoint cap keep
  load predictable; capacity is a variable, validated to stay inside the free tier.
- No point-in-time recovery (it is billed). The data is re-creatable monitoring history.
