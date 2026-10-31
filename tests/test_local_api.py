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
