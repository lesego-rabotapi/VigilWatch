"""Endpoints belong to the user who registered them (IDOR checks), and each user has a cap."""

import json
from datetime import UTC, datetime

import boto3
import pytest

import get_checks
import register_endpoint
from common.endpoints_repo import EndpointRepository, owner_counter_id
from common.status import CheckResult
from common.urlguard import endpoint_id
from tests.auth_events import OTHER, OWNER, signed_in

pytestmark = [pytest.mark.req("VW-026"), pytest.mark.security]

URL = "https://example.com/"
THIRD = "33333333-3333-4333-8333-333333333333"


@pytest.fixture(autouse=True)
def env(tables, monkeypatch):
    """No network: every host resolves to a public address and every probe answers 200."""
    monkeypatch.setattr(register_endpoint, "resolver", lambda host: ["93.184.215.14"])
    monkeypatch.setattr(
        register_endpoint, "probe", lambda url, **_: CheckResult(status_code=200, latency_ms=50.0)
    )
    monkeypatch.setattr(
        register_endpoint, "utcnow", lambda: datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    )
    monkeypatch.delenv("MAX_ENDPOINTS", raising=False)
    monkeypatch.delenv("MAX_ENDPOINTS_PER_USER", raising=False)


def register(url=URL, sub=OWNER, sign_in=True):
    event = {"version": "2.0", "body": json.dumps({"url": url})}
    response = register_endpoint.lambda_handler(signed_in(event, sub) if sign_in else event, None)
    return response["statusCode"], json.loads(response["body"])


def checks(url=URL, sub=OWNER, sign_in=True):
    event = {"version": "2.0", "queryStringParameters": {"url": url}}
    response = get_checks.lambda_handler(signed_in(event, sub) if sign_in else event, None)
    return response["statusCode"], json.loads(response["body"])


def endpoints_table():
    return boto3.resource("dynamodb").Table("vigilwatch-endpoints")


@pytest.mark.negative
@pytest.mark.parametrize("call", [register, checks], ids=["register", "checks"])
def test_a_request_without_a_signed_in_caller_is_refused(call):
    status, body = call(sign_in=False)
    assert status == 401 and body["code"] == "unauthorized"


def test_an_endpoint_records_its_owner(tables):
    status, body = register()
    assert status == 201
    item = endpoints_table().get_item(Key={"endpoint_id": body["endpoint_id"]})["Item"]
    assert item["owner_sub"] == OWNER
    assert body["endpoint_id"] == endpoint_id(OWNER, URL)
    assert "owner_sub" not in body, "the payload carries no user ids"


@pytest.mark.negative
def test_another_users_url_is_not_found_exactly_like_an_unmonitored_one():
    register(sub=OWNER)
    theirs = checks(sub=OTHER)
    nobodys = checks(url="https://nobody.example/", sub=OTHER)
    assert theirs[0] == nobodys[0] == 404
    assert theirs[1] == nobodys[1], "the answer must not tell the two apart"


def test_two_users_monitoring_one_url_have_two_endpoints():
    _, mine = register(sub=OWNER)
    status, theirs = register(sub=OTHER)
    assert status == 201, "not 'already monitored': it is not monitored by them"
    assert mine["endpoint_id"] != theirs["endpoint_id"]
    assert checks(sub=OWNER)[1]["endpoint_id"] == mine["endpoint_id"]
    assert checks(sub=OTHER)[1]["endpoint_id"] == theirs["endpoint_id"]


@pytest.mark.negative
def test_an_item_owned_by_someone_else_is_never_returned():
    """Defence in depth: even if an id ever collided, the owner on the item is checked."""
    register(sub=OWNER)
    endpoints_table().update_item(
        Key={"endpoint_id": endpoint_id(OWNER, URL)},
        UpdateExpression="SET owner_sub = :o",
        ExpressionAttributeValues={":o": OTHER},
    )
    assert checks(sub=OWNER)[0] == 404


@pytest.mark.boundary
def test_each_user_has_their_own_cap(monkeypatch):
    monkeypatch.setenv("MAX_ENDPOINTS_PER_USER", "2")
    assert register("https://a.example/")[0] == 201
    assert register("https://b.example/")[0] == 201
    status, body = register("https://c.example/")
    assert status == 429 and body["code"] == "limit_reached"
    assert "your" in body["message"].lower(), "say it is the user's own limit"
    assert register("https://c.example/", sub=OTHER)[0] == 201, "others are not affected"


@pytest.mark.boundary
def test_the_global_cap_still_bounds_everyone_together(monkeypatch):
    monkeypatch.setenv("MAX_ENDPOINTS", "2")
    assert register("https://a.example/", sub=OWNER)[0] == 201
    assert register("https://b.example/", sub=OTHER)[0] == 201
    status, body = register("https://c.example/", sub=THIRD)
    assert status == 429 and "your" not in body["message"].lower()


def test_each_users_counter_is_updated_with_each_registration():
    register("https://a.example/")
    register("https://b.example/")
    counter = endpoints_table().get_item(Key={"endpoint_id": owner_counter_id(OWNER)})["Item"]
    assert counter["n"] == 2
    assert EndpointRepository(endpoints_table()).count(owner=OWNER) == 2


def test_a_repair_after_a_restore_fixes_every_users_counter():
    register("https://a.example/", sub=OWNER)
    register("https://b.example/", sub=OTHER)
    table = endpoints_table()
    table.put_item(Item={"endpoint_id": owner_counter_id(OWNER), "n": 0})  # stale
    EndpointRepository(table).repair_counter()
    assert table.get_item(Key={"endpoint_id": owner_counter_id(OWNER)})["Item"]["n"] == 1
    assert table.get_item(Key={"endpoint_id": owner_counter_id(OTHER)})["Item"]["n"] == 1


def test_a_users_counter_that_drifted_high_is_repaired_on_refusal(monkeypatch):
    """Like the global counter: an endpoint deleted by hand frees a slot again."""
    monkeypatch.setenv("MAX_ENDPOINTS_PER_USER", "1")
    endpoints_table().put_item(Item={"endpoint_id": owner_counter_id(OWNER), "n": 1})
    assert register("https://a.example/")[0] == 201


def test_a_repair_scans_the_table_once_however_many_users_there_are(monkeypatch):
    for index, sub in enumerate((OWNER, OTHER, THIRD)):
        register(f"https://{index}.example/", sub=sub)
    table = endpoints_table()
    repo = EndpointRepository(table)
    scans = []
    real_scan = table.scan
    monkeypatch.setattr(table, "scan", lambda **kw: scans.append(kw) or real_scan(**kw))
    repo.repair_counter()
    assert len(scans) <= 2, f"{len(scans)} scans for three users"
    for sub in (OWNER, OTHER, THIRD):
        assert table.get_item(Key={"endpoint_id": owner_counter_id(sub)})["Item"]["n"] == 1
