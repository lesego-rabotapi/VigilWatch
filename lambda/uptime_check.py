import json
import os
from datetime import datetime
from urllib import request as urllib_request, error as urllib_error

import boto3

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "uptime_checks")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def _get_clients():
    dynamodb = boto3.resource("dynamodb")
    cloudwatch = boto3.client("cloudwatch")
    sns = boto3.client("sns")
    table = dynamodb.Table(TABLE_NAME)
    return table, cloudwatch, sns


def lambda_handler(event, context):
    """
    Periodic uptime check Lambda.
    Always returns CORS headers, even on error.
    """
    try:
        table, cloudwatch, sns = _get_clients()

        response = table.scan()
        items = response.get("Items", [])

        results = []

        for item in items:
            if not item.get("enabled", True):
                continue

            # Safely handle items that don't have an 'endpoint' key
            endpoint = item.get("endpoint")
            if not endpoint:
                # Skip malformed items instead of crashing the whole Lambda
                print(f"Skipping item without endpoint: {json.dumps(item)}")
                continue

            method = item.get("method", "GET")
            expected_status = int(item.get("expected_status", 200))

            try:
                # For now, only support GET (UI only does GET checks)
                if method != "GET":
                    raise ValueError(f"Unsupported method: {method}")

                req = urllib_request.Request(endpoint, method="GET")
                with urllib_request.urlopen(req, timeout=5) as resp:
                    actual_status = resp.getcode()
                success = actual_status == expected_status

            except urllib_error.HTTPError as e:
                actual_status = e.code
                success = actual_status == expected_status

            except Exception:
                success = False
                actual_status = "timeout"

            cloudwatch.put_metric_data(
                Namespace="VigilWatch",
                MetricData=[
                    {
                        "MetricName": "EndpointUp",
                        "Dimensions": [
                            {"Name": "Endpoint", "Value": endpoint},
                        ],
                        "Value": 1 if success else 0,
                        "Unit": "Count",
                    }
                ],
            )

            if not success and SNS_TOPIC_ARN:
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject="Uptime check failed",
                    Message=json.dumps(
                        {
                            "endpoint": endpoint,
                            "expected_status": expected_status,
                            "actual_status": actual_status,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        indent=2,
                    ),
                )

            results.append(
                {
                    "endpoint": endpoint,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                    "success": success,
                }
            )

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(
                {
                    "status": "completed",
                    "checked": len(results),
                    "results": results,
                }
            ),
        }

    except Exception as e:
        # Ensure CORS headers even on unexpected failure
        print("Error in uptime_check:", repr(e))
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"message": "Internal server error"}),
        }