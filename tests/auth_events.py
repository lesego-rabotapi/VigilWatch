"""Signed-in API events for handler tests: API Gateway's JWT authorizer puts the verified token's
claims under requestContext.authorizer.jwt.claims."""

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def signed_in(event: dict, sub=OWNER) -> dict:
    """The event as it reaches the function after the authorizer accepted a token for `sub`."""
    context = event.setdefault("requestContext", {})
    context["authorizer"] = {"jwt": {"claims": {"sub": sub}, "scopes": None}}
    return event
