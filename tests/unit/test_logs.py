import json
import logging
from types import SimpleNamespace

import pytest

from common import logs

pytestmark = pytest.mark.req("VW-021")


@pytest.fixture(autouse=True)
def clean_logging():
    logs.reset()
    yield
    logs.reset()


def _lines(capsys):
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_log_lines_are_single_json_objects_with_the_core_fields(capsys):
    logs.get_logger("vigilwatch.test").info("check recorded")
    [line] = _lines(capsys)
    assert line["level"] == "INFO"
    assert line["message"] == "check recorded"
    assert line["logger"] == "vigilwatch.test"
    assert line["time"].endswith("Z") and "T" in line["time"]


def test_extra_fields_are_merged_but_cannot_overwrite_core_fields(capsys):
    logs.get_logger("t").warning(
        "slow", extra={"fields": {"endpoint_id": "abc", "latency_ms": 1500, "level": "FAKE"}}
    )
    [line] = _lines(capsys)
    assert line["endpoint_id"] == "abc" and line["latency_ms"] == 1500
    assert line["level"] == "WARNING"


def test_exceptions_are_included_as_text_on_the_same_line(capsys):
    log = logs.get_logger("t")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log.exception("failed")
    [line] = _lines(capsys)
    assert line["level"] == "ERROR"
    assert "RuntimeError: boom" in line["exception"]


def test_request_id_is_bound_from_the_lambda_context(capsys):
    logs.bind(SimpleNamespace(aws_request_id="req-123"))
    logs.get_logger("t").info("one")
    logs.get_logger("t").info("two")
    assert [line["request_id"] for line in _lines(capsys)] == ["req-123", "req-123"]


def test_no_request_id_field_without_a_context(capsys):
    logs.bind(None)
    logs.get_logger("t").info("local")
    [line] = _lines(capsys)
    assert "request_id" not in line


def test_configuration_is_idempotent(capsys):
    for _ in range(3):
        logs.get_logger("t")
    logs.get_logger("t").info("once")
    assert len(_lines(capsys)) == 1


def test_log_level_comes_from_the_environment(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    logs.reset()
    log = logs.get_logger("t")
    log.info("hidden")
    log.warning("shown")
    assert [line["message"] for line in _lines(capsys)] == ["shown"]


def test_inside_lambda_the_runtime_handler_is_reformatted_not_duplicated(monkeypatch, capsys):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "vigilwatch-test")
    root = logging.getLogger()
    runtime_handler = logging.StreamHandler()
    saved = root.handlers[:]
    root.handlers = [runtime_handler]
    try:
        logs.reset()
        logs.get_logger("t")
        assert isinstance(runtime_handler.formatter, logs.JsonFormatter)
        assert root.handlers == [runtime_handler], "must not add a second handler in Lambda"
    finally:
        root.handlers = saved
