"""GET /checks?url=<monitored url> - dashboard payload for one endpoint."""

from datetime import UTC, datetime

from common.http import error, query_param, response
from common.repo import Repo
from common.urlguard import UnsafeURL, endpoint_id, normalize
from common.view import build_view


def utcnow() -> datetime:
    return datetime.now(UTC)


def lambda_handler(event, context):
    raw_url = query_param(event, "url")
    if not raw_url:
        return error(400, "'url' query parameter is required")
    try:
        # Lookup only: no DNS resolution needed, the id is derived from the normalized URL.
        url = normalize(raw_url)
    except UnsafeURL as exc:
        return error(400, str(exc))

    repo = Repo()
    endpoint = repo.get_endpoint(endpoint_id(url))
    if endpoint is None:
        return error(404, "This URL is not being monitored. Register it first.")
    return response(200, build_view(repo, endpoint, utcnow()))
