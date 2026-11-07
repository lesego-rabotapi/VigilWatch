"""The local stack has no Cognito: it signs every request in as one local user, so the real
handlers, which require a caller, work unchanged."""

import pytest

import local_api
from common.auth import caller

pytestmark = pytest.mark.req("VW-026")


def test_every_local_request_is_signed_in_as_the_local_user():
    event = local_api.api_event("GET", "/checks", "url=https%3A%2F%2Fexample.com", {}, None)
    assert caller(event) == local_api.LOCAL_USER
    assert event["queryStringParameters"] == {"url": "https://example.com"}
    assert event["requestContext"]["http"] == {"method": "GET", "path": "/checks"}


def test_the_local_preflight_allows_the_authorization_header():
    """The e2e CORS test runs against the local stack too, and a browser sends the token."""
    import threading
    import urllib.request
    from http.server import HTTPServer

    server = HTTPServer(("127.0.0.1", 0), local_api.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/register", method="OPTIONS"
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            allowed = response.headers["Access-Control-Allow-Headers"].lower()
    finally:
        server.shutdown()
        server.server_close()
    assert "authorization" in allowed and "content-type" in allowed
