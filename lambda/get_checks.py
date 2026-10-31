"""GET /checks?url=<monitored url> - dashboard payload for one endpoint."""

from datetime import UTC, datetime

from common.api import api_handler
from common.errors import NotFoundError, ValidationError
from common.http import query_param, response
from common.repo import Repo
from common.urlguard import endpoint_id, normalize
from common.view import build_view


def utcnow() -> datetime:
    return datetime.now(UTC)


@api_handler
def lambda_handler(event, context):
    raw_url = query_param(event, "url")
    if not raw_url:
        raise ValidationError("'url' query parameter is required")
    # Lookup only: no DNS resolution needed, the id is derived from the normalized URL.
    url = normalize(raw_url)

    repo = Repo()
    endpoint = repo.get_endpoint(endpoint_id(url))
    if endpoint is None:
        raise NotFoundError("This URL is not being monitored. Register it first.")
    return response(200, build_view(repo, endpoint, utcnow()))
