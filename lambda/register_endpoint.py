import json
from datetime import datetime

import boto3

TABLE_NAME = "uptime_checks"

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    table = _get_table()

    if "body" in event:
        body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
    else:
        body = event

    url = body.get("endpoint") or body.get("url")
    if not url:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"message": "Missing 'endpoint' or 'url' field"}),
        }

    endpoint_id = body.get("endpoint_id") or datetime.utcnow().strftime("%Y%m%d%H%M%S%f")

    table.put_item(
        Item={
            "endpoint_id": endpoint_id,
            "timestamp": datetime.utcnow().isoformat(),
            "endpoint": url,
            "method": body.get("method", "GET"),
            "expected_status": body.get("expected_status", 200),
            "enabled": True,
        }
    )

    return {
        "statusCode": 201,
        "headers": CORS_HEADERS,
        "body": json.dumps(
            {
                "message": "Endpoint registered successfully",
                "endpoint_id": endpoint_id,
                "url": url,
            }
        ),
    }

    return {
    "statusCode": 200,
    "headers": {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "OPTIONS,POST"
    },
    "body": json.dumps({
        "message": "Monitoring started successfully"
    })
}
