"""Concurrent registrations: a busy table or a stale read is never reported as a full cap."""

from datetime import UTC, datetime

import boto3
import pytest
from botocore.exceptions import ClientError

from common.endpoints_repo import EndpointLimitReached, EndpointRepository, OwnerLimitReached
from common.errors import Busy
from tests.auth_events import OWNER

pytestmark = [pytest.mark.req("VW-026"), pytest.mark.negative]

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def cancelled(*codes):
    return ClientError(
        {
            "Error": {"Code": "TransactionCanceledException", "Message": "x"},
            "CancellationReasons": [{"Code": c or "None"} for c in codes],
        },
        "TransactWriteItems",
    )


@pytest.fixture
def repo(tables):
    return EndpointRepository(boto3.resource("dynamodb").Table("vigilwatch-endpoints"))


def put(repo, url="https://a.example/", **kwargs):
    return repo.put("e" * 16, url, NOW, owner=OWNER, max_per_owner=5, **kwargs)


def test_a_transaction_conflict_is_retried_not_reported_as_a_full_cap(repo, monkeypatch):
    real, calls = repo._create, []

    def create(*args):
        calls.append(1)
        if len(calls) == 1:
            raise cancelled(None, "TransactionConflict", None)
        return real(*args)

    monkeypatch.setattr(repo, "_create", create)
    item, created = put(repo)
    assert created and len(calls) == 2


def test_a_conflict_that_persists_is_a_busy_error_never_a_limit(repo, monkeypatch):
    def create(*args):
        raise cancelled(None, "TransactionConflict", "TransactionConflict")

    monkeypatch.setattr(repo, "_create", create)
    with pytest.raises(Busy) as caught:
        put(repo)
    assert not isinstance(caught.value, EndpointLimitReached)
    assert caught.value.status == 503


def test_a_stale_read_after_a_duplicate_put_still_returns_the_existing_endpoint(repo, monkeypatch):
    real_get = repo.get
    first = real_get("e" * 16)
    assert first is None
    repo.table.put_item(Item={"endpoint_id": "e" * 16, "url": "https://a.example/"})

    def stale_get(endpoint_id, consistent=False):
        return real_get(endpoint_id) if consistent else None

    def create(*args):
        raise cancelled("ConditionalCheckFailed", None, None)

    monkeypatch.setattr(repo, "get", stale_get)
    monkeypatch.setattr(repo, "_create", create)
    item, created = put(repo)
    assert not created and item["url"] == "https://a.example/"


@pytest.mark.parametrize(
    "reasons, expected",
    [
        ((None, "ConditionalCheckFailed", None), EndpointLimitReached),
        ((None, None, "ConditionalCheckFailed"), OwnerLimitReached),
    ],
    ids=["global", "owner"],
)
def test_each_cap_is_blamed_only_when_its_own_check_failed(repo, monkeypatch, reasons, expected):
    monkeypatch.setattr(repo, "_create", lambda *a: (_ for _ in ()).throw(cancelled(*reasons)))
    monkeypatch.setattr(repo, "_reconcile", lambda *a: False)
    with pytest.raises(expected) as caught:
        put(repo)
    assert type(caught.value) is expected
