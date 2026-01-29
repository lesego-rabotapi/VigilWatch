import json
from decimal import Decimal
from typing import Any, Dict

def to_json_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, list):
        return [to_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
    return obj

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Api-Key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}

def register(event, context):
    try:
        result: Dict[str, Any] = {"ok": True, "userId": Decimal("1")}
        body = json.dumps(to_json_safe(result))
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": body}
    except Exception as e:
        # Return CORS headers on errors too
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }

def checks(event, context):
    try:
        items = [{"repo": "lesego-rabotapi/VigilWatch", "score": Decimal("0.95")}]
        body = json.dumps(to_json_safe(items))
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": body}
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }