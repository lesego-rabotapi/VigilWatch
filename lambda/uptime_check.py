import json
import os
from datetime import datetime

import boto3
import requests

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "uptime_checks")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")


def _get_clients():
    """Create AWS clients/resources lazily to avoid side effects at import time."""
    dynamodb = boto3.resource("dynamodb")
    cloudwatch = boto3.client("cloudwatch")
    sns = boto3.client("sns")
    table = dynamodb.Table(TABLE_NAME)
    return table, cloudwatch, sns


def lambda_handler(event, context):
    """
    Periodic uptime check Lambda.
    """
    table, cloudwatch, sns = _get_clients()

    response = table.scan()
    items = response.get("Items", [])

    results = []

    for item in items:
        if not item.get("enabled", True):
            continue

        endpoint = item["endpoint"]
        method = item.get("method", "GET")
        expected_status = int(item.get("expected_status", 200))

        try:
            r = requests.request(method, endpoint, timeout=5)
            success = r.status_code == expected_status
            actual_status = r.status_code
        except Exception:
            success = False
            r = None
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
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(
            {
                "status": "completed",
                "checked": len(results),
                "results": results,
            }
        ),
    }