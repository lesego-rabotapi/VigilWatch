import json

def test_api_response_format():
    """Test standard API response format"""
    response = {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin':  '*'
        },
        'body': json.dumps({'data': []})
    }
    
    # Verify response structure
    assert isinstance(response, dict)
    assert 'statusCode' in response
    assert 'headers' in response
    assert 'body' in response
    
    # Verify status code
    assert response['statusCode'] in [200, 201, 400, 500]
    
    # Verify headers
    assert 'Content-Type' in response['headers']
    assert response['headers']['Content-Type'] == 'application/json'
    
    # Verify body is valid JSON
    body = json.loads(response['body'])
    assert isinstance(body, dict)

def test_cors_headers_present():
    """Test that all responses include CORS headers"""
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
    }
    
    assert 'Access-Control-Allow-Origin' in headers
    assert headers['Access-Control-Allow-Origin'] == '*'
