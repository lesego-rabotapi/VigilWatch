import requests
import time
import boto3
from datetime import datetime

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("vigilwatch-uptime")

URLS = [
    "https://example.com",
    "https://google.com"
]

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