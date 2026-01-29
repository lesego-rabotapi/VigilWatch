resource "aws_apigatewayv2_api" "vigilwatch" {
  name          = "vigilwatch-http"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["https://your-frontend.example.com", "http://localhost:3000"]
    allow_headers = ["Content-Type", "Authorization"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "register" {
  api_id                 = aws_apigatewayv2_api.vigilwatch.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.register.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "register" {
  api_id    = aws_apigatewayv2_api.vigilwatch.id
  route_key = "POST /register"
  target    = "integrations/${aws_apigatewayv2_integration.register.id}"
}

resource "aws_apigatewayv2_integration" "checks" {
  api_id                 = aws_apigatewayv2_api.vigilwatch.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.checks.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "checks" {
  api_id    = aws_apigatewayv2_api.vigilwatch.id
  route_key = "GET /checks"
  target    = "integrations/${aws_apigatewayv2_integration.checks.id}"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.vigilwatch.id
  name        = "prod"
  auto_deploy = true
}

# Permissions for API Gateway to invoke Lambda
resource "aws_lambda_permission" "apigw_register" {
  statement_id  = "AllowInvokeRegister"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.register.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.vigilwatch.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_checks" {
  statement_id  = "AllowInvokeChecks"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.checks.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.vigilwatch.execution_arn}/*/*"
}