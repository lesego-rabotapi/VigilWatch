import json
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("vigilwatch-endpoints")

def api_handler(event, context):
    params = event.get("queryStringParameters") or {}
    endpoint = params.get("endpoint")

    if "body" not in event:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing request body"})
        }

    if not endpoint:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "endpoint query parameter required"})
        }

    response = table.query(
        KeyConditionExpression=Key("endpoint").eq(endpoint)
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response["Items"])
    }

