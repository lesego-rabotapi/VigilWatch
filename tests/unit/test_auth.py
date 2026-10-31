"""The caller is the token's subject, as API Gateway's JWT authorizer verified it. Anything else
is refused: the functions never trust a request that reached them without a signed-in caller."""

import pytest

from common.auth import caller
from common.errors import UnauthorizedError
from tests.auth_events import OWNER, signed_in

pytestmark = [pytest.mark.req("VW-026"), pytest.mark.security]


def test_the_caller_is_the_tokens_subject():
    assert caller(signed_in({}, OWNER)) == OWNER


@pytest.mark.boundary
@pytest.mark.parametrize("length, accepted", [(1, True), (128, True), (129, False)])
def test_the_subject_length_is_bounded(length, accepted):
    sub = "a" * length
    if accepted:
        assert caller(signed_in({}, sub)) == sub
    else:
        with pytest.raises(UnauthorizedError):
            caller(signed_in({}, sub))


@pytest.mark.negative
@pytest.mark.parametrize(
    "event",
    [
        {},
        {"requestContext": {}},
        {"requestContext": {"authorizer": None}},
        {"requestContext": {"authorizer": {"jwt": {}}}},
        {"requestContext": {"authorizer": {"jwt": {"claims": {}}}}},
    ],
    ids=["no-context", "no-authorizer", "null-authorizer", "no-claims", "no-subject"],
)
def test_a_request_without_a_signed_in_caller_is_refused(event):
    with pytest.raises(UnauthorizedError):
        caller(event)


@pytest.mark.negative
@pytest.mark.parametrize(
    "sub",
    ["", "   ", 123, None, ["a"], "a#b", "a\nb", "a/b", "../x"],
    ids=["empty", "blank", "int", "none", "list", "hash", "newline", "slash", "dots"],
)
def test_a_subject_that_is_not_a_plain_id_is_refused(sub):
    """It becomes part of keys (the endpoint id, the per-user counter): only letters, digits
    and hyphens, as Cognito's UUIDs are."""
    with pytest.raises(UnauthorizedError):
        caller(signed_in({}, sub))
