"""Structured JSON logging with the Lambda request ID on every line.

One JSON object per line is searchable with CloudWatch Logs Insights. The request ID ties together
all lines of one invocation. Only the standard library is used.

Inside Lambda the runtime already installs a root handler, which is reformatted rather than
duplicated. Elsewhere (local runs, tests) a stdout handler is added.
"""

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_CORE_FIELDS = ("level", "message", "logger", "time", "request_id", "exception")
_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {}
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update({k: v for k, v in extra.items() if k not in _CORE_FIELDS})
        entry["level"] = record.levelname
        entry["message"] = record.getMessage()
        entry["logger"] = record.name
        entry["time"] = (
            datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        )
        request_id = _request_id.get()
        if request_id:
            entry["request_id"] = request_id
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is at emit time, so output capture keeps working."""

    def __init__(self):
        super().__init__()

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _value):
        pass


def configure() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        for handler in root.handlers:
            handler.setFormatter(JsonFormatter())
    else:
        handler = _StdoutHandler()
        handler.setFormatter(JsonFormatter())
        handler.set_name("vigilwatch-json")
        root.addHandler(handler)
    _configured = True


def reset() -> None:
    """Undo configure() (tests only)."""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == "vigilwatch-json":
            root.removeHandler(handler)
    _request_id.set(None)
    _configured = False


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(name)


def bind(context) -> None:
    """Start an invocation: make sure logging is configured and tag lines with the request ID."""
    configure()
    _request_id.set(getattr(context, "aws_request_id", None))
