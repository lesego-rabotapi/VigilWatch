"""Helpers for API Gateway HTTP API (payload format 2.0) events.

CORS headers are deliberately absent: the HTTP API's cors_configuration is the
single source of truth (terraform/modules/api/main.tf).
"""

import base64
import json


class BadRequest(ValueError):
    pass


def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def error(status_code: int, message: str, code: str, **extra) -> dict:
    return response(status_code, {"message": message, "code": code, **extra})


def json_body(event: dict) -> dict:
    raw = event.get("body")
    if raw is None:
        raise BadRequest("request body is required")
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise BadRequest("request body is not valid base64 UTF-8") from exc
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as exc:  # deep nesting must not become a 5xx
        raise BadRequest("request body must be JSON") from exc
    if not isinstance(body, dict):
        raise BadRequest("request body must be a JSON object")
    return body


def query_param(event: dict, name: str) -> str | None:
    return (event.get("queryStringParameters") or {}).get(name)
