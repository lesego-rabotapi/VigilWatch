"""Who is calling: the subject of the token API Gateway's JWT authorizer verified.

The authorizer refuses a request without a valid token before any function runs. This is the
second line: a request that reaches a function without a usable subject is refused too, so a
misconfigured route cannot open the data to anyone.
"""

import re

from common.errors import UnauthorizedError

# It becomes part of keys (the endpoint id, the per-user counter), so only what Cognito's UUID
# subjects contain: letters, digits and hyphens.
_SUBJECT = re.compile(r"[A-Za-z0-9-]{1,128}")


def caller(event: dict) -> str:
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get(
        "claims"
    ) or {}
    sub = claims.get("sub")
    if not isinstance(sub, str) or not _SUBJECT.fullmatch(sub):
        raise UnauthorizedError("Sign in to use VigilWatch")
    return sub
