import json
import os
from datetime import datetime
from urllib import request as urllib_request, error as urllib_error

import boto3 

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def lambda_handler(event, context):
    """
    Extremely simple uptime check:
    - Reads ?url=... from queryStringParameters
    - Performs a single GET with 5s timeout
    - Returns status code and success flag
    - No DynamoDB, no SNS, no Decimals
    """
    try:
        qs = event.get("queryStringParameters") or {}
        url = qs.get("url")
        if not url:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"message": "Missing 'url' query parameter"}),
            }

        expected_status = 200
        started_at = datetime.utcnow().isoformat()

        try:
            req = urllib_request.Request(url, method="GET")
            with urllib_request.urlopen(req, timeout=5) as resp:
                actual_status = resp.getcode()
                success = actual_status == expected_status
        except urllib_error.HTTPError as e:
            actual_status = e.code
            success = actual_status == expected_status
        except Exception as e:
            actual_status = "error"
            success = False

        body = {
            "status": "completed",
            "checked": 1,
            "results": [
                {
                    "endpoint": url,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                    "success": success,
                    "timestamp": started_at,
                }
            ],
        }

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(body),
        }

    except Exception as e:
        # Last-resort error
        print("Error in simple uptime_check:", repr(e))
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"message": "Internal server error"}),
        }