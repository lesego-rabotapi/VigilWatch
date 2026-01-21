# import json
# import boto3
# import uuid
# from datetime import datetime

# dynamodb = boto3.resource("dynamodb")
# table = dynamodb.Table("uptime_checks")

# def lambda_handler(event, context):
#     body = json.loads(event["body"])

#     endpoint_id = str(uuid.uuid4())

#     table.put_item(
#         Item={
#             "endpoint_id": endpoint_id,
#             "timestamp": datetime.utcnow().isoformat(),
#             "url": body["url"],
#             "method": body.get("method", "GET"),
#             "expected_status": body.get("expected_status", 200),
#             "enabled": True
#         }
#     )

#     return {
#         "statusCode": 201,
#         "body": json.dumps({
#             "message": "Endpoint registered",
#             "endpoint_id": endpoint_id
#         })
#     }
###################################################

import json
import os
import uuid
import boto3
from datetime import datetime
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("EVENT: %s", json.dumps(event))


dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "uptime_checks")

table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {})

    try:
        body = json.loads(event.get("body", "{}"))

        endpoint = body.get("endpoint")
        method = body.get("method", "GET")
        expected_status = body.get("expected_status", 200)

        if not endpoint:
            return _response(400, {"error": "endpoint is required"})

        endpoint_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        table.put_item(
            Item={
                "endpoint_id": endpoint_id,
                "timestamp": timestamp,
                "endpoint": endpoint,
                "method": method,
                "expected_status": expected_status,
                "enabled": True,
            }
        )

        return _response(
            201,
            {
                "message": "Endpoint registered",
                "endpoint_id": endpoint_id,
            },
        )

    except Exception as e:
        return _response(500, {"error": str(e)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body),
    }