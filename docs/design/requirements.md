# VigilWatch requirements

User stories with acceptance criteria. Each story has an ID (`VW-nnn`) that tests cite, so
[traceability.md](traceability.md) can show what proves what. Stories describe behaviour that exists
today; planned work (honest checker, authentication) is added here when its stage starts, with its tests.

**Actors:** *visitor* (uses the dashboard), *owner* (deploys and operates the stack).

## Monitoring

### VW-001: Register a URL to monitor

As a visitor I want to submit a URL so that it is checked from then on.

**Acceptance:**
- A new URL returns 201 with the dashboard payload, including the result of an immediate first check.
- Submitting the same URL again (any case, with or without the default port) returns 200 and does not create a second endpoint.
- Missing, malformed or non-object request bodies return 400 with a message.

### VW-002: Refuse unsafe URLs

As an owner I want the checker to refuse internal or malformed targets so that it cannot be used to probe private networks.

**Acceptance:**
- Only `http` and `https` URLs are accepted; credentials in the URL, over-long URLs and invalid ports are rejected.
- Loopback, private, link-local (including cloud metadata), carrier-grade NAT, multicast and unspecified addresses are rejected, for IPv4 and IPv6.
- A hostname is rejected if any of its addresses is non-public.
- The same check runs again before every probe, because DNS can change.

### VW-003: Bound the number of monitored endpoints

As an owner I want a cap on monitored URLs so that runtime and cost stay bounded.

**Acceptance:**
- Registering beyond the cap returns 429; re-registering an existing URL still succeeds at the cap.
- The cap is configurable and has an upper bound enforced in infrastructure.

### VW-004: Check endpoints on a schedule

As a visitor I want my URL checked every few minutes without doing anything.

**Acceptance:**
- A schedule invokes the checker, and the checker is permitted to be invoked by it.
- Each enabled endpoint is probed and the result is stored; disabled or malformed items are skipped.
- A failure on one endpoint does not stop the others; the run fails only if VigilWatch itself could not process an endpoint.

### VW-005: Classify health

As a visitor I want a clear status for each check.

**Acceptance:**
- UP when the status code matches and latency is under the threshold (default 1000 ms).
- DEGRADED when the status code matches but latency is at or above the threshold.
- DOWN on a status mismatch, timeout or connection error.
- The expected status code is configurable per endpoint (100 to 599).

### VW-006: Probe politely and safely

As an owner I want probes that cannot be redirected inward and that identify themselves.

**Acceptance:**
- Redirects are not followed; a 3xx is reported as the status it is.
- Probes send an identifying `User-Agent`; timeouts and connection errors become results, not exceptions.

## History and reporting

### VW-007: Report 30-day uptime

As a visitor I want an uptime percentage over 30 days.

**Acceptance:**
- Uptime is computed from daily rollups, counting DEGRADED as up, and ignores days outside the window.
- With no data the value is null rather than 0 or 100.

### VW-008: Show recent latency

As a visitor I want a latency trend.

**Acceptance:**
- The payload contains the 20 most recent checks, oldest first, with latency (null on failure) and status.

### VW-009: Record incidents

As a visitor I want outages recorded with start, end and duration.

**Acceptance:**
- After N consecutive DOWN results (default 2) an incident opens; one blip does not.
- The next UP result closes it and records the duration.
- Incidents are returned with a human-readable duration and a resolved flag.

### VW-010: Alert once, then confirm recovery

As an owner I want one email when a target goes down and one when it recovers, not one per check.

**Acceptance:**
- Exactly one DOWN notification is published per incident, and a RECOVERED notification when it closes.
- The time of the last alert is stored and shown.
- If no notification topic is configured, incidents are still recorded.

### VW-011: Stable dashboard payload

As a visitor I want the dashboard to keep working as the backend evolves.

**Acceptance:**
- `POST /register` and `GET /checks` return the same payload shape, validated against a JSON Schema shared by the Python and frontend tests.
- Every field the frontend reads exists in the schema.
- Functions set no CORS headers; the API gateway owns CORS.

### VW-012: Clear errors for lookups

As a visitor I want a useful message when I ask about something that does not exist.

**Acceptance:**
- `GET /checks` without a URL or with an invalid URL returns 400; an unregistered URL returns 404; each has a message.

### VW-013: Bounded storage

As an owner I want old data to expire on its own so that storage stays inside the free tier.

**Acceptance:**
- Raw checks expire after 48 hours; rollups and incidents after 31 days; expiry uses the table TTL attribute.

## Dashboard

### VW-014: Safe, readable dashboard

As a visitor I want the dashboard to show status and errors safely.

**Acceptance:**
- All server-provided text is rendered as text, never as HTML.
- A brand-new endpoint with no data renders without errors.
- API error messages are shown to the user; the API address comes from generated runtime configuration.

## Operations and security

### VW-015: Observe the monitor itself

As an owner I want to know when monitoring is broken.

**Acceptance:**
- Each run emits one metric record with a fixed set of metrics and no per-URL dimension.
- Alarms exist for checker errors, a checker that stopped running, dead-lettered runs and API 5xx, and notify the alert topic.

### VW-016: Least privilege and private hosting

As an owner I want each component to hold only the access it needs.

**Acceptance:**
- Each function has its own role with no wildcard actions or resources; the read API cannot write.
- The dashboard bucket is private and readable only through the CDN; viewers are redirected to HTTPS.
- The public API is throttled.

### VW-017: Safe, gated deployment

As an owner I want deployments to be reviewed, keyless and reproducible.

**Acceptance:**
- Deployment uses short-lived federated credentials, never stored keys.
- The reviewed plan is the one applied, after an approval gate, and deploys are serialized.
- Infrastructure uses one pinned Terraform version, and AWS-dependent jobs skip cleanly until configured.

### VW-018: Clean repository

As a maintainer I want state, build artifacts and caches kept out of version control.

**Acceptance:**
- No Terraform state, bundles or caches are tracked; the provider lock file is.

### VW-019: Honest documentation

As a reader I want the documentation to match what exists.

**Acceptance:**
- Documents do not reference removed components, code fences are balanced, links resolve and named outputs exist.

### VW-020: Efficient warm invocations

As an owner I want repeat invocations to be fast and cheap.

**Acceptance:**
- AWS clients are created once per execution environment and reused by later invocations, not rebuilt per request.
- Clients are created on first use rather than at import time.

### VW-021: Traceable logs

As an owner I want to follow one request through the logs.

**Acceptance:**
- Every log line is one JSON object with level, message, logger and time.
- Lines written during an invocation carry that invocation's request ID, and exceptions are included on the same line.
- The log level is configurable, and Lambda's own log handler is reformatted rather than duplicated.

### VW-022: An honest checker

As an owner I want VigilWatch to say "I cannot tell" when its own connection is broken, so that a monitoring fault is never reported as my website being down.

**Acceptance:**
- When every target looks down, the checker probes its control URLs. If none answers, the results are INCONCLUSIVE.
- An INCONCLUSIVE result is recorded but is not a failure to count, does not open or close an incident, sends no alert, and is excluded from uptime. Earlier failure counts and open incidents are left as they were.
- A target that answers correctly proves connectivity, so control URLs are not probed and failing targets in the same run are reported as DOWN.
- With no control URLs configured the behaviour is unchanged.
- Every completed run writes a heartbeat and emits RunsCompleted, EndpointsInconclusive and, when connectivity was checked, ControlProbeFailed.

### VW-023: Alerts that arrive and do not nag

As an owner I want the DOWN email to arrive even if the first attempt failed, and I want a choice about how noisy recovery and reminders are.

**Acceptance:**
- If the DOWN alert for an open incident was not delivered, it is retried on the next failing check. An alert sent for an earlier incident does not count as delivered.
- An incident closes only after RECOVERY_THRESHOLD consecutive healthy checks (default 1, so behaviour is unchanged); a failure in between restarts the count without raising a new alert.
- With REMINDER_MINUTES above 0, a "still down" email is sent while the incident stays open and that long has passed since the last alert (default 0 = off).
- The endpoint cap holds under concurrent registrations (the counter is updated in the same transaction as the endpoint).
