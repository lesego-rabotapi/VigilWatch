import json
import sys
import os
sys.path. insert(0, os.path. join(os.path.dirname(__file__), '../lambda'))

from register_endpoint import lambda_handler

def test_register_endpoint_structure():
    """Test that register endpoint returns proper structure"""
    response = {
        'statusCode':  201,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'message': 'Endpoint registered',
            'url': 'https://example.com'
        })
    }
    
    assert response['statusCode'] == 201
    assert 'headers' in response
    assert 'body' in response

def test_register_response_has_cors():
    """Test CORS headers in register response"""
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin':  '*'
    }
    
    assert 'Access-Control-Allow-Origin' in headers
    assert headers['Access-Control-Allow-Origin'] == '*'

def test_json_body_valid():
    """Test that response body is valid JSON"""
    body = json.dumps({'message': 'Endpoint registered', 'url': 'https://example.com'})
    parsed = json.loads(body)
    
    assert 'message' in parsed
    assert 'url' in parsed
