import base64
import json
from datetime import UTC, datetime

import pytest

import register_endpoint
from common.repo import Repo
from common.status import CheckResult
from common.urlguard import UnresolvableHost, endpoint_id

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
PUBLIC = {
    "example.com": ["93.184.215.14"],
    "other.example.com": ["93.184.215.15"],
    "internal.corp": ["10.0.0.5"],
}


def http_event(body, *, raw=False, b64=False):
    payload = body if raw else json.dumps(body)
    if b64:
        payload = base64.b64encode(payload.encode()).decode()
    return {
        "version": "2.0",
        "routeKey": "POST /register",
        "rawPath": "/register",
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"method": "POST", "path": "/register"}},
        "body": payload,
        "isBase64Encoded": b64,
    }


def call(event):
    response = register_endpoint.lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"]), response["headers"]


@pytest.fixture(autouse=True)
def env(tables, monkeypatch):
    def resolver(host):
        if host not in PUBLIC:
            raise UnresolvableHost(host)
        return PUBLIC[host]

    probes = []

    def fake_probe(url, **_):
        probes.append(url)
        return CheckResult(status_code=200, latency_ms=87.0)

    monkeypatch.setattr(register_endpoint, "resolver", resolver)
    monkeypatch.setattr(register_endpoint, "probe", fake_probe)
    monkeypatch.setattr(register_endpoint, "utcnow", lambda: NOW)
    monkeypatch.delenv("MAX_ENDPOINTS", raising=False)
    return probes


def test_registers_new_endpoint_and_runs_first_check(env):
    status, body, headers = call(http_event({"url": "https://Example.com"}))

    assert status == 201
    assert body["url"] == "https://example.com/"
    assert body["endpoint_id"] == endpoint_id("https://example.com/")
    assert body["status"] == "UP"
    assert body["latest_latency_ms"] == 87
    assert body["uptime_30d"] == 100.0
    assert env == ["https://example.com/"]

    stored = Repo().get_endpoint(body["endpoint_id"])
    assert stored["status"] == "UP"
    assert headers["Content-Type"] == "application/json"


def test_reregistering_is_idempotent_and_does_not_probe_again(env):
    call(http_event({"url": "https://example.com/"}))
    status, body, _ = call(http_event({"url": "https://EXAMPLE.com"}))
    assert status == 200
    assert body["url"] == "https://example.com/"
    assert len(env) == 1
    assert Repo().count_endpoints() == 1


def test_legacy_endpoint_field_is_accepted():
    status, body, _ = call(http_event({"endpoint": "https://example.com/"}))
    assert status == 201


def test_base64_body_is_decoded():
    status, _, _ = call(http_event({"url": "https://example.com/"}, b64=True))
    assert status == 201


@pytest.mark.parametrize(
    "event",
    [
        http_event("{not json", raw=True),
        http_event("[]", raw=True),
        http_event({}),
        http_event({"url": ""}),
        http_event({"url": 42}),
        {"version": "2.0", "requestContext": {"http": {"method": "POST"}}},
    ],
)
def test_bad_requests_are_400(event):
    status, body, _ = call(event)
    assert status == 400
    assert body["message"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:9001/",
        "http://internal.corp/",
        "https://admin:secret@example.com/",
    ],
)
def test_ssrf_targets_are_rejected_and_never_stored_or_probed(url, env):
    status, body, _ = call(http_event({"url": url}))
    assert status == 400
    assert Repo().count_endpoints() == 0
    assert env == []


def test_unresolvable_host_is_400_with_clear_message():
    status, body, _ = call(http_event({"url": "https://nope.invalid/"}))
    assert status == 400
    assert "resolve" in body["message"]


@pytest.mark.parametrize("expected", [0, 99, 600, "200", True])
def test_expected_status_must_be_a_valid_http_status(expected):
    status, _, _ = call(http_event({"url": "https://example.com/", "expected_status": expected}))
    assert status == 400


def test_expected_status_is_stored():
    _, body, _ = call(http_event({"url": "https://example.com/", "expected_status": 204}))
    assert Repo().get_endpoint(body["endpoint_id"])["expected_status"] == 204


def test_endpoint_cap_returns_429(monkeypatch):
    monkeypatch.setenv("MAX_ENDPOINTS", "1")
    assert call(http_event({"url": "https://example.com/"}))[0] == 201
    status, body, _ = call(http_event({"url": "https://other.example.com/"}))
    assert status == 429
    assert "limit" in body["message"].lower()


def test_first_check_failure_still_registers(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("probe crashed")

    monkeypatch.setattr(register_endpoint, "apply_result", boom)
    status, body, _ = call(http_event({"url": "https://example.com/"}))
    assert status == 201
    assert body["status"] == "UNKNOWN"


def test_cors_is_owned_by_api_gateway_not_the_function():
    _, _, headers = call(http_event({"url": "https://example.com/"}))
    assert not any(h.lower().startswith("access-control-") for h in headers)
