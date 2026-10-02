from datetime import UTC, datetime, timedelta

import boto3
import pytest

from common.repo import EndpointLimitReached, Repo, iso

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def repo(tables):
    return Repo()


def _raw_history(endpoint_id):
    table = boto3.resource("dynamodb").Table("vigilwatch-history")
    return table.query(
        KeyConditionExpression="endpoint_id = :e",
        ExpressionAttributeValues={":e": endpoint_id},
    )["Items"]


def test_iso_is_utc_z_suffixed():
    assert iso(NOW) == "2026-10-02T12:00:00Z"


def test_put_endpoint_creates_once_and_is_idempotent(repo):
    item, created = repo.put_endpoint("abc", "https://example.com/", NOW)
    assert created is True
    assert item["url"] == "https://example.com/"
    assert item["enabled"] is True
    assert item["expected_status"] == 200
    assert item["status"] == "UNKNOWN"
    assert item["consecutive_failures"] == 0

    again, created_again = repo.put_endpoint("abc", "https://example.com/", NOW)
    assert created_again is False
    assert again["created_at"] == item["created_at"]
    assert repo.count_endpoints() == 1


def test_endpoint_cap_is_enforced_but_existing_endpoint_still_returns(repo):
    for i in range(3):
        repo.put_endpoint(f"id{i}", f"https://e{i}.example.com/", NOW, max_endpoints=3)
    with pytest.raises(EndpointLimitReached):
        repo.put_endpoint("id9", "https://new.example.com/", NOW, max_endpoints=3)
    _, created = repo.put_endpoint("id0", "https://e0.example.com/", NOW, max_endpoints=3)
    assert created is False


def test_get_endpoint_missing_returns_none(repo):
    assert repo.get_endpoint("nope") is None


def test_list_enabled_endpoints_skips_disabled(repo):
    repo.put_endpoint("a", "https://a.example.com/", NOW)
    repo.put_endpoint("b", "https://b.example.com/", NOW)
    repo.update_endpoint("b", enabled=False)
    assert [e["endpoint_id"] for e in repo.list_enabled_endpoints()] == ["a"]


def test_record_check_writes_raw_row_with_ttl_and_daily_rollup(repo):
    repo.record_check("a", NOW, "UP", 200, 123.7)
    repo.record_check("a", NOW + timedelta(minutes=5), "DOWN", None, None)

    rows = {r["sk"]: r for r in _raw_history("a")}
    raw = rows["C#2026-10-02T12:00:00Z"]
    assert raw["status"] == "UP"
    assert raw["status_code"] == 200
    assert raw["latency_ms"] == 124
    assert raw["expires_at"] == int((NOW + timedelta(hours=48)).timestamp())

    down = rows["C#2026-10-02T12:05:00Z"]
    assert "status_code" not in down and "latency_ms" not in down

    day = rows["D#2026-10-02"]
    assert day["total"] == 2 and day["up"] == 1
    # Expiry slides forward with the latest write to that day.
    assert day["expires_at"] == int((NOW + timedelta(minutes=5, days=31)).timestamp())


def test_degraded_counts_as_up_in_rollup(repo):
    repo.record_check("a", NOW, "DEGRADED", 200, 2500)
    day = {r["sk"]: r for r in _raw_history("a")}["D#2026-10-02"]
    assert day["up"] == 1


def test_uptime_30d_aggregates_daily_rollups_inside_window(repo):
    # 40 days ago (outside window): all down, must be ignored.
    for _ in range(4):
        repo.record_check("a", NOW - timedelta(days=40), "DOWN", 500, 10)
    # Inside the window: 3 up, 1 down -> 75 %.
    repo.record_check("a", NOW - timedelta(days=29), "UP", 200, 10)
    repo.record_check("a", NOW - timedelta(days=3), "UP", 200, 10)
    repo.record_check("a", NOW - timedelta(days=3), "DOWN", 500, 10)
    repo.record_check("a", NOW, "UP", 200, 10)
    assert repo.uptime_30d("a", NOW) == pytest.approx(75.0)


def test_uptime_30d_is_none_without_data(repo):
    assert repo.uptime_30d("a", NOW) is None


def test_recent_checks_newest_first_and_limited(repo):
    for i in range(25):
        repo.record_check("a", NOW + timedelta(minutes=5 * i), "UP", 200, i)
    recent = repo.recent_checks("a", limit=20)
    assert len(recent) == 20
    assert recent[0]["latency_ms"] == 24
    assert recent[-1]["latency_ms"] == 5
    assert recent[0]["checked_at"] == iso(NOW + timedelta(minutes=120))


def test_incident_open_and_close(repo):
    start = NOW
    end = NOW + timedelta(minutes=15)
    repo.open_incident("a", start)
    [open_inc] = repo.incidents("a")
    assert open_inc == {
        "start_time": iso(start),
        "end_time": None,
        "resolved": False,
        "duration_s": None,
    }

    repo.close_incident("a", iso(start), end)
    [closed] = repo.incidents("a")
    assert closed["resolved"] is True
    assert closed["end_time"] == iso(end)
    assert closed["duration_s"] == 900


def test_update_endpoint_sets_and_removes_fields(repo):
    repo.put_endpoint("a", "https://a.example.com/", NOW)
    repo.update_endpoint("a", status="DOWN", consecutive_failures=2, open_incident_start=iso(NOW))
    repo.update_endpoint("a", open_incident_start=None)
    item = repo.get_endpoint("a")
    assert item["status"] == "DOWN"
    assert item["consecutive_failures"] == 2
    assert "open_incident_start" not in item


def test_values_come_back_as_plain_python_not_decimal(repo):
    repo.put_endpoint("a", "https://a.example.com/", NOW)
    repo.record_check("a", NOW, "UP", 200, 12.0)
    assert type(repo.get_endpoint("a")["expected_status"]) is int
    assert type(repo.recent_checks("a")[0]["latency_ms"]) is int
