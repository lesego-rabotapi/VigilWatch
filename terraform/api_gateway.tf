resource "aws_api_gateway_rest_api" "uptime_api" {
  name        = "uptime-api"
  description = "VigilWatch Uptime Monitoring API"
}

# /checks
resource "aws_api_gateway_resource" "checks" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  parent_id   = aws_api_gateway_rest_api.uptime_api.root_resource_id
  path_part   = "checks"
}

resource "aws_api_gateway_method" "get_checks" {
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  resource_id   = aws_api_gateway_resource.checks.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_checks_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.uptime_api.id
  resource_id             = aws_api_gateway_resource.checks.id
  http_method             = aws_api_gateway_method.get_checks.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.uptime_check.invoke_arn
}

# CORS OPTIONS /checks
resource "aws_api_gateway_method" "options_checks" {
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  resource_id   = aws_api_gateway_resource.checks.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "options_checks" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  resource_id = aws_api_gateway_resource.checks.id
  http_method = aws_api_gateway_method.options_checks.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "options_checks_200" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  resource_id = aws_api_gateway_resource.checks.id
  http_method = aws_api_gateway_method.options_checks.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "options_checks" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  resource_id = aws_api_gateway_resource.checks.id
  http_method = aws_api_gateway_method.options_checks.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

# /register
resource "aws_api_gateway_resource" "register" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  parent_id   = aws_api_gateway_rest_api.uptime_api.root_resource_id
  path_part   = "register"
}

resource "aws_api_gateway_method" "post_register" {
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  resource_id   = aws_api_gateway_resource.register.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "post_register_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.uptime_api.id
  resource_id             = aws_api_gateway_resource.register.id
  http_method             = aws_api_gateway_method.post_register.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.register_endpoint.invoke_arn
}

# CORS OPTIONS /register
resource "aws_api_gateway_method" "options_register" {
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  resource_id   = aws_api_gateway_resource.register.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "options_register" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  resource_id = aws_api_gateway_resource.register.id
  http_method = aws_api_gateway_method.options_register.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "options_register_200" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  resource_id = aws_api_gateway_resource.register.id
  http_method = aws_api_gateway_method.options_register.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "options_register" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  resource_id = aws_api_gateway_resource.register.id
  http_method = aws_api_gateway_method.options_register.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

# Stage & deployment

resource "aws_api_gateway_deployment" "uptime_api" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id

  depends_on = [
    aws_api_gateway_integration.get_checks_lambda,
    aws_api_gateway_integration.post_register_lambda,
    aws_api_gateway_integration.options_checks,
    aws_api_gateway_integration.options_register,
  ]
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.uptime_api.id
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  stage_name    = "prod"
}

# Lambda permissions

resource "aws_lambda_permission" "api_gateway_uptime_checker" {
  statement_id_prefix = "AllowExecutionFromAPIGatewayChecks"
  action              = "lambda:InvokeFunction"
  function_name       = aws_lambda_function.uptime_check.function_name
  principal           = "apigateway.amazonaws.com"
  source_arn          = "${aws_api_gateway_rest_api.uptime_api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "api_gateway_register" {
  statement_id_prefix = "AllowExecutionFromAPIGatewayRegister"
  action              = "lambda:InvokeFunction"
  function_name       = aws_lambda_function.register_endpoint.function_name
  principal           = "apigateway.amazonaws.com"
  source_arn          = "${aws_api_gateway_rest_api.uptime_api.execution_arn}/*/*"
}