# System overview

## User journey

1. The user enters a URL on the dashboard.
2. `POST /register` validates it (SSRF guard), stores it and runs a first check straight away.
3. The dashboard shows status, latency and uptime, then polls `GET /checks` every 15 seconds.
4. From then on the scheduled checker probes the URL every 5 minutes.
5. After 2 consecutive failed checks an incident opens and one alert email is sent.
6. When the URL recovers, the incident closes and a recovery email is sent.

## End-to-end workflow

1. EventBridge triggers the `uptime_check` Lambda every 5 minutes.
2. The Lambda reads the enabled endpoints from DynamoDB (at most 10).
3. It re-validates each URL and sends an HTTP GET (5 s timeout, redirects not followed).
4. Each result is classified as UP, DEGRADED (slower than 1 s) or DOWN.
5. The raw check (kept 48 h) and the daily rollup (kept 31 days) are written to DynamoDB.
6. The endpoint's state machine opens or closes incidents and publishes to SNS.
7. One EMF log line becomes CloudWatch metrics; function logs go to CloudWatch Logs.
8. CloudWatch alarms watch the monitor itself (errors, missed runs, DLQ, API 5xx).
9. The dashboard calls API Gateway, which invokes the `get_checks` Lambda.
10. `get_checks` reads the endpoint, the last 20 checks, 30 daily rollups and recent incidents.
11. The dashboard renders status, 30-day uptime, the latency trend and incidents.
