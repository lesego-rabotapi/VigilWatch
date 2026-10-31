"""docs/openapi.yaml is the source of truth for the API; the JSON Schema is exported from it."""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from openapi_spec_validator import validate

import get_checks
import register_endpoint
from export_schema import SCHEMA_PATH, build_schema, load_spec

pytestmark = pytest.mark.req("VW-011", "VW-012")

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "docs" / "openapi.yaml"


def test_spec_is_a_valid_openapi_31_document():
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.1")
    validate(spec)


def test_spec_documents_exactly_the_routes_the_api_serves():
    spec = load_spec()
    assert set(spec["paths"]) == {"/register", "/checks"}
    assert set(spec["paths"]["/register"]) == {"post"}
    assert set(spec["paths"]["/checks"]) == {"get"}


@pytest.mark.parametrize(
    "path, method, statuses",
    [
        ("/register", "post", {"200", "201", "400", "429", "500"}),
        ("/checks", "get", {"200", "400", "404", "500"}),
    ],
)
def test_every_status_the_handlers_can_return_is_documented(path, method, statuses):
    documented = set(load_spec()["paths"][path][method]["responses"])
    assert statuses <= documented, f"undocumented: {statuses - documented}"


def test_responses_use_the_shared_schemas():
    spec = load_spec()
    ok = spec["paths"]["/checks"]["get"]["responses"]["200"]["content"]["application/json"]
    assert ok["schema"] == {"$ref": "#/components/schemas/ChecksResponse"}
    for path, method in (("/register", "post"), ("/checks", "get")):
        bad = spec["paths"][path][method]["responses"]["400"]["content"]["application/json"]
        assert bad["schema"] == {"$ref": "#/components/schemas/Error"}


def test_committed_json_schema_is_exported_from_the_spec():
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == build_schema("ChecksResponse"), (
        "schema drifted from docs/openapi.yaml; run: python scripts/export_schema.py"
    )


def test_exported_schema_is_standalone_and_valid():
    schema = build_schema("ChecksResponse")
    jsonschema.Draft202012Validator.check_schema(schema)
    assert "#/components" not in json.dumps(schema), "unresolved component refs"
    assert schema["additionalProperties"] is False
    assert "uptime_30d" in schema["required"]


def test_register_request_schema_accepts_documented_bodies_and_rejects_bad_ones():
    schema = build_schema("RegisterRequest")
    validator = jsonschema.Draft202012Validator(schema)
    assert validator.is_valid({"url": "https://example.com"})
    assert validator.is_valid({"url": "https://example.com", "expected_status": 204})
    assert not validator.is_valid({})
    assert not validator.is_valid({"url": "https://example.com", "expected_status": 99})
    assert not validator.is_valid({"url": "https://example.com", "expected_status": 600})


def _error_schema_validator():
    return jsonschema.Draft202012Validator(build_schema("Error"))


def test_validation_errors_from_register_match_the_error_schema():
    response = register_endpoint.lambda_handler({"body": "{not json"}, None)
    assert response["statusCode"] == 400
    _error_schema_validator().validate(json.loads(response["body"]))


def test_missing_parameter_error_from_checks_matches_the_error_schema():
    response = get_checks.lambda_handler({"queryStringParameters": None}, None)
    assert response["statusCode"] == 400
    _error_schema_validator().validate(json.loads(response["body"]))


def test_not_found_error_from_checks_matches_the_error_schema(tables):
    event = {"queryStringParameters": {"url": "https://never-registered.example.org/"}}
    response = get_checks.lambda_handler(event, None)
    assert response["statusCode"] == 404
    _error_schema_validator().validate(json.loads(response["body"]))


def test_inconclusive_is_a_documented_status_in_the_payload_and_the_exported_schema():
    schemas = load_spec()["components"]["schemas"]
    assert "INCONCLUSIVE" in schemas["Status"]["enum"]
    assert "INCONCLUSIVE" in schemas["CheckStatus"]["enum"]
    payload = {
        "endpoint_id": "0123456789abcdef",
        "url": "https://example.com/",
        "status": "INCONCLUSIVE",
        "uptime_30d": None,
        "latest_latency_ms": None,
        "last_check": "2026-10-02T12:00:00Z",
        "last_alert_sent": None,
        "recent_latencies": [
            {"ms": None, "status": "INCONCLUSIVE", "checked_at": "2026-10-02T12:00:00Z"}
        ],
        "incidents": [],
    }
    jsonschema.validate(payload, build_schema("ChecksResponse"))
