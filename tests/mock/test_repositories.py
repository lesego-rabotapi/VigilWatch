"""Each repository works on its own, given only a table: the point of splitting the old Repo."""

from datetime import UTC, datetime, timedelta

import boto3
import pytest

from common.endpoints_repo import EndpointLimitReached, EndpointRepository
from common.history_repo import HistoryRepository
from common.incidents_repo import IncidentRepository
from common.repo import Repo

pytestmark = pytest.mark.req("VW-001", "VW-003", "VW-007", "VW-008", "VW-009")

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def endpoints_table(tables):
    return boto3.resource("dynamodb").Table("vigilwatch-endpoints")


@pytest.fixture
def history_table(tables):
    return boto3.resource("dynamodb").Table("vigilwatch-history")


def test_endpoint_repository_creates_reads_lists_and_updates(endpoints_table):
    repo = EndpointRepository(endpoints_table)
    item, created = repo.put("a", "https://a.example.com/", NOW)
    assert created and item["status"] == "UNKNOWN"
    assert repo.get("a")["url"] == "https://a.example.com/"
    assert repo.count() == 1
    repo.update("a", status="UP", enabled=False)
    assert repo.get("a")["status"] == "UP"
    assert repo.list_enabled() == []


def test_endpoint_repository_enforces_the_cap_but_returns_existing(endpoints_table):
    repo = EndpointRepository(endpoints_table)
    repo.put("a", "https://a.example.com/", NOW, max_endpoints=1)
    with pytest.raises(EndpointLimitReached):
        repo.put("b", "https://b.example.com/", NOW, max_endpoints=1)
    assert repo.put("a", "https://a.example.com/", NOW, max_endpoints=1)[1] is False


def test_history_repository_records_checks_and_summarises_them(history_table):
    repo = HistoryRepository(history_table)
    repo.record("a", NOW, "UP", 200, 120.0)
    repo.record("a", NOW + timedelta(minutes=5), "DOWN", 503, 40.0)
    assert [c["status"] for c in repo.recent("a")] == ["DOWN", "UP"]
    assert repo.uptime_30d("a", NOW) == pytest.approx(50.0)
    assert repo.uptime_30d("nobody", NOW) is None


def test_incident_repository_opens_closes_and_lists(history_table):
    repo = IncidentRepository(history_table)
    start = repo.open("a", NOW)
    repo.close("a", start, NOW + timedelta(minutes=10))
    [incident] = repo.list("a")
    assert incident["resolved"] is True and incident["duration_s"] == 600


def test_checks_and_incidents_share_a_table_without_mixing(history_table):
    checks, incidents = HistoryRepository(history_table), IncidentRepository(history_table)
    checks.record("a", NOW, "UP", 200, 10.0)
    incidents.open("a", NOW)
    assert len(checks.recent("a")) == 1
    assert len(incidents.list("a")) == 1


def test_the_repo_facade_delegates_to_the_three_repositories(tables):
    repo = Repo()
    repo.put_endpoint("a", "https://a.example.com/", NOW)
    repo.record_check("a", NOW, "UP", 200, 50.0)
    repo.open_incident("a", NOW)
    assert repo.get_endpoint("a")["url"] == "https://a.example.com/"
    assert len(repo.recent_checks("a")) == 1
    assert len(repo.incidents("a")) == 1
