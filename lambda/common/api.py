"""The error boundary shared by the HTTP handlers.

    @api_handler
    def lambda_handler(event, context): ...

Known errors become responses with a stable code. Anything else is logged with its traceback and
returned as a generic 500 that carries the request ID but none of the internals, so a failure is
diagnosable by the owner and tells an attacker nothing.
"""

import functools

from common import logs
from common.endpoints_repo import EndpointLimitReached
from common.errors import AppError
from common.http import BadRequest, error
from common.urlguard import UnresolvableHost, UnsafeURL

logger = logs.get_logger(__name__)


def _translate(exc: Exception) -> tuple[int, str, str] | None:
    """(status, code, message) for an error the caller can act on, else None."""
    if isinstance(exc, AppError):
        return exc.status, exc.code, exc.message
    if isinstance(exc, UnresolvableHost):  # before UnsafeURL, its parent class
        return 400, "host_unresolvable", "Could not resolve that host name"
    if isinstance(exc, UnsafeURL):
        return 400, "unsafe_url", str(exc)
    if isinstance(exc, BadRequest):
        return 400, "bad_request", str(exc)
    if isinstance(exc, EndpointLimitReached):
        return 429, "limit_reached", f"Monitoring limit reached ({exc.args[0]} endpoints)"
    return None


def api_handler(func):
    @functools.wraps(func)
    def wrapper(event, context):
        logs.bind(context)
        try:
            return func(event, context)
        except Exception as exc:
            translated = _translate(exc)
            if translated:
                status, code, message = translated
                return error(status, message, code)
            logger.exception("unhandled error")
            extra = {}
            request_id = getattr(context, "aws_request_id", None)
            if request_id:
                extra["request_id"] = request_id
            return error(500, "Internal server error", "internal_error", **extra)

    return wrapper
