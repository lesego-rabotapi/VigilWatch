import json
import boto3
import uuid
from datetime import datetime

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("uptime_checks")

def lambda_handler(event, context):
    body = json.loads(event["body"])

    endpoint_id = str(uuid.uuid4())

    table.put_item(
        Item={
            "endpoint_id": endpoint_id,
            "timestamp": datetime.utcnow().isoformat(),
            "url": body["url"],
            "method": body.get("method", "GET"),
            "expected_status": body.get("expected_status", 200),
            "enabled": True
        }
    )

    return {
        "statusCode": 201,
        "body": json.dumps({
            "message": "Endpoint registered",
            "endpoint_id": endpoint_id
        })
    }
