"""Every error a real handler returns carries a message and a documented, stable code."""

import json

import pytest

import get_checks
import register_endpoint
from export_schema import load_spec

pytestmark = pytest.mark.req("VW-002", "VW-003", "VW-012")

CODES = set(load_spec()["components"]["schemas"]["ErrorCode"]["enum"])


def _register(body, tables=None):
    return register_endpoint.lambda_handler({"version": "2.0", "body": body}, None)


def _check(url):
    params = None if url is None else {"url": url}
    return get_checks.lambda_handler({"queryStringParameters": params}, None)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    def resolver(host):
        if host.endswith("example.com"):
            return ["93.184.215.14"]
        from common.urlguard import UnresolvableHost

        raise UnresolvableHost(host)

    monkeypatch.setattr(register_endpoint, "resolver", resolver)
    monkeypatch.setattr(register_endpoint, "probe", lambda url, **_: None)
    monkeypatch.setattr(register_endpoint, "apply_result", lambda *a, **k: "UP")


@pytest.mark.negative
@pytest.mark.parametrize(
    "call, status, code",
    [
        (lambda: _register("{not json"), 400, "bad_request"),
        (lambda: _register(json.dumps({})), 400, "bad_request"),
        (lambda: _register(json.dumps({"url": "ftp://example.com/"})), 400, "unsafe_url"),
        (lambda: _register(json.dumps({"url": "http://169.254.169.254/"})), 400, "unsafe_url"),
        (lambda: _register(json.dumps({"url": "https://nope.invalid/"})), 400, "host_unresolvable"),
        (
            lambda: _register(json.dumps({"url": "https://example.com/", "expected_status": 99})),
            400,
            "bad_request",
        ),
        (lambda: _check(None), 400, "validation_error"),
        (lambda: _check("ftp://example.com/"), 400, "unsafe_url"),
    ],
)
def test_client_errors_have_a_message_and_a_documented_code(tables, call, status, code):
    response = call()
    body = json.loads(response["body"])
    assert response["statusCode"] == status
    assert body["code"] == code and body["code"] in CODES
    assert body["message"]


@pytest.mark.negative
def test_not_found_has_the_not_found_code(tables):
    response = _check("https://never-registered.example.org/")
    body = json.loads(response["body"])
    assert (response["statusCode"], body["code"]) == (404, "not_found")


@pytest.mark.negative
def test_the_endpoint_cap_has_the_limit_code(tables, monkeypatch):
    monkeypatch.setenv("MAX_ENDPOINTS", "1")
    assert _register(json.dumps({"url": "https://a.example.com/"}))["statusCode"] == 201
    response = _register(json.dumps({"url": "https://b.example.com/"}))
    body = json.loads(response["body"])
    assert (response["statusCode"], body["code"]) == (429, "limit_reached")
    assert "1 endpoints" in body["message"] or "(1" in body["message"]


@pytest.mark.negative
@pytest.mark.security
def test_an_unexpected_failure_is_a_json_500_not_a_leak(tables, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("dynamodb exploded: arn:aws:dynamodb:af-south-1:123456789012:table/x")

    monkeypatch.setattr(get_checks.Repo, "get_endpoint", broken)
    response = _check("https://example.com/")
    body = json.loads(response["body"])
    assert response["statusCode"] == 500
    assert body["code"] == "internal_error"
    assert "123456789012" not in response["body"]
