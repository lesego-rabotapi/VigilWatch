import boto3
import json

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('uptime_checks')

def lambda_handler(event, context):
    response = table.scan(Limit=10)
    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps(response["Items"])
    }