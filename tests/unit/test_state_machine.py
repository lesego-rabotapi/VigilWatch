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


def endpoint(failures=0, incident=None, expected=200):
    item = {
        "endpoint_id": "abc",
        "url": "https://example.com/",
        "expected_status": expected,
        "consecutive_failures": failures,
    }
    if incident:
        item["open_incident_start"] = incident
    return item


def run(result, failures=0, incident=None, threshold=2, alerts=None, expected=200):
    store, alerts = FakeStore(), alerts or Alerts()
    status = apply_result(
        endpoint(failures, incident, expected),
        result,
        store,
        alerts,
        NOW,
        Settings(failure_threshold=threshold),
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
