import requests
import boto3
from boto3.dynamodb.conditions import Key
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cloudwatch = boto3.client("cloudwatch")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

URLS = ["https://example.com", "https://api.example.com"]  # Add your URLs

def get_registered_endpoints():
    registry = dynamodb.Table(os.environ.get("REGISTRY_TABLE_NAME", "vigilwatch-registered-endpoints"))
    response = registry.scan()
    return [item["endpoint"] for item in response["Items"]]

def uptime_check(event, context):
    for url in URLS:
        start = time.time()
        try:
            response = requests.get(url, timeout=5)
            latency = int((time.time() - start) * 1000)
            status = "UP" if response.status_code == 200 else "DOWN"
            status_value = 1 if response.status_code == 200 else 0
        except Exception as e:
            logger.error(f"Error checking {url}: {str(e)}")
            latency = None
            status = "DOWN"
            status_value = 0

        response = table.query(
            KeyConditionExpression=Key("endpoint").eq(url)
        )

        cloudwatch.put_metric_data(
            Namespace="VigilWatch",
            MetricData=[
                {
                    "MetricName": "EndpointStatus",
                    "Dimensions": [
                        {"Name": "Endpoint", "Value": url}
                    ],
                    "Timestamp": datetime.utcnow(),
                    "Value": status_value,
                    "Unit": "Count"
                }
            ]
        )

    return {"message": "Uptime check complete"}