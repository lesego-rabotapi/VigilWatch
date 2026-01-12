import time
import requests
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('uptime_checks')

URLS = ["https://example.com"]

def lambda_handler(event, context):
    for url in URLS:
        start = time.time()
        try:
            response = requests.get(url, timeout=5)
            status = response.status_code
        except Exception:
            status = 500

        latency = time.time() - start

        table.put_item(
            Item={
                "target_url": url,
                "timestamp": datetime.utcnow().isoformat(),
                "status_code": status,
                "latency": latency
            }
        )