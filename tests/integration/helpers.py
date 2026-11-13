"""Small helpers shared by the integration tests."""

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime

from common.repo import Repo
from common.urlguard import endpoint_id, normalize

OWNER = "local-user"  # the subject the local HTTP adapter signs every request in as


def add_endpoint(url: str, expected_status: int = 200) -> str:
    """Register a URL straight in the table, as register_endpoint would, without its first check."""
    normalized = normalize(url)
    key = endpoint_id(OWNER, normalized)
    Repo().put_endpoint(key, normalized, datetime.now(UTC), expected_status, owner=OWNER)
    return key


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(  # noqa: S310
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())
