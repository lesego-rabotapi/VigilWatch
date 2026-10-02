"""POST /register - start monitoring a URL.

Body: {"url": "https://example.com", "expected_status": 200}
201 with the dashboard payload (after an immediate first check) for a new URL,
200 for a URL that is already monitored.
"""

import logging
import os
from datetime import UTC, datetime

from common.checker import Settings, apply_result, make_publisher, probe
from common.http import BadRequest, error, json_body, response
from common.repo import EndpointLimitReached, Repo
from common.urlguard import UnresolvableHost, UnsafeURL, default_resolver, endpoint_id, validate
from common.view import build_view

logger = logging.getLogger()
logger.setLevel(logging.INFO)

resolver = default_resolver


def utcnow() -> datetime:
    return datetime.now(UTC)


def _expected_status(body: dict) -> int:
    value = body.get("expected_status", 200)
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise BadRequest("expected_status must be an integer HTTP status (100-599)")
    return value


def lambda_handler(event, context):
    try:
        body = json_body(event)
        raw_url = body.get("url") or body.get("endpoint")
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise BadRequest("'url' is required")
        expected_status = _expected_status(body)
        url = validate(raw_url, resolver=resolver)
    except UnresolvableHost:
        return error(400, "Could not resolve that host name")
    except (BadRequest, UnsafeURL) as exc:
        return error(400, str(exc))

    repo = Repo()
    now = utcnow()
    max_endpoints = int(os.environ.get("MAX_ENDPOINTS", "10"))
    try:
        endpoint, created = repo.put_endpoint(
            endpoint_id(url), url, now, expected_status=expected_status, max_endpoints=max_endpoints
        )
    except EndpointLimitReached:
        return error(429, f"Monitoring limit reached ({max_endpoints} endpoints)")

    if created:
        settings = Settings.from_env()
        try:
            result = probe(url, timeout=settings.timeout_s)
            apply_result(endpoint, result, repo, make_publisher(), now, settings)
            endpoint = repo.get_endpoint(endpoint["endpoint_id"])
        except Exception:
            # Registration succeeded; the scheduled checker will pick it up.
            logger.exception("first check failed for %s", url)

    return response(201 if created else 200, build_view(repo, endpoint, now))
