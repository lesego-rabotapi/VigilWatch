"""Scheduled checker: persistence, incident lifecycle, alerting and metrics."""

import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest

import uptime_check
from common.repo import Repo, iso
from common.status import CheckResult

T0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)

OK = CheckResult(status_code=200, latency_ms=120.0)
SLOW = CheckResult(status_code=200, latency_ms=2500.0)
FAIL = CheckResult(status_code=503, latency_ms=40.0)
TIMEOUT = CheckResult(status_code=None, latency_ms=None, error="timed out")


@pytest.fixture
def alerts(tables, sns_topic):
    """Subscribe an SQS queue to the alert topic so published alerts can be read back."""
    sqs = boto3.client("sqs")
    queue_url = sqs.create_queue(QueueName="alerts")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    boto3.client("sns").subscribe(TopicArn=sns_topic, Protocol="sqs", Endpoint=queue_arn)

    def read():
        msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
        for m in msgs:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
        return [json.loads(m["Body"]) for m in msgs]

    return read


@pytest.fixture
def world(tables, monkeypatch):
    """Registered endpoints, a scripted probe and a controllable clock."""
    state = {"now": T0, "script": {}}
    repo = Repo()
    repo.put_endpoint("a", "https://a.example.com/", T0)

    def fake_probe(url, **_):
        outcomes = state["script"].get(url, [OK])
        return outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]

    monkeypatch.setattr(uptime_check, "probe", fake_probe)
    monkeypatch.setattr(uptime_check, "utcnow", lambda: state["now"])

    def run(times=1, step=timedelta(minutes=5)):
        out = None
        for _ in range(times):
            out = uptime_check.lambda_handler({"source": "aws.events"}, None)
            state["now"] += step
        return out

    state["repo"] = repo
    state["run"] = run
    return state


def test_healthy_run_persists_check_and_updates_endpoint(world):
    summary = world["run"]()
    assert summary == {"checked": 1, "up": 1, "degraded": 0, "down": 0, "errors": 0}

    ep = world["repo"].get_endpoint("a")
    assert ep["status"] == "UP"
    assert ep["consecutive_failures"] == 0
    assert ep["last_check"] == iso(T0)
    assert ep["last_latency_ms"] == 120
    [check] = world["repo"].recent_checks("a")
    assert check["status"] == "UP" and check["latency_ms"] == 120
    assert world["repo"].uptime_30d("a", T0) == 100.0


def test_slow_response_is_degraded_not_down(world):
    world["script"]["https://a.example.com/"] = [SLOW]
    assert world["run"]()["degraded"] == 1
    assert world["repo"].get_endpoint("a")["status"] == "DEGRADED"


def test_single_failure_does_not_alert(world, alerts):
    world["script"]["https://a.example.com/"] = [FAIL, OK]
    world["run"]()
    assert alerts() == []
    assert world["repo"].incidents("a") == []
    assert world["repo"].get_endpoint("a")["consecutive_failures"] == 1


def test_second_consecutive_failure_opens_incident_and_alerts_once(world, alerts):
    world["script"]["https://a.example.com/"] = [FAIL, TIMEOUT, FAIL, FAIL]
    world["run"](times=4)

    messages = alerts()
    assert len(messages) == 1
    assert messages[0]["Subject"].startswith("[VigilWatch] DOWN")
    body = json.loads(messages[0]["Message"])
    assert body["url"] == "https://a.example.com/"
    assert body["event"] == "DOWN"

    [incident] = world["repo"].incidents("a")
    assert incident["resolved"] is False
    assert incident["start_time"] == iso(T0 + timedelta(minutes=5))

    ep = world["repo"].get_endpoint("a")
    assert ep["status"] == "DOWN"
    assert ep["consecutive_failures"] == 4
    assert ep["open_incident_start"] == incident["start_time"]
    assert ep["last_alert_sent"] == iso(T0 + timedelta(minutes=5))


def test_recovery_closes_incident_and_sends_recovery_alert(world, alerts):
    world["script"]["https://a.example.com/"] = [FAIL, FAIL, OK]
    world["run"](times=3)

    subjects = [m["Subject"] for m in alerts()]
    assert subjects[0].startswith("[VigilWatch] DOWN")
    assert subjects[1].startswith("[VigilWatch] RECOVERED")

    [incident] = world["repo"].incidents("a")
    assert incident["resolved"] is True
    assert incident["duration_s"] == 300

    ep = world["repo"].get_endpoint("a")
    assert "open_incident_start" not in ep
    assert ep["consecutive_failures"] == 0
    assert ep["status"] == "UP"


def test_failure_threshold_is_configurable(world, alerts, monkeypatch):
    monkeypatch.setenv("FAILURE_THRESHOLD", "1")
    world["script"]["https://a.example.com/"] = [FAIL]
    world["run"]()
    assert len(alerts()) == 1


def test_disabled_endpoints_and_items_without_url_are_skipped(world):
    world["repo"].update_endpoint("a", enabled=False)
    world["repo"].endpoints.put_item(Item={"endpoint_id": "legacy", "enabled": True})
    assert world["run"]()["checked"] == 0


def test_no_topic_configured_still_records_incident(world, monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    world["script"]["https://a.example.com/"] = [FAIL, FAIL]
    world["run"](times=2)
    [incident] = world["repo"].incidents("a")
    assert incident["resolved"] is False
    assert "last_alert_sent" not in world["repo"].get_endpoint("a")


def test_many_endpoints_are_checked(world):
    for i in range(5):
        world["repo"].put_endpoint(f"e{i}", f"https://e{i}.example.com/", T0)
    world["script"]["https://e3.example.com/"] = [FAIL]
    summary = world["run"]()
    assert summary["checked"] == 6
    assert summary["down"] == 1


def test_internal_error_on_one_endpoint_isolates_others_then_raises(world, monkeypatch):
    world["repo"].put_endpoint("b", "https://b.example.com/", T0)
    real = Repo.record_check

    def flaky(self, endpoint_id, *args, **kwargs):
        if endpoint_id == "a":
            raise RuntimeError("dynamodb exploded")
        return real(self, endpoint_id, *args, **kwargs)

    monkeypatch.setattr(Repo, "record_check", flaky)
    with pytest.raises(RuntimeError, match="1 of 2"):
        world["run"]()
    # The healthy endpoint was still processed.
    assert world["repo"].get_endpoint("b")["status"] == "UP"


def test_emits_one_emf_record_without_per_endpoint_dimensions(world, capsys):
    world["repo"].put_endpoint("b", "https://b.example.com/", T0)
    world["script"]["https://b.example.com/"] = [FAIL]
    world["run"]()

    emf = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "_aws" in line
    ]
    assert len(emf) == 1
    record = emf[0]
    directive = record["_aws"]["CloudWatchMetrics"][0]
    assert directive["Namespace"] == "VigilWatch"
    assert directive["Dimensions"] == [["Service"]]
    names = {m["Name"] for m in directive["Metrics"]}
    assert names == {"ChecksRun", "EndpointsDown", "EndpointsDegraded", "AvgLatencyMs"}
    assert record["ChecksRun"] == 2
    assert record["EndpointsDown"] == 1
    assert "url" not in json.dumps(directive).lower()
