# req: VW-001 VW-007 VW-011 VW-016 VW-026
# The HTTP API in front of the two request-handling functions. The AWS provider is mocked.

mock_provider "aws" {
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:af-south-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      execution_arn = "arn:aws:execute-api:af-south-1:123456789012:abc123"
      api_endpoint  = "https://abc123.execute-api.af-south-1.amazonaws.com"
    }
  }
  mock_resource "aws_apigatewayv2_stage" {
    defaults = { invoke_url = "https://abc123.execute-api.af-south-1.amazonaws.com/" }
  }
}

variables {
  name_prefix = "vigilwatch-dev"
  function_invoke_arns = {
    register_endpoint = "arn:aws:apigateway:af-south-1:lambda:path/2015-03-31/functions/arn:aws:lambda:af-south-1:123456789012:function:register/invocations"
    get_checks        = "arn:aws:apigateway:af-south-1:lambda:path/2015-03-31/functions/arn:aws:lambda:af-south-1:123456789012:function:checks/invocations"
  }
  function_names  = { register_endpoint = "vigilwatch-dev-register-endpoint", get_checks = "vigilwatch-dev-get-checks" }
  allowed_origins = ["https://d111111abcdef8.cloudfront.net", "http://localhost:3000"]
  jwt_issuer      = "https://cognito-idp.af-south-1.amazonaws.com/af-south-1_MOCK"
  jwt_audiences   = ["dashboardclient", "smokeclient"]
}

run "exactly_two_routes_reach_the_right_functions" {
  command = apply

  assert {
    condition     = toset(keys(aws_apigatewayv2_route.route)) == toset(["POST /register", "GET /checks"])
    error_message = "the API must expose exactly POST /register and GET /checks"
  }
  assert {
    condition     = aws_apigatewayv2_route.route["GET /checks"].target == "integrations/${aws_apigatewayv2_integration.api["get_checks"].id}"
    error_message = "GET /checks must reach the get_checks function"
  }
  assert {
    condition     = alltrue([for i in aws_apigatewayv2_integration.api : i.payload_format_version == "2.0" && i.integration_type == "AWS_PROXY"])
    error_message = "integrations must be proxy integrations with the v2 payload"
  }
  assert {
    condition     = aws_apigatewayv2_api.http.name == "vigilwatch-dev-http"
    error_message = "the API name must carry the environment prefix"
  }
}

run "invocation_is_limited_to_this_api" {
  command = apply

  assert {
    condition     = alltrue([for p in aws_lambda_permission.api_invoke : p.principal == "apigateway.amazonaws.com" && startswith(p.source_arn, aws_apigatewayv2_api.http.execution_arn)])
    error_message = "only this API may invoke the functions"
  }
}

run "cors_names_the_dashboard_and_never_everyone" {
  command = apply

  assert {
    condition     = contains(aws_apigatewayv2_api.http.cors_configuration[0].allow_origins, "https://d111111abcdef8.cloudfront.net")
    error_message = "CORS must allow the dashboard origin"
  }
  assert {
    condition     = !contains(aws_apigatewayv2_api.http.cors_configuration[0].allow_origins, "*")
    error_message = "CORS must not allow every origin"
  }
}

run "the_public_api_is_throttled_and_cheap" {
  command = apply

  assert {
    condition     = aws_apigatewayv2_stage.default.default_route_settings[0].throttling_rate_limit == 5 && aws_apigatewayv2_stage.default.default_route_settings[0].throttling_burst_limit == 10
    error_message = "the default throttle is 5 requests per second with a burst of 10"
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.default_route_settings[0].detailed_metrics_enabled == false
    error_message = "detailed (per-route) metrics are billed as custom metrics"
  }
  assert {
    condition     = aws_cloudwatch_log_group.api_access.retention_in_days <= 14 && aws_cloudwatch_log_group.api_access.name == "/aws/apigateway/vigilwatch-dev-http"
    error_message = "access logs must be short-lived and carry the environment prefix"
  }
}

run "outputs_expose_the_base_url_without_a_trailing_slash" {
  command = apply

  assert {
    condition     = output.base_url == "https://abc123.execute-api.af-south-1.amazonaws.com"
    error_message = "the base URL must have no trailing slash"
  }
}

run "rejects_a_wildcard_origin" {
  command = plan
  variables {
    allowed_origins = ["*"]
  }
  expect_failures = [var.allowed_origins]
}

run "rejects_an_unbounded_throttle" {
  command = plan
  variables {
    throttle_rate = 1000
  }
  expect_failures = [var.throttle_rate]
}

run "exports_the_access_log_group_for_the_saved_queries" {
  command = apply

  assert {
    condition     = output.access_log_group == "/aws/apigateway/vigilwatch-dev-http"
    error_message = "the monitoring module reads this environment's access log group by name"
  }
}

run "every_access_log_line_is_json_even_when_a_value_is_missing" {
  command = apply

  # Values are written unescaped: free text such as an integration error message could hold a
  # quote and break the line, so only fixed-form values are logged (errors are in function logs).
  assert {
    condition = !anytrue([for v in ["ErrorMessage", "error.message", "integration.error", "authorizer.error"] :
    strcontains(aws_apigatewayv2_stage.default.access_log_settings[0].format, v)])
    error_message = "no free-text value in the access log"
  }
  assert {
    condition = (strcontains(aws_apigatewayv2_stage.default.access_log_settings[0].format, "$context.error.responseType")
    && strcontains(aws_apigatewayv2_stage.default.access_log_settings[0].format, "$context.integration.status"))
    error_message = "a 5xx that never reached a function (throttled, no permission, timed out) still says why"
  }

  # API Gateway writes "-" for a value it does not have: only a quoted placeholder stays valid JSON.
  assert {
    condition     = can(jsondecode(replace(aws_apigatewayv2_stage.default.access_log_settings[0].format, "/\\$context\\.[A-Za-z.]+/", "-")))
    error_message = "every $context value must be inside quotes"
  }
}

run "no_route_is_unauthenticated" {
  command = apply

  assert {
    condition     = alltrue([for r in aws_apigatewayv2_route.route : r.authorization_type == "JWT" && r.authorizer_id == aws_apigatewayv2_authorizer.jwt.id])
    error_message = "every route must require a token checked by the JWT authorizer (ADR 0007)"
  }
}

run "tokens_are_checked_against_this_environments_pool_and_clients" {
  command = apply

  assert {
    condition     = aws_apigatewayv2_authorizer.jwt.authorizer_type == "JWT"
    error_message = "the built-in JWT authorizer, not a Lambda authorizer"
  }
  assert {
    condition     = aws_apigatewayv2_authorizer.jwt.jwt_configuration[0].issuer == "https://cognito-idp.af-south-1.amazonaws.com/af-south-1_MOCK"
    error_message = "only this environment's user pool issues valid tokens"
  }
  assert {
    condition     = toset(aws_apigatewayv2_authorizer.jwt.jwt_configuration[0].audience) == toset(["dashboardclient", "smokeclient"])
    error_message = "only tokens for this environment's own clients"
  }
  assert {
    condition     = toset(aws_apigatewayv2_authorizer.jwt.identity_sources) == toset(["$request.header.Authorization"])
    error_message = "the token comes in the Authorization header"
  }
}

run "the_browser_may_send_the_authorization_header" {
  command = apply

  assert {
    condition     = contains(aws_apigatewayv2_api.http.cors_configuration[0].allow_headers, "authorization")
    error_message = "CORS must allow the Authorization header, or the browser never sends the token"
  }
}
