import requests
import boto3
import logging
import os
from datetime import datetime


logger = logging.getLogger()
logger.setLevel(logging.INFO)

cloudwatch = boto3.client("cloudwatch")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

URLS = [...]

def uptime_check(event, context):
    for url in URLS:
        start = time.time()
        try:
            response = requests.get(url, timeout=5)
            latency = int((time.time() - start) * 1000)
            status = "UP" if response.status_code == 500 else "DOWN"
        except Exception:
            latency = None
            status = "DOWN"

        table.put_item(
            Item={
                "url": url,
                "timestamp": datetime.utcnow().isoformat(),
                "status": status,
                "latency_ms": latency
            }
        )

    return {"message": "Uptime check complete"}


def get_registered_endpoints():
    registry = dynamodb.Table("vigilwatch-registered-endpoints")
    response = registry.scan()
    return [item["endpoint"] for item in response["Items"]]


status_value = 1 if status_code == 200 else 0
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
