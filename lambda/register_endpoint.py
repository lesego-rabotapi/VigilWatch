import json
import boto3
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('uptime_checks')

def lambda_handler(event, context):
    try:
        body = json.loads(event. get('body', '{}')) if isinstance(event.get('body'), str) else event
        url = body.get('endpoint') or body.get('url', 'https://example.com')
        
        table.put_item(Item={
            'endpoint_id': str(uuid.uuid4()),
            'timestamp': datetime.utcnow().isoformat(),
            'url': url,
            'status':  'REGISTERED'
        })
        
        return {
            'statusCode': 201,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'message': 'Endpoint registered', 'url': url})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'error': str(e)})
        }
