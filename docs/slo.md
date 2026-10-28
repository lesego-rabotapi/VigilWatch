# Service level objectives

What "working" means for VigilWatch, in numbers. The objectives apply to prod; dev has no
objectives. They are **targets**: `NEEDS-AWS`, unmeasured until prod has run for a full 30-day
window (Stage 10). Nothing here reports a result.

## Objectives

| Objective | Indicator | Target, over 30 days | Read from | Guarded by |
|---|---|---|---|---|
| Checker freshness | Share of 10-minute windows in which a scheduled run completed and could see the internet (an INCONCLUSIVE run does not count) | 99.5% | Dashboard: checker invocations and errors; saved query `checker-runs` | `vigilwatch-<env>-checker-not-running`, `vigilwatch-<env>-checker-errors`, `vigilwatch-<env>-checker-blind` |
| API availability | Share of API requests answered without a 5xx | 99.5% | Dashboard: API requests and 5xx; saved query `api-5xx` | `vigilwatch-<env>-api-5xx` |
| API latency | Share of 5-minute periods whose p99 API latency is under 500 ms | 99.5% of periods | Dashboard: latency; saved query `api-slow` | No alarm: read on the dashboard. Prod and dev use 7 of the 10 free alarms; one could be added if this objective is missed |

**Why these numbers.** A five-minute check interval, two consecutive failures before an alert (the default
`failure_threshold`), and Lambda cold starts all limit how fresh and fast the service can be. 99.5% leaves room for those
and for a deploy or two a month, and it can be measured with free metrics.

## Error budget

99.5% over 30 days leaves 0.5% for failure: **216 minutes** of stale checks or of failing API time in
30 days. For latency it is 43 of the 8,640 five-minute periods in 30 days.

- While an objective has budget left, deploys go ahead as usual.
- When a budget is spent within a 30-day window, **freeze** feature promotions to prod. Only fixes are
  promoted, until the window's spending falls back under the budget.
- Spending more than half a budget in one incident gets a short written note in the drift or incident
  issue: what happened, how it was noticed, and what changes.

## Where to read them

- The dashboard `<env>-golden-signals` (`vigilwatch-prod-golden-signals` in prod) shows latency, traffic,
  errors and saturation for the API, functions, queue and tables.
- The saved CloudWatch Logs Insights queries under `vigilwatch-prod/` find the matching log lines:
  `function-errors`, `checker-runs`, `api-5xx` and `api-slow`.
- The alarms notify the environment's topic (runbook, section 5); what to do for each failure is in
  `docs/resilience.md`.
