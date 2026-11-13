"""The emulated AWS backend the integration layer runs against: moto in server mode.

Unlike `mock_aws`, which patches boto3 inside the test process, the moto server is a separate HTTP
service: every boto3 call crosses a real socket, as it does against DynamoDB, SNS and SQS in AWS.
"""

import os

import pytest


class BackendUnavailable(Exception):
    """The emulated backend cannot be started here."""


def require(problem: BackendUnavailable | None, ci: bool) -> None:
    """Skip on a laptop where the backend is absent; fail in CI, where a skip proves nothing."""
    if problem is None:
        return
    if ci:
        pytest.fail(f"the integration backend is required in CI: {problem}", pytrace=False)
    pytest.skip(f"integration backend unavailable: {problem}")


def running_in_ci() -> bool:
    return os.environ.get("CI", "").lower() == "true"


def start_server():
    """Start a moto server on a free local port. Returns (server, endpoint_url)."""
    try:
        from moto.server import ThreadedMotoServer
    except ImportError as exc:  # moto[server] (Flask) not installed
        raise BackendUnavailable(f"install requirements-dev.txt ({exc})") from exc
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    return server, f"http://{host}:{port}"
