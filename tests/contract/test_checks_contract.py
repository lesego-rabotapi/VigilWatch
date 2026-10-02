"""Contract between the API Lambdas and the dashboard (frontend/app.js)."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

import get_checks
import register_endpoint
from common.checker import Settings, apply_result
from common.repo import Repo
from common.status import CheckResult
from common.urlguard import endpoint_id

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((Path(__file__).parent / "checks_response.schema.json").read_text())
T0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
URL = "https://example.com/"


def get_event(params):
    return {
        "version": "2.0",
        "routeKey": "GET /checks",
        "rawPath": "/checks",
        "requestContext": {"http": {"method": "GET", "path": "/checks"}},
        "queryStringParameters": params,
    }


def call_get(params):
    r = get_checks.lambda_handler(get_event(params), None)
    return r["statusCode"], json.loads(r["body"])


@pytest.fixture
def seeded(tables, monkeypatch):
    """One endpoint with a history: up, slow, two failures (incident), recovery."""
    monkeypatch.setattr(get_checks, "utcnow", lambda: T0 + timedelta(minutes=30))
    repo = Repo()
    endpoint, _ = repo.put_endpoint(endpoint_id(URL), URL, T0)
    script = [
        CheckResult(200, 100.0),
        CheckResult(200, 1500.0),
        CheckResult(503, 30.0),
        CheckResult(None, None, "timed out"),
        CheckResult(200, 90.0),
    ]
    for i, result in enumerate(script):
        apply_result(
            repo.get_endpoint(endpoint["endpoint_id"]),
            result,
            repo,
            lambda *_: True,
            T0 + timedelta(minutes=5 * i),
            Settings(),
        )
    return repo


def test_schema_itself_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_get_checks_matches_contract(seeded):
    status, body = call_get({"url": URL})
    assert status == 200
    jsonschema.validate(body, SCHEMA)

    assert body["status"] == "UP"
    assert body["uptime_30d"] == pytest.approx(60.0)  # 3 of 5 (DEGRADED counts as up)
    assert body["latest_latency_ms"] == 90
    assert [p["status"] for p in body["recent_latencies"]] == [
        "UP",
        "DEGRADED",
        "DOWN",
        "DOWN",
        "UP",
    ]
    assert body["recent_latencies"][3]["ms"] is None
    [incident] = body["incidents"]
    assert incident == {
        "start_time": "2026-10-02T12:15:00Z",
        "end_time": "2026-10-02T12:20:00Z",
        "duration": "5m 0s",
        "duration_s": 300,
        "resolved": True,
    }
    assert body["last_alert_sent"] == "2026-10-02T12:20:00Z"


def test_lookup_normalizes_the_url(seeded):
    assert call_get({"url": "HTTPS://EXAMPLE.COM"})[0] == 200


def test_register_response_matches_the_same_contract(tables, monkeypatch):
    monkeypatch.setattr(register_endpoint, "resolver", lambda host: ["93.184.215.14"])
    monkeypatch.setattr(register_endpoint, "probe", lambda url, **_: CheckResult(200, 50.0))
    r = register_endpoint.lambda_handler(
        {"version": "2.0", "body": json.dumps({"url": URL}), "isBase64Encoded": False}, None
    )
    jsonschema.validate(json.loads(r["body"]), SCHEMA)


@pytest.mark.parametrize("params", [None, {}, {"url": ""}])
def test_missing_url_is_400(tables, params):
    status, body = call_get(params)
    assert status == 400
    assert body["message"]


def test_invalid_url_is_400(tables):
    assert call_get({"url": "ftp://example.com/"})[0] == 400


def test_unknown_endpoint_is_404(tables):
    status, body = call_get({"url": "https://never-registered.example.com/"})
    assert status == 404
    assert body["message"]


def test_no_cors_headers_from_function(seeded):
    r = get_checks.lambda_handler(get_event({"url": URL}), None)
    assert not any(h.lower().startswith("access-control-") for h in r["headers"])


def test_frontend_reads_only_fields_in_the_contract():
    """Every data.<field> the dashboard reads must exist in the schema."""
    source = (ROOT / "frontend").glob("*.js")
    used = set()
    for path in source:
        used |= set(re.findall(r"\bdata\.([a-z_0-9]+)", path.read_text(encoding="utf-8")))
    assert used, "expected the frontend to read fields from the payload"
    assert used <= set(SCHEMA["properties"]), used - set(SCHEMA["properties"])
