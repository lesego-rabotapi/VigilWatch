"""Post-deploy smoke tests against a live API (and optionally the dashboard).

    API_URL=https://<id>.execute-api.<region>.amazonaws.com \
    DASHBOARD_URL=https://<id>.cloudfront.net \
    pytest -m e2e tests/e2e

Deselected by default (pytest.ini). Registering https://example.com is
idempotent, so repeated deploys reuse the same endpoint slot.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema
import pytest

pytestmark = pytest.mark.e2e

API_URL = os.environ.get("API_URL", "").rstrip("/")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
SCHEMA = json.loads(
    (Path(__file__).parents[1] / "contract" / "checks_response.schema.json").read_text()
)
TARGET = "https://example.com/"


def request(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode()


@pytest.fixture(scope="module", autouse=True)
def require_api():
    if not API_URL:
        pytest.skip("API_URL not set")


def test_register_returns_dashboard_payload():
    status, _, body = request("POST", f"{API_URL}/register", {"url": TARGET})
    assert status in (200, 201), body
    payload = json.loads(body)
    jsonschema.validate(payload, SCHEMA)
    assert payload["url"] == TARGET


def test_checks_returns_history_for_registered_url():
    request("POST", f"{API_URL}/register", {"url": TARGET})
    status, _, body = request("GET", f"{API_URL}/checks?url={TARGET}")
    assert status == 200, body
    payload = json.loads(body)
    jsonschema.validate(payload, SCHEMA)
    assert payload["status"] in ("UP", "DEGRADED", "DOWN")
    assert payload["last_check"] is not None


def test_ssrf_target_is_rejected():
    status, _, body = request(
        "POST", f"{API_URL}/register", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert status == 400, body


def test_unknown_url_is_404():
    status, _, _ = request("GET", f"{API_URL}/checks?url=https://unregistered.example.org/")
    assert status == 404


def test_dashboard_is_served_with_security_headers_and_config():
    if not DASHBOARD_URL:
        pytest.skip("DASHBOARD_URL not set")
    status, headers, body = request("GET", f"{DASHBOARD_URL}/")
    assert status == 200
    assert "VigilWatch" in body
    lower = {k.lower(): v for k, v in headers.items()}
    assert "content-security-policy" in lower

    status, _, config = request("GET", f"{DASHBOARD_URL}/config.js")
    assert status == 200
    assert API_URL in config


def test_cors_allows_the_dashboard_origin():
    if not DASHBOARD_URL:
        pytest.skip("DASHBOARD_URL not set")
    status, headers, _ = request(
        "OPTIONS",
        f"{API_URL}/register",
        headers={
            "Origin": DASHBOARD_URL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert status in (200, 204)
    lower = {k.lower(): v for k, v in headers.items()}
    assert lower.get("access-control-allow-origin") == DASHBOARD_URL
