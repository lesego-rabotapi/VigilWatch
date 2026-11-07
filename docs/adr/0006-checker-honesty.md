# ADR 0006: Tell a failed check from a failed checker

- Status: accepted (2026-10-25)

## Context

A monitor that cannot reach the internet sees every target fail. Reported naively, that looks like a mass
outage: incidents open, emails go out, and the owner learns about a fault in the monitor by being told
their sites are down. A failed **check** means "the target answered wrongly while the checker was healthy".
A failed **checker** means "the monitor cannot be trusted right now". The system must never turn the
second into the first.

## Decision

**Control URLs.** The checker has a short list of addresses expected to be up: this deployment's own
`healthz.txt` (served by its CloudFront distribution) plus independent sites (`extra_control_urls`).
A control answers when it returns a 2xx or 3xx status without an error.

**When they are probed.** Only when something is down and nothing answered. If any target that answers
correctly exists in the run, the checker's outbound path is proven and the controls are not used, so a
healthy fleet costs no extra requests and a real outage on one site is never second-guessed.

**What INCONCLUSIVE means.** If all targets failed and no control answers, each DOWN result is recorded as
`INCONCLUSIVE`. It is stored (the dashboard shows a hatched bar and an explanation) but is not a failure to
count, does not open or close an incident, sends no target alert, and stays out of the uptime figure.
Earlier failure counts and open incidents are left exactly as they were, so a blind cycle neither
advances nor erases a real outage.

| Status is DOWN | Any target answered | A control answers | Incident open | Result |
|---|---|---|---|---|
| no | n/a | n/a | n/a | normal UP or DEGRADED handling (recovery closes an open incident) |
| yes | yes | not probed | any | DOWN counted as usual |
| yes | no | yes | any | DOWN counted as usual |
| yes | no | no | any | INCONCLUSIVE: nothing counted, opened, closed or sent |
| yes | no | no controls configured | any | DOWN counted as usual (feature off) |

**Making blindness visible.** Every completed run writes a heartbeat item and emits `RunsCompleted`,
`EndpointsInconclusive` and, when connectivity was actually checked, `ControlProbeFailed` (1 or 0). The
`checker-blind` alarm fires when it is 1 in 2 of the last 3 five-minute periods, so silence caused by
blindness is never invisible to the owner. `checker-not-running` still covers a checker that does not run
at all.

## Consequences

- A fault in the monitor produces one alarm to the owner instead of a flood of false site-down emails.
- The design prefers false silence about a target to a false alarm about it, and compensates with the
  alarm above. If a real outage coincides with every control being unreachable, it stays hidden until a
  control answers or a target does. Using several independent controls makes that unlikely.
- Control probes add at most a handful of requests, and only in runs where everything failed.

## Limits

- **A single region and a single Lambda.** Controls detect a broken outbound path. They cannot detect a
  regional AWS fault that also takes down DynamoDB or the schedule: that is the job of the alarms, and
  of nothing in the system if the whole region is gone. Probing from a second region and comparing results
  is the next step and is out of scope for cost reasons.
- Control URLs are third-party or self-hosted services that can themselves fail. One answering control is
  enough, which is why the default has two.
- **Unverified until deployed (NEEDS-AWS):** that the Lambda can reach its own CloudFront health file,
  that CloudWatch extracts `ControlProbeFailed` from the log line, and how the alarm behaves in practice.
