"""The incident/alert state machine, tested with in-memory fakes: no AWS libraries involved."""

from datetime import UTC, datetime

import pytest

from common.settings import Settings
from common.state import apply_result
from common.status import CheckResult
from common.timefmt import iso

pytestmark = pytest.mark.req("VW-009", "VW-010")

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
START = "2026-10-02T11:50:00Z"
OK = CheckResult(status_code=200, latency_ms=100.0)
SLOW = CheckResult(status_code=200, latency_ms=2500.0)
FAIL = CheckResult(status_code=503, latency_ms=40.0)


class FakeStore:
    def __init__(self):
        self.checks, self.opened, self.closed, self.updates = [], [], [], []

    def record_check(self, endpoint_id, now, status, status_code, latency_ms):
        self.checks.append((endpoint_id, status, status_code, latency_ms))

    def open_incident(self, endpoint_id, start):
        self.opened.append(start)
        return iso(start)

    def close_incident(self, endpoint_id, start_iso, end):
        self.closed.append((start_iso, end))

    def update_endpoint(self, endpoint_id, **fields):
        self.updates.append(fields)


class Alerts:
    def __init__(self, succeed=True):
        self.sent, self.succeed = [], succeed

    def __call__(self, subject, payload):
        self.sent.append((subject, payload))
        return self.succeed


def endpoint(
    failures=0, incident=None, expected=200, successes=0, alerted="auto", last_alert_sent=None
):
    """An endpoint as stored. An open incident normally has had its DOWN alert delivered."""
    item = {
        "endpoint_id": "abc",
        "url": "https://example.com/",
        "expected_status": expected,
        "consecutive_failures": failures,
        "consecutive_successes": successes,
    }
    if incident:
        item["open_incident_start"] = incident
        if last_alert_sent is None and alerted == "auto":
            last_alert_sent = incident
    if last_alert_sent:
        item["last_alert_sent"] = last_alert_sent
    return item


def run(
    result,
    failures=0,
    incident=None,
    threshold=2,
    alerts=None,
    expected=200,
    controls_ok=True,
    successes=0,
    alerted="auto",
    last_alert_sent=None,
    recovery_threshold=1,
    reminder_minutes=0,
):
    store, alerts = FakeStore(), alerts or Alerts()
    status = apply_result(
        endpoint(failures, incident, expected, successes, alerted, last_alert_sent),
        result,
        store,
        alerts,
        NOW,
        Settings(
            failure_threshold=threshold,
            recovery_threshold=recovery_threshold,
            reminder_minutes=reminder_minutes,
        ),
        controls_ok=controls_ok,
    )
    return status, store, alerts, store.updates[-1]


# result, failures before, open incident, threshold, expected (opened, closed, alerts, failures)
DECISION_TABLE = [
    pytest.param(OK, 0, None, 2, (False, False, [], 0), id="healthy stays healthy"),
    pytest.param(SLOW, 1, None, 2, (False, False, [], 0), id="degraded resets the count"),
    pytest.param(FAIL, 0, None, 2, (False, False, [], 1), id="first failure is only counted"),
    pytest.param(FAIL, 1, None, 2, (True, False, ["DOWN"], 2), id="threshold opens an incident"),
    pytest.param(FAIL, 2, START, 2, (False, False, [], 3), id="no repeat alert during incident"),
    pytest.param(FAIL, 0, None, 1, (True, False, ["DOWN"], 1), id="threshold of one is immediate"),
    pytest.param(OK, 4, START, 2, (False, True, ["RECOVERED"], 0), id="recovery closes it"),
    pytest.param(SLOW, 3, START, 2, (False, True, ["RECOVERED"], 0), id="degraded also recovers"),
]


@pytest.mark.parametrize("result, failures, incident, threshold, expected", DECISION_TABLE)
def test_decision_table(result, failures, incident, threshold, expected):
    _, store, alerts, fields = run(result, failures, incident, threshold)
    opened, closed, events, count = expected
    assert bool(store.opened) is opened
    assert bool(store.closed) is closed
    assert [payload["event"] for _, payload in alerts.sent] == events
    assert fields["consecutive_failures"] == count


def test_every_check_is_recorded_with_its_classification():
    status, store, _, _ = run(SLOW)
    assert status == "DEGRADED"
    assert store.checks == [("abc", "DEGRADED", 200, 2500.0)]


def test_expected_status_decides_what_counts_as_down():
    status, *_ = run(CheckResult(status_code=204, latency_ms=10.0), expected=204)
    assert status == "UP"


def test_down_alert_names_the_endpoint_and_the_cause():
    error = CheckResult(status_code=None, latency_ms=None, error="timed out")
    _, _, alerts, _ = run(error, failures=1)
    [(subject, payload)] = alerts.sent
    assert subject == "[VigilWatch] DOWN: https://example.com/"
    assert payload["url"] == "https://example.com/"
    assert payload["endpoint_id"] == "abc"
    assert payload["error"] == "timed out"
    assert payload["timestamp"] == iso(NOW)


def test_the_incident_is_stored_on_the_endpoint_and_the_alert_time_recorded():
    _, store, _, fields = run(FAIL, failures=1)
    assert fields["open_incident_start"] == iso(NOW)
    assert fields["last_alert_sent"] == iso(NOW)
    assert store.opened == [NOW]


def test_recovery_clears_the_stored_incident_and_reports_its_start():
    _, store, alerts, fields = run(OK, failures=3, incident=START)
    assert fields["open_incident_start"] is None
    assert store.closed == [(START, NOW)]
    assert alerts.sent[0][1]["incident_start"] == START


@pytest.mark.negative
def test_a_failed_publish_keeps_the_incident_but_not_the_alert_time():
    _, store, alerts, fields = run(FAIL, failures=1, alerts=Alerts(succeed=False))
    assert store.opened, "the incident must be recorded even if the email could not be sent"
    assert len(alerts.sent) == 1
    assert "last_alert_sent" not in fields


# ---- the checker must not blame a target for the checker's own connectivity failure --------------

BLIND = [
    pytest.param(FAIL, 0, None, id="first failure"),
    pytest.param(FAIL, 1, None, id="would have crossed the threshold"),
    pytest.param(FAIL, 5, START, id="incident already open"),
    pytest.param(CheckResult(None, None, "timed out"), 1, None, id="timeout"),
]


@pytest.mark.negative
@pytest.mark.parametrize("result, failures, incident", BLIND)
def test_a_down_result_is_inconclusive_when_the_connectivity_checks_failed(
    result, failures, incident
):
    status, store, alerts, fields = run(result, failures, incident, controls_ok=False)
    assert status == "INCONCLUSIVE"
    assert not store.opened and not store.closed, "no incident may open or close"
    assert alerts.sent == [], "no alert about the target"
    for untouched in ("consecutive_failures", "open_incident_start", "last_alert_sent"):
        assert untouched not in fields, f"{untouched} must be left exactly as it was"
    assert fields["status"] == "INCONCLUSIVE"
    assert store.checks[-1][1] == "INCONCLUSIVE", "the check is still recorded, as inconclusive"


@pytest.mark.parametrize("result", [OK, SLOW], ids=["up", "degraded"])
def test_a_successful_probe_proves_connectivity_whatever_the_controls_say(result):
    status, _, _, fields = run(result, failures=3, incident=START, controls_ok=False)
    assert status in ("UP", "DEGRADED")
    assert fields["consecutive_failures"] == 0
    assert fields["open_incident_start"] is None, "recovery still closes the incident"


def test_a_real_outage_with_healthy_connectivity_is_unaffected():
    status, store, alerts, _ = run(FAIL, failures=1, controls_ok=True)
    assert status == "DOWN" and store.opened and len(alerts.sent) == 1


# ---- alert quality: flap damping, retry of a failed alert, reminders ----

# NOW is 12:00; incident and alerts are timestamped relative to it.
THIRTY, SIXTY, NINETY = "2026-10-02T11:30:00Z", "2026-10-02T11:00:00Z", "2026-10-02T10:30:00Z"


@pytest.mark.parametrize(
    "result, successes, recovery_threshold, closes, events, stored_successes",
    [
        pytest.param(OK, 0, 1, True, ["RECOVERED"], 0, id="default: one healthy check recovers"),
        pytest.param(OK, 0, 2, False, [], 1, id="damped: first healthy check only counts"),
        pytest.param(OK, 1, 2, True, ["RECOVERED"], 0, id="damped: second healthy check recovers"),
        pytest.param(SLOW, 1, 2, True, ["RECOVERED"], 0, id="degraded counts as healthy"),
        pytest.param(OK, 2, 5, False, [], 3, id="damped: still counting towards five"),
    ],
)
def test_flap_damping_needs_consecutive_healthy_checks_before_an_incident_closes(
    result, successes, recovery_threshold, closes, events, stored_successes
):
    _, store, alerts, fields = run(
        result,
        failures=3,
        incident=START,
        successes=successes,
        recovery_threshold=recovery_threshold,
    )
    assert bool(store.closed) is closes
    assert [p["event"] for _, p in alerts.sent] == events
    assert fields["consecutive_successes"] == stored_successes
    if not closes:
        assert "open_incident_start" not in fields, "the incident stays exactly as it was"


def test_a_failure_in_the_middle_of_recovery_restarts_the_healthy_count():
    _, store, alerts, fields = run(
        FAIL, failures=3, incident=START, successes=1, recovery_threshold=2
    )
    assert fields["consecutive_successes"] == 0
    assert not store.opened and alerts.sent == [], "same incident, already alerted: stay quiet"


def test_healthy_checks_outside_an_incident_never_accumulate():
    _, _, _, fields = run(OK, successes=1, recovery_threshold=3)
    assert fields["consecutive_successes"] == 0


@pytest.mark.negative
def test_a_down_alert_that_failed_to_send_is_retried_on_the_next_failing_check():
    _, store, alerts, fields = run(FAIL, failures=2, incident=START, alerted=None)
    assert [p["event"] for _, p in alerts.sent] == ["DOWN"]
    assert fields["last_alert_sent"] == iso(NOW)
    assert not store.opened, "it is the same incident, not a new one"


@pytest.mark.negative
def test_a_retry_that_fails_again_records_nothing_and_will_be_tried_again():
    _, _, alerts, fields = run(
        FAIL, failures=2, incident=START, alerted=None, alerts=Alerts(succeed=False)
    )
    assert len(alerts.sent) == 1 and "last_alert_sent" not in fields


def test_an_alert_from_an_earlier_incident_does_not_count_as_delivered_for_this_one():
    stale = "2026-10-01T08:00:00Z"
    _, _, alerts, _ = run(FAIL, failures=2, incident=START, last_alert_sent=stale)
    assert [p["event"] for _, p in alerts.sent] == ["DOWN"]


@pytest.mark.parametrize(
    "reminder_minutes, last_alert, expect_reminder",
    [
        (0, NINETY, False),
        (60, THIRTY, False),
        (60, SIXTY, True),
        (60, NINETY, True),
        (30, THIRTY, True),
    ],
)
def test_reminders_fire_only_when_enabled_and_due(reminder_minutes, last_alert, expect_reminder):
    _, _, alerts, fields = run(
        FAIL,
        failures=5,
        incident=START,
        last_alert_sent=last_alert,
        reminder_minutes=reminder_minutes,
    )
    events = [p["event"] for _, p in alerts.sent]
    assert events == (["REMINDER"] if expect_reminder else [])
    assert ("last_alert_sent" in fields) is expect_reminder


def test_a_reminder_says_the_site_is_still_down_and_restarts_the_clock():
    _, _, alerts, fields = run(
        FAIL, failures=5, incident=START, last_alert_sent=NINETY, reminder_minutes=60
    )
    [(subject, payload)] = alerts.sent
    assert subject == "[VigilWatch] STILL DOWN: https://example.com/"
    assert payload["incident_start"] == START
    assert fields["last_alert_sent"] == iso(NOW)


def test_no_reminder_is_sent_for_a_healthy_check():
    _, _, alerts, _ = run(
        OK,
        failures=5,
        incident=START,
        last_alert_sent=NINETY,
        reminder_minutes=60,
        recovery_threshold=2,
    )
    assert alerts.sent == []


def test_no_reminder_while_blind():
    _, _, alerts, _ = run(
        FAIL,
        failures=5,
        incident=START,
        last_alert_sent=NINETY,
        reminder_minutes=60,
        controls_ok=False,
    )
    assert alerts.sent == []
