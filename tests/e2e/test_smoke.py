"""Post-deploy tests against a live environment, through the API only.

    pytest -m e2e tests/e2e --env=dev         # needs API_URL_DEV (or API_URL) and DASHBOARD_URL_DEV
    pytest -m e2e tests/e2e --env=local       # against `python scripts/local_api.py`
    pytest -m e2e -m smoke --env=prod         # read-only subset; needs E2E_READONLY_URL

Tests marked `smoke` only read, so they may run anywhere, including production. Tests that
modify data take the `writable` fixture, which skips them in read-only environments. The API has
no delete route: write tests register one stable, idempotent target, so reruns create nothing new.
"""

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.req("VW-001", "VW-002", "VW-011", "VW-012"), pytest.mark.e2e]

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "contract" / "checks_response.schema.json").read_text()
)
TARGET = "https://example.com/"


def test_register_returns_the_dashboard_payload(proxy, writable):
    response = proxy.register(TARGET)
    assert response.status in (200, 201), response.text
    jsonschema.validate(response.json, SCHEMA)
    assert response.json["url"] == TARGET


@pytest.mark.negative
@pytest.mark.security
def test_a_metadata_service_address_is_refused(proxy, writable):
    response = proxy.register("http://169.254.169.254/latest/meta-data/")
    assert response.status == 400, response.text
    assert response.json["code"] == "unsafe_url"


@pytest.mark.smoke
def test_checks_returns_the_payload_for_a_monitored_url(proxy, monitored_url):
    response = proxy.checks(monitored_url)
    assert response.status == 200, response.text
    jsonschema.validate(response.json, SCHEMA)
    assert response.json["status"] in ("UP", "DEGRADED", "DOWN", "UNKNOWN")


@pytest.mark.smoke
@pytest.mark.negative
def test_an_unregistered_url_is_not_found(proxy):
    response = proxy.checks("https://unregistered.example.org/")
    assert response.status == 404
    assert response.json["code"] == "not_found"


@pytest.mark.smoke
def test_the_dashboard_is_served_with_security_headers_and_the_api_address(dashboard, proxy):
    page = dashboard.get("/")
    assert page.status == 200 and "VigilWatch" in page.text
    assert page.header("content-security-policy"), "the dashboard must send a CSP"

    config = dashboard.get("/config.js")
    assert config.status == 200
    assert proxy.base_url in config.text


@pytest.mark.smoke
def test_cors_allows_the_dashboard_origin(proxy, dashboard):
    reply = proxy.preflight("/register", origin=dashboard.base_url)
    assert reply.status in (200, 204)
    assert reply.header("access-control-allow-origin") == dashboard.base_url
