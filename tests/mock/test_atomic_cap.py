"""The endpoint cap must hold under concurrent registrations, not just one at a time.

DynamoDB executes every request atomically, including a transaction and its conditions. moto does
not lock, so two threads could both pass one condition inside the mock, which says nothing about the
real service. The `serialised_requests` fixture therefore runs each DynamoDB request to completion
before the next, as the service does, while leaving the gaps *between* requests open. Those gaps are
where check-then-write races live, so the old code still fails here and the new code must not.
"""

import threading
import time
from datetime import UTC, datetime

import boto3
import pytest
from botocore.client import BaseClient

from common.endpoints_repo import EndpointLimitReached, EndpointRepository

pytestmark = pytest.mark.req("VW-003", "VW-023")

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
COUNTER_KEY = {"endpoint_id": "_system#count"}


def test_checking_the_counter_exists_costs_an_eventually_consistent_read(tables, monkeypatch):
    """It runs on every registration against 2 to 5 units; the conditional create covers a race."""
    repo = new_repo()
    reads = []
    real = repo.table.get_item

    def spy(**kwargs):
        reads.append(kwargs.get("ConsistentRead", False))
        return real(**kwargs)

    monkeypatch.setattr(repo.table, "get_item", spy)
    repo._ensure_counter()
    assert reads[0] is False


def new_repo():
    """A repository on its own boto3 resource, as a separate Lambda container would have."""
    return EndpointRepository(boto3.resource("dynamodb").Table("vigilwatch-endpoints"))


def register_concurrently(entries, cap):
    """Start every (endpoint_id, url) registration together; return (created, over_cap, errors)."""
    outcomes, errors = [], []
    gate = threading.Barrier(len(entries))

    def worker(endpoint_id, url):
        try:
            gate.wait(timeout=5)
            _, created = new_repo().put(endpoint_id, url, NOW, max_endpoints=cap)
            outcomes.append("created" if created else "existing")
        except EndpointLimitReached:
            outcomes.append("over_cap")
        except Exception as exc:  # surfaced by the assertions below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=entry) for entry in entries]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return outcomes.count("created"), outcomes.count("over_cap"), errors


@pytest.fixture
def serialised_requests(monkeypatch):
    """Make each DynamoDB request atomic, like the real service (see the module docstring)."""
    lock = threading.RLock()
    real = BaseClient._make_api_call

    def locked(self, operation_name, api_params):
        if self.meta.service_model.service_name != "dynamodb":
            return real(self, operation_name, api_params)
        with lock:
            return real(self, operation_name, api_params)

    monkeypatch.setattr(BaseClient, "_make_api_call", locked)


@pytest.fixture
def slow_count(monkeypatch, serialised_requests):
    """Widen the race window: every reader of the count sees it before anyone else writes."""
    real = EndpointRepository.count

    def slow(self):
        value = real(self)
        time.sleep(0.15)
        return value

    monkeypatch.setattr(EndpointRepository, "count", slow)


@pytest.mark.negative
def test_concurrent_registrations_never_exceed_the_cap(tables, slow_count):
    entries = [(f"id{i:02d}", f"https://h{i}.example.com/") for i in range(10)]
    created, over_cap, errors = register_concurrently(entries, cap=3)
    assert errors == []
    assert (created, over_cap) == (3, 7)
    assert new_repo().count() == 3


def test_concurrent_registrations_of_the_same_url_create_it_once(tables, slow_count):
    # the same URL has the same id, so there is one creator and everyone else sees it exists
    entries = [("same", "https://same.example.com/")] * 6
    created, over_cap, errors = register_concurrently(entries, cap=5)
    assert errors == [] and over_cap == 0
    assert created == 1
    assert new_repo().count() == 1


def test_the_cap_is_a_counter_item_updated_with_each_registration(tables):
    repo = new_repo()
    repo.put("a", "https://a.example.com/", NOW, max_endpoints=5)
    repo.put("b", "https://b.example.com/", NOW, max_endpoints=5)
    counter = repo.table.get_item(Key=COUNTER_KEY)["Item"]
    assert int(counter["n"]) == 2


def test_the_counter_is_invisible_to_counting_and_listing(tables):
    repo = new_repo()
    repo.put("a", "https://a.example.com/", NOW)
    assert repo.count() == 1
    assert [e["endpoint_id"] for e in repo.list_enabled()] == ["a"]


@pytest.mark.negative
def test_existing_deployments_without_a_counter_are_still_capped(tables):
    repo = new_repo()
    for name in ("a", "b"):  # written the old way: items but no counter
        repo.table.put_item(Item={"endpoint_id": name, "url": f"https://{name}.example.com/"})
    assert repo.table.get_item(Key=COUNTER_KEY).get("Item") is None
    with pytest.raises(EndpointLimitReached):
        repo.put("c", "https://c.example.com/", NOW, max_endpoints=2)


def test_removing_an_endpoint_by_hand_frees_a_slot(tables):
    """The runbook says to delete an item to stop monitoring it; the counter must follow."""
    repo = new_repo()
    repo.put("a", "https://a.example.com/", NOW, max_endpoints=2)
    repo.put("b", "https://b.example.com/", NOW, max_endpoints=2)
    with pytest.raises(EndpointLimitReached):
        repo.put("c", "https://c.example.com/", NOW, max_endpoints=2)

    repo.table.delete_item(Key={"endpoint_id": "b"})
    item, created = repo.put("c", "https://c.example.com/", NOW, max_endpoints=2)
    assert created and item["url"] == "https://c.example.com/"
    assert repo.count() == 2


@pytest.mark.negative
def test_a_full_table_stays_full_after_the_counter_is_reconciled(tables):
    repo = new_repo()
    repo.put("a", "https://a.example.com/", NOW, max_endpoints=1)
    for _ in range(3):
        with pytest.raises(EndpointLimitReached):
            repo.put("b", "https://b.example.com/", NOW, max_endpoints=1)
    assert repo.count() == 1


def test_registering_an_existing_endpoint_at_the_cap_does_not_touch_the_counter(tables):
    repo = new_repo()
    repo.put("a", "https://a.example.com/", NOW, max_endpoints=1)
    _, created = repo.put("a", "https://a.example.com/", NOW, max_endpoints=1)
    assert created is False
    assert int(repo.table.get_item(Key=COUNTER_KEY)["Item"]["n"]) == 1
