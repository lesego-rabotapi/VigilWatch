# Sequence diagrams

The four core flows, each with its failure paths. A **business error** is an expected outcome the caller
can act on (a 4xx response, an endpoint that is down). An **unexpected error** is VigilWatch itself failing
(a dependency error or a bug), which must be visible to the owner and must not corrupt other work.
Requirement IDs refer to [requirements.md](requirements.md). A test checks that every diagram has both
failure paths and names only modules that exist.

## Register a URL

Covers VW-001, VW-002 and VW-003.

```mermaid
sequenceDiagram
    participant B as Browser
    participant G as API Gateway
    participant R as register_endpoint
    participant U as common.urlguard
    participant S as common.repo
    participant C as common.checker
    B->>G: POST /register with url
    G->>R: invoke
    R->>U: validate(url)
    alt Business error: body invalid, URL unsafe or host unresolvable
        U-->>R: UnsafeURL or BadRequest
        R-->>B: 400 with message
    else URL is acceptable
        R->>S: put_endpoint(id, url, cap)
        alt Business error: monitoring limit reached
            S-->>R: EndpointLimitReached
            R-->>B: 429 with message
        else Endpoint already monitored
            S-->>R: existing item
            R-->>B: 200 with current payload
        else New endpoint
            S-->>R: created
            R->>C: probe then apply_result
            alt Unexpected error: first check fails
                C-->>R: exception, logged
                R-->>B: 201 with status UNKNOWN, scheduled check will retry
            else First check recorded
                C-->>R: status stored
                R-->>B: 201 with full payload
            end
        end
    end
    Note over R,B: Unexpected error in DynamoDB or the handler itself<br/>surfaces as a 5xx and the checker-errors and api-5xx alarms
```

## Scheduled check

Covers VW-004, VW-005, VW-006, VW-015 and VW-022.

```mermaid
sequenceDiagram
    participant E as EventBridge
    participant K as uptime_check
    participant S as common.repo
    participant P as common.checker
    participant C as common.controls
    participant T as Target website
    participant Q as DLQ and alarms
    E->>K: rate(5 minutes)
    K->>S: list_enabled_endpoints
    par each enabled endpoint, in parallel
        K->>P: probe(url)
        P->>P: common.urlguard validate again
        alt Business error: target down, slow, wrong status or blocked address
            P-->>K: CheckResult with error or status mismatch
        else Target answers
            P->>T: GET, redirects not followed
            T-->>P: status and latency
            P-->>K: CheckResult
        end
    end
    alt Business error: every target failed and none answered
        K->>C: check_controls(control URLs)
        alt no control answers either
            C-->>K: blind
            Note over K: DOWN results become INCONCLUSIVE, so nothing is counted or alerted
        else a control answers
            C-->>K: connected, so the failures are real
        end
    else at least one target answered, or no control URLs
        Note over K: connectivity is proven or not being judged
    end
    loop each result, one at a time
        K->>P: apply_result
        alt Unexpected error: store or update fails for this endpoint
            P-->>K: exception, logged and counted
            Note right of K: other endpoints still processed
        else Result stored
            P-->>K: status, possibly INCONCLUSIVE
        end
    end
    K->>S: record_heartbeat
    K->>K: print one EMF metrics record
    alt Unexpected error: any endpoint failed internally
        K-->>E: raise, invocation fails
        E->>Q: async failure goes to the DLQ, checker-errors and checker-dlq alarm
    else All processed
        K-->>E: summary
    end
```

## Alerting

Covers VW-009 and VW-010. The threshold defaults to 2 consecutive DOWN results.

```mermaid
sequenceDiagram
    participant K as uptime_check
    participant P as common.checker
    participant S as common.repo
    participant N as SNS topic
    participant O as Owner email
    K->>P: apply_result(endpoint, result)
    P->>S: record_check and daily rollup
    alt Business error: result is DOWN
        P->>P: failures + 1
        alt failures reach the threshold and no incident is open
            P->>S: open_incident
            P->>N: publish DOWN once
            N->>O: email
        else below threshold or incident already open
            Note over P: no new alert
        end
    else Result is UP or DEGRADED
        alt an incident is open
            P->>S: close_incident with duration
            P->>N: publish RECOVERED
            N->>O: email
        else healthy as before
            Note over P: reset failures only
        end
    end
    alt Unexpected error: SNS publish fails
        N-->>P: exception
        P->>P: log it, keep the incident, leave last_alert_sent unchanged
    else Alert published
        P->>S: store last_alert_sent
    end
```

## Read status

Covers VW-007, VW-008, VW-011 and VW-012.

```mermaid
sequenceDiagram
    participant B as Browser
    participant G as API Gateway
    participant R as get_checks
    participant U as common.urlguard
    participant S as common.repo
    B->>G: GET /checks with url
    G->>R: invoke
    alt Business error: url missing or not a valid http or https URL
        R->>U: normalize(url)
        U-->>R: UnsafeURL
        R-->>B: 400 with message
    else URL is well formed
        R->>S: get_endpoint(id)
        alt Business error: URL is not monitored
            S-->>R: none
            R-->>B: 404 with message
        else Endpoint found
            R->>S: recent_checks, uptime_30d, incidents
            S-->>R: history
            R-->>B: 200 with dashboard payload
        end
    end
    Note over R,B: Unexpected error in DynamoDB or the handler itself<br/>surfaces as a 5xx and the api-5xx alarm
```
