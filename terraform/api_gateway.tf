resource "aws_api_gateway_rest_api" "uptime_api" {
  name = "uptime-api"
}

resource "aws_api_gateway_resource" "endpoints" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  parent_id   = aws_api_gateway_rest_api.uptime_api.root_resource_id
  path_part   = "endpoints"
}

resource "aws_api_gateway_resource" "uptime_resource" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
  parent_id   = aws_api_gateway_rest_api.uptime_api.root_resource_id
  path_part   = "check"
}

resource "aws_api_gateway_deployment" "uptime_api" {
  rest_api_id = aws_api_gateway_rest_api.uptime_api.id

  depends_on = [
    aws_api_gateway_integration.post_endpoint_lambda
  ]
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.uptime_api.id
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  stage_name    = "prod"
}


resource "aws_api_gateway_method" "post_endpoint" {
  rest_api_id   = aws_api_gateway_rest_api.uptime_api.id
  resource_id   = aws_api_gateway_resource.endpoints.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "post_endpoint_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.uptime_api.id
  resource_id             = aws_api_gateway_resource.endpoints.id
  http_method             = aws_api_gateway_method.post_endpoint.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.register_endpoint.invoke_arn
}

resource "aws_lambda_permission" "api_gateway_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.uptime_checker.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.uptime_api.execution_arn}/*/*"
}

#resource "aws_api_gateway_method_response" "post_response" {
#  rest_api_id = aws_api_gateway_rest_api.uptime_api.id
#  resource_id = aws_api_gateway_resource.uptime_resource.id
#  http_method = aws_api_gateway_method.post_endpoint.http_method
#  status_code = "200"
#}

resource "aws_lambda_permission" "allow_apigw_register_endpoint" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.register_endpoint.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_api_gateway_rest_api.uptime_api.execution_arn}/*/POST/endpoints"
}

resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.register_endpoint.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_api_gateway_rest_api.uptime_api.execution_arn}/*/*"
}

