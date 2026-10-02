# Infrastructure tests. The AWS provider is mocked: nothing is created and no
# credentials are needed. Run: terraform init -backend=false && terraform test

mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "123456789012" }
  }
}

variables {
  notification_email = ""
}

run "core_loop_is_wired" {
  command = apply

  assert {
    condition     = aws_cloudwatch_event_rule.schedule.schedule_expression == "rate(5 minutes)"
    error_message = "checker must run every 5 minutes by default"
  }
  assert {
    condition     = aws_cloudwatch_event_target.checker.arn == aws_lambda_function.fn["uptime_check"].arn
    error_message = "schedule must target the checker Lambda"
  }
  assert {
    condition     = aws_lambda_permission.events_invoke_checker.principal == "events.amazonaws.com"
    error_message = "EventBridge must be allowed to invoke the checker"
  }
  assert {
    condition     = aws_lambda_function_event_invoke_config.checker.destination_config[0].on_failure[0].destination == aws_sqs_queue.checker_dlq.arn
    error_message = "failed async checker runs must land in the DLQ"
  }
  assert {
    condition     = toset(keys(aws_apigatewayv2_route.route)) == toset(["POST /register", "GET /checks"])
    error_message = "API must expose exactly POST /register and GET /checks"
  }
  assert {
    condition     = aws_apigatewayv2_route.route["GET /checks"].target == "integrations/${aws_apigatewayv2_integration.api["get_checks"].id}"
    error_message = "GET /checks must hit the get_checks Lambda, not the checker"
  }
}

run "lambdas_are_consistent" {
  command = apply

  assert {
    condition     = alltrue([for f in aws_lambda_function.fn : f.runtime == "python3.12"])
    error_message = "all functions must run python3.12"
  }
  assert {
    condition     = alltrue([for f in aws_lambda_function.fn : contains(f.architectures, "arm64")])
    error_message = "arm64 is cheaper per GB-second"
  }
  assert {
    condition     = length(distinct([for f in aws_lambda_function.fn : f.role])) == 3
    error_message = "each function needs its own role"
  }
  assert {
    condition     = alltrue([for f in aws_lambda_function.fn : f.environment[0].variables["ENDPOINTS_TABLE"] == aws_dynamodb_table.endpoints.name])
    error_message = "functions must be told which table to use"
  }
  assert {
    condition     = alltrue([for lg in aws_cloudwatch_log_group.fn : lg.retention_in_days > 0 && lg.retention_in_days <= 14])
    error_message = "log retention must be set and short (cost)"
  }
}

run "least_privilege_iam" {
  command = apply

  assert {
    condition = alltrue(flatten([
      for p in aws_iam_role_policy.fn : [
        for s in jsondecode(p.policy).Statement : [
          !contains(flatten([s.Resource]), "*"),
          length([for a in flatten([s.Action]) : a if endswith(a, ":*") || a == "*"]) == 0,
        ]
      ]
    ]))
    error_message = "function policies must not use wildcard actions or resources"
  }
  assert {
    condition = length([
      for s in jsondecode(aws_iam_role_policy.fn["get_checks"].policy).Statement : s
      if length(setintersection(toset(flatten([s.Action])), toset(["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "sns:Publish"]))) > 0
    ]) == 0
    error_message = "the read API must be read-only"
  }
}

run "stays_in_free_tier" {
  command = apply

  assert {
    condition     = aws_dynamodb_table.endpoints.billing_mode == "PROVISIONED" && aws_dynamodb_table.history.billing_mode == "PROVISIONED"
    error_message = "on-demand DynamoDB is not covered by the always-free tier"
  }
  assert {
    condition = (aws_dynamodb_table.endpoints.read_capacity + aws_dynamodb_table.history.read_capacity <= 25
    && aws_dynamodb_table.endpoints.write_capacity + aws_dynamodb_table.history.write_capacity <= 25)
    error_message = "total provisioned capacity must stay within 25 RCU / 25 WCU"
  }
  assert {
    condition     = aws_dynamodb_table.history.ttl[0].enabled && aws_dynamodb_table.history.ttl[0].attribute_name == "expires_at"
    error_message = "history must expire via TTL (free deletes)"
  }
  assert {
    condition     = aws_cloudfront_distribution.frontend.price_class == "PriceClass_100"
    error_message = "use the cheapest CloudFront price class"
  }
  assert {
    condition     = length(aws_cloudwatch_metric_alarm.alarm) <= 10
    error_message = "only 10 alarms are free"
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.default_route_settings[0].throttling_rate_limit <= 10 && aws_apigatewayv2_stage.default.default_route_settings[0].throttling_burst_limit <= 20
    error_message = "the public API must be throttled"
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.default_route_settings[0].detailed_metrics_enabled == false
    error_message = "detailed (per-route) metrics are billed as custom metrics"
  }
}

run "frontend_is_private_and_https" {
  command = apply

  assert {
    condition = (aws_s3_bucket_public_access_block.frontend.block_public_acls
      && aws_s3_bucket_public_access_block.frontend.block_public_policy
      && aws_s3_bucket_public_access_block.frontend.ignore_public_acls
    && aws_s3_bucket_public_access_block.frontend.restrict_public_buckets)
    error_message = "frontend bucket must not be public"
  }
  assert {
    condition     = aws_cloudfront_distribution.frontend.origin[*].origin_access_control_id == [aws_cloudfront_origin_access_control.frontend.id]
    error_message = "CloudFront must reach S3 via OAC"
  }
  assert {
    condition     = aws_cloudfront_distribution.frontend.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "viewers must be redirected to HTTPS"
  }
  assert {
    condition     = jsondecode(aws_s3_bucket_policy.frontend.policy).Statement[0].Principal.Service == "cloudfront.amazonaws.com"
    error_message = "only CloudFront may read the bucket"
  }
  assert {
    condition     = strcontains(aws_s3_object.config.content, aws_apigatewayv2_stage.default.invoke_url)
    error_message = "config.js must point the dashboard at the deployed API"
  }
  assert {
    condition     = contains(keys(aws_s3_object.site), "index.html") && contains(keys(aws_s3_object.site), "app.js")
    error_message = "the dashboard files must be uploaded"
  }
  assert {
    condition     = !contains(keys(aws_s3_object.site), "package.json")
    error_message = "only browser assets belong in the bucket"
  }
  assert {
    condition     = contains(aws_apigatewayv2_api.http.cors_configuration[0].allow_origins, "https://${aws_cloudfront_distribution.frontend.domain_name}")
    error_message = "CORS must allow the dashboard origin"
  }
  assert {
    condition     = !contains(aws_apigatewayv2_api.http.cors_configuration[0].allow_origins, "*")
    error_message = "CORS must not allow every origin"
  }
}

run "alerting" {
  command = apply

  assert {
    condition     = length(aws_sns_topic_subscription.email) == 0
    error_message = "no subscription without an email address"
  }
  assert {
    condition     = alltrue([for a in aws_cloudwatch_metric_alarm.alarm : contains(a.alarm_actions, aws_sns_topic.alerts.arn)])
    error_message = "every alarm must notify the alert topic"
  }
  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.alarm)) == toset(["checker-errors", "checker-not-running", "checker-dlq", "api-5xx"])
    error_message = "expected alarms are missing"
  }
}

run "email_subscription_when_configured" {
  command = apply

  variables {
    notification_email = "ops@example.com"
  }

  assert {
    condition     = length(aws_sns_topic_subscription.email) == 1 && aws_sns_topic_subscription.email[0].protocol == "email"
    error_message = "email subscription must be created when an address is given"
  }
}

run "rejects_invalid_email" {
  command = plan
  variables {
    notification_email = "not-an-email"
  }
  expect_failures = [var.notification_email]
}

run "rejects_capacity_beyond_free_tier" {
  command = plan
  variables {
    dynamodb_capacity = 13
  }
  expect_failures = [var.dynamodb_capacity]
}

run "rejects_unbounded_endpoint_cap" {
  command = plan
  variables {
    max_endpoints = 500
  }
  expect_failures = [var.max_endpoints]
}
