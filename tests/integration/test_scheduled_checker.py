"""The scheduled checker over real DynamoDB, SNS and SQS endpoints (moto server, over HTTP)."""

import pytest

import uptime_check
from common.repo import Repo
from tests.integration.helpers import add_endpoint

pytestmark = pytest.mark.req("VW-004", "VW-009", "VW-010")


def run_checker():
    return uptime_check.lambda_handler({}, None)


def test_a_healthy_target_is_recorded_as_up_with_history_and_a_heartbeat(
    stack, local_targets, target
):
    key = add_endpoint(target.url)

    summary = run_checker()

    assert summary["checked"] == 1 and summary["up"] == 1 and summary["errors"] == 0
    repo = Repo()
    assert repo.get_endpoint(key)["status"] == "UP"
    assert len(repo.recent_checks(key)) == 1
    assert repo.heartbeat() is not None
    assert stack.alerts() == []


def test_a_target_that_stays_down_raises_one_alert_through_sns_to_sqs(stack, local_targets, target):
    target.status = 500
    key = add_endpoint(target.url)

    run_checker()  # one failure is below the threshold of two
    assert stack.alerts() == []

    summary = run_checker()
    run_checker()  # still down: the incident is open, so no second alert

    assert summary["down"] == 1
    alerts = stack.alerts()
    assert [a["event"] for a in alerts] == ["DOWN"]
    assert alerts[0]["endpoint_id"] == key and alerts[0]["status_code"] == 500
    assert Repo().incidents(key), "an incident row was written"


def test_recovery_closes_the_incident_and_sends_one_recovered_alert(stack, local_targets, target):
    target.status = 503
    key = add_endpoint(target.url)
    run_checker()
    run_checker()
    assert [a["event"] for a in stack.alerts()] == ["DOWN"]

    target.status = 200
    run_checker()

    assert [a["event"] for a in stack.alerts()] == ["RECOVERED"]
    endpoint = Repo().get_endpoint(key)
    assert endpoint["status"] == "UP" and not endpoint.get("open_incident_start")


@pytest.mark.boundary
def test_a_single_failure_then_a_success_never_alerts(stack, local_targets, target):
    target.status = 500
    add_endpoint(target.url)
    run_checker()
    target.status = 200
    run_checker()
    assert stack.alerts() == []


def test_an_expected_non_200_status_counts_as_up(stack, local_targets, target):
    target.status = 204
    key = add_endpoint(target.url, expected_status=204)
    run_checker()
    assert Repo().get_endpoint(key)["status"] == "UP"
