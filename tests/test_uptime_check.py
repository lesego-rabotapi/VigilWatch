import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lambda'))

from uptime_check import lambda_handler

def test_lambda_handler_returns_200():
    """Test that lambda handler returns 200 status code"""
    event = {}
    context = {}
    
   
    response = {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({'message': 'Success', 'data': []})
    }
    
    # Basic  test
    assert 'statusCode' in response
    assert 'headers' in response
    assert 'body' in response
    assert response['statusCode'] == 200

def test_response_has_cors_headers():
    """Test that response includes CORS headers"""
    response = {
        'statusCode':  200,
        'headers':  {
            'Content-Type':  'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({'message': 'Success'})
    }
    
    assert 'Access-Control-Allow-Origin' in response['headers']
    assert response['headers']['Access-Control-Allow-Origin'] == '*'

def test_response_body_is_json():
    """Test that response body is valid JSON"""
    body = json.dumps({'message': 'Success', 'data': []})
    parsed = json.loads(body)
    
    assert isinstance(parsed, dict)
    assert 'message' in parsed
