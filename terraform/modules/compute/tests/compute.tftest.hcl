# req: VW-004 VW-016 VW-017 VW-022 VW-023
# Lambda functions, their roles, the schedule and the dead-letter queue. The AWS provider is mocked.

mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:af-south-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:af-south-1:123456789012:function:mock"
      invoke_arn = "arn:aws:apigateway:af-south-1:lambda:path/2015-03-31/functions/arn:aws:lambda:af-south-1:123456789012:function:mock/invocations"
    }
  }
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:af-south-1:123456789012:mock"
      url = "https://sqs.af-south-1.amazonaws.com/123456789012/mock"
    }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:af-south-1:123456789012:rule/mock" }
  }
}

variables {
  name_prefix         = "vigilwatch-dev"
  aws_region          = "af-south-1"
  account_id          = "123456789012"
  bundle_path         = "bundle.zip"
  bundle_sha256       = "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="
  endpoints_table_arn = "arn:aws:dynamodb:af-south-1:123456789012:table/vigilwatch-dev-endpoints"
  history_table_arn   = "arn:aws:dynamodb:af-south-1:123456789012:table/vigilwatch-dev-history"
  endpoints_table     = "vigilwatch-dev-endpoints"
  history_table       = "vigilwatch-dev-history"
  sns_topic_arn       = "arn:aws:sns:af-south-1:123456789012:vigilwatch-dev-alerts"
  control_urls        = ["https://d111111abcdef8.cloudfront.net/healthz.txt", "https://control.example.org/"]
}

run "core_loop_is_wired" {
  command = apply

  assert {
    condition     = aws_cloudwatch_event_rule.schedule.schedule_expression == "rate(5 minutes)"
    error_message = "the checker must run every 5 minutes by default"
  }
  assert {
    condition     = aws_cloudwatch_event_target.checker.arn == aws_lambda_function.fn["uptime_check"].arn
    error_message = "the schedule must target the checker"
  }
  assert {
    condition = (aws_lambda_permission.events_invoke_checker.principal == "events.amazonaws.com"
      && aws_lambda_permission.events_invoke_checker.function_name == aws_lambda_function.fn["uptime_check"].function_name
    && aws_lambda_permission.events_invoke_checker.source_arn == aws_cloudwatch_event_rule.schedule.arn)
    error_message = "EventBridge (this rule only) must be allowed to invoke the checker"
  }
  assert {
    condition     = aws_lambda_function_event_invoke_config.checker.destination_config[0].on_failure[0].destination == aws_sqs_queue.checker_dlq.arn
    error_message = "failed async checker runs must land in the dead-letter queue"
  }
  assert {
    condition     = aws_lambda_function_event_invoke_config.checker.maximum_retry_attempts == 0
    error_message = "a failed run is not retried: the next one is minutes away"
  }
}

run "names_carry_the_environment" {
  command = apply

  assert {
    condition     = toset([for f in aws_lambda_function.fn : f.function_name]) == toset(["vigilwatch-dev-uptime-check", "vigilwatch-dev-register-endpoint", "vigilwatch-dev-get-checks"])
    error_message = "function names must carry the environment prefix"
  }
  assert {
    condition     = aws_sqs_queue.checker_dlq.name == "vigilwatch-dev-uptime-check-dlq"
    error_message = "the queue name must carry the environment prefix"
  }
  assert {
    condition     = output.checker_function_name == "vigilwatch-dev-uptime-check"
    error_message = "the checker name must be exported"
  }
}

run "the_prebuilt_bundle_is_what_gets_deployed" {
  command = apply

  assert {
    condition     = alltrue([for f in aws_lambda_function.fn : f.filename == "bundle.zip" && f.source_code_hash == "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="])
    error_message = "every function must deploy the prebuilt bundle and its hash, not a zip made at plan time"
  }
}

run "lambdas_are_consistent" {
  command = apply

  assert {
    condition     = alltrue([for f in aws_lambda_function.fn : f.runtime == "python3.12" && contains(f.architectures, "arm64")])
    error_message = "all functions run python3.12 on arm64 (cheaper per GB-second)"
  }
  assert {
    condition     = length(aws_iam_role.fn) == 3 && alltrue([for k, f in aws_lambda_function.fn : f.role == aws_iam_role.fn[k].arn])
    error_message = "each function needs its own role"
  }
  assert {
    condition     = alltrue([for lg in aws_cloudwatch_log_group.fn : lg.retention_in_days > 0 && lg.retention_in_days <= 14])
    error_message = "log retention must be set and short (cost)"
  }
  assert {
    condition     = alltrue([for r in aws_iam_role.fn : jsondecode(r.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "123456789012"])
    error_message = "only Lambda in this account may assume the roles"
  }
}

run "the_checker_is_configured_from_the_inputs" {
  command = apply

  assert {
    condition     = aws_lambda_function.fn["uptime_check"].environment[0].variables["ENDPOINTS_TABLE"] == "vigilwatch-dev-endpoints" && aws_lambda_function.fn["uptime_check"].environment[0].variables["HISTORY_TABLE"] == "vigilwatch-dev-history"
    error_message = "functions must be told which tables to use"
  }
  assert {
    condition     = aws_lambda_function.fn["uptime_check"].environment[0].variables["CONTROL_URLS"] == "https://d111111abcdef8.cloudfront.net/healthz.txt,https://control.example.org/"
    error_message = "control URLs must reach the checker"
  }
  assert {
    condition     = aws_lambda_function.fn["uptime_check"].environment[0].variables["RECOVERY_THRESHOLD"] == "1" && aws_lambda_function.fn["uptime_check"].environment[0].variables["REMINDER_MINUTES"] == "0"
    error_message = "defaults must leave alert behaviour unchanged"
  }
  assert {
    condition     = aws_lambda_function.fn["uptime_check"].environment[0].variables["METRICS_ENABLED"] == "true"
    error_message = "metrics are on unless switched off"
  }
}

run "settings_reach_the_checker" {
  command = apply

  variables {
    recovery_threshold = 3
    reminder_minutes   = 120
    metrics_enabled    = false
    max_endpoints      = 7
  }

  assert {
    condition = (aws_lambda_function.fn["uptime_check"].environment[0].variables["RECOVERY_THRESHOLD"] == "3"
      && aws_lambda_function.fn["uptime_check"].environment[0].variables["REMINDER_MINUTES"] == "120"
      && aws_lambda_function.fn["uptime_check"].environment[0].variables["METRICS_ENABLED"] == "false"
    && aws_lambda_function.fn["register_endpoint"].environment[0].variables["MAX_ENDPOINTS"] == "7")
    error_message = "recovery_threshold, reminder_minutes, metrics_enabled and max_endpoints must be passed on"
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

run "the_policies_are_exported_for_the_enforcement_test" {
  command = apply

  assert {
    condition     = toset(keys(output.function_policies)) == toset(["uptime_check", "register_endpoint", "get_checks"])
    error_message = "every function's policy must be exported so a test can enforce it"
  }
  assert {
    condition     = alltrue([for k, p in output.function_policies : jsondecode(p).Version == "2012-10-17"])
    error_message = "exported policies must be valid policy documents"
  }
}

run "rejects_a_malformed_bundle_hash" {
  command = plan
  variables {
    bundle_sha256 = "not-a-hash"
  }
  expect_failures = [var.bundle_sha256]
}

run "rejects_out_of_range_settings" {
  command = plan
  variables {
    failure_threshold = 11
  }
  expect_failures = [var.failure_threshold]
}

run "rejects_an_insecure_control_url" {
  command = plan
  variables {
    control_urls = ["ftp://insecure.example.com/"]
  }
  expect_failures = [var.control_urls]
}

run "rejects_too_many_control_urls" {
  command = plan
  variables {
    control_urls = ["https://a.example.com/", "https://b.example.com/", "https://c.example.com/", "https://d.example.com/", "https://e.example.com/", "https://f.example.com/"]
  }
  expect_failures = [var.control_urls]
}

run "rejects_a_check_interval_outside_the_bounds" {
  command = plan
  variables {
    check_interval_minutes = 61
  }
  expect_failures = [var.check_interval_minutes]
}

run "rejects_an_unbounded_endpoint_cap" {
  command = plan
  variables {
    max_endpoints = 500
  }
  expect_failures = [var.max_endpoints]
}
