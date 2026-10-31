"""A request ID must flow from the Lambda context into every log line a handler writes."""

import json
from types import SimpleNamespace

import pytest

import register_endpoint
from common import logs

pytestmark = pytest.mark.req("VW-021")


@pytest.fixture(autouse=True)
def fresh_logging():
    logs.reset()
    yield
    logs.reset()


def test_handler_logs_carry_the_lambda_request_id(tables, monkeypatch, capsys):
    monkeypatch.setattr(register_endpoint, "resolver", lambda host: ["93.184.215.14"])

    def boom(*_args, **_kwargs):
        raise RuntimeError("probe crashed")

    monkeypatch.setattr(register_endpoint, "apply_result", boom)
    monkeypatch.setattr(register_endpoint, "probe", lambda url, **_: None)
    event = {"version": "2.0", "body": json.dumps({"url": "https://example.com/"})}

    response = register_endpoint.lambda_handler(event, SimpleNamespace(aws_request_id="req-abc-1"))

    assert response["statusCode"] == 201
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    failure = [line for line in lines if "first check failed" in line["message"]]
    assert failure, lines
    assert failure[0]["request_id"] == "req-abc-1"
    assert "RuntimeError: probe crashed" in failure[0]["exception"]
    assert failure[0]["endpoint_url"] == "https://example.com/"
