"""One decorator turns typed errors into consistent JSON responses; unexpected errors never leak."""

import json
from types import SimpleNamespace

import pytest

from common.api import api_handler
from common.endpoints_repo import EndpointLimitReached
from common.errors import LimitError, NotFoundError, UnauthorizedError, ValidationError
from common.http import BadRequest
from common.urlguard import UnresolvableHost, UnsafeURL

pytestmark = pytest.mark.req("VW-012", "VW-021")


def failing(exc):
    @api_handler
    def handler(event, context):
        raise exc

    return handler


def call(handler, request_id="req-1"):
    response = handler({}, SimpleNamespace(aws_request_id=request_id))
    return response["statusCode"], json.loads(response["body"]), response["headers"]


@pytest.mark.parametrize(
    "exc, status, code, message",
    [
        (ValidationError("url is required"), 400, "validation_error", "url is required"),
        (NotFoundError("not monitored"), 404, "not_found", "not monitored"),
        (LimitError("too many"), 429, "limit_reached", "too many"),
        (UnauthorizedError("sign in"), 401, "unauthorized", "sign in"),
        (BadRequest("body must be JSON"), 400, "bad_request", "body must be JSON"),
        (UnsafeURL("private address"), 400, "unsafe_url", "private address"),
        (
            UnresolvableHost("x.invalid"),
            400,
            "host_unresolvable",
            "Could not resolve that host name",
        ),
        (EndpointLimitReached(5), 429, "limit_reached", "Monitoring limit reached (5 endpoints)"),
    ],
)
def test_typed_errors_become_consistent_responses(exc, status, code, message):
    got_status, body, headers = call(failing(exc))
    assert got_status == status
    assert body == {"message": message, "code": code}
    assert headers["Content-Type"] == "application/json"


def test_a_successful_handler_is_untouched():
    @api_handler
    def handler(event, context):
        return {"statusCode": 200, "headers": {}, "body": "{}"}

    assert handler({}, None) == {"statusCode": 200, "headers": {}, "body": "{}"}


@pytest.mark.negative
@pytest.mark.security
def test_unexpected_errors_return_a_generic_500_without_internal_details():
    status, body, _ = call(failing(RuntimeError("password=hunter2 at db-internal.corp")))
    assert status == 500
    assert body["code"] == "internal_error"
    assert body["message"] == "Internal server error"
    assert body["request_id"] == "req-1"
    assert "hunter2" not in json.dumps(body)


@pytest.mark.negative
def test_unexpected_errors_are_logged_with_the_traceback_and_request_id(capsys):
    from common import logs

    logs.reset()
    try:
        call(failing(RuntimeError("boom")), request_id="req-77")
        lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    finally:
        logs.reset()
    [entry] = [line for line in lines if line["level"] == "ERROR"]
    assert entry["request_id"] == "req-77"
    assert "RuntimeError: boom" in entry["exception"]


def test_a_missing_context_still_produces_a_response():
    response = failing(RuntimeError("x"))({}, None)
    assert response["statusCode"] == 500
    assert "request_id" not in json.loads(response["body"])
