"""The API handlers behind a local HTTP adapter, over real tables on the moto server."""

import pytest

import uptime_check
from tests.integration.helpers import call

pytestmark = pytest.mark.req("VW-001", "VW-012")


def test_registering_a_url_returns_its_first_check_and_get_checks_agrees(api, target):
    status, created = call("POST", f"{api}/register", {"url": target.url})
    assert status == 201 and created["status"] == "UP"

    status, fetched = call("GET", f"{api}/checks?url={target.url}")
    assert status == 200
    assert fetched["endpoint_id"] == created["endpoint_id"]
    assert fetched["status"] == "UP"
    assert len(fetched["recent_latencies"]) == 1


def test_registering_the_same_url_again_is_a_200_not_a_second_endpoint(api, target):
    assert call("POST", f"{api}/register", {"url": target.url})[0] == 201
    status, again = call("POST", f"{api}/register", {"url": target.url})
    assert status == 200
    status, fetched = call("GET", f"{api}/checks?url={target.url}")
    assert status == 200 and len(fetched["recent_latencies"]) == 1


@pytest.mark.negative
def test_an_unmonitored_url_is_not_found(api, target):
    status, body = call("GET", f"{api}/checks?url={target.url}")
    assert status == 404
    assert "not being monitored" in body["message"]


@pytest.mark.negative
def test_a_registration_without_a_url_is_rejected(api):
    status, body = call("POST", f"{api}/register", {})
    assert status == 400
    assert "url" in body["message"]


def test_the_scheduled_checker_and_the_api_see_the_same_tables(api, target):
    call("POST", f"{api}/register", {"url": target.url})
    target.status = 500

    uptime_check.lambda_handler({}, None)

    status, fetched = call("GET", f"{api}/checks?url={target.url}")
    assert status == 200
    assert [p["status"] for p in fetched["recent_latencies"]][-1] == "DOWN"
