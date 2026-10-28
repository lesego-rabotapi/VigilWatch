# req: VW-015 VW-022 VW-025
# Alarms that watch the monitor itself. The AWS provider is mocked.

mock_provider "aws" {}

variables {
  name_prefix       = "vigilwatch-prod"
  topic_arn         = "arn:aws:sns:af-south-1:123456789012:vigilwatch-prod-alerts"
  checker_function  = "vigilwatch-prod-uptime-check"
  dead_letter_queue = "vigilwatch-prod-uptime-check-dlq"
  api_id            = "abc123"
  enabled_alarms    = ["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"]
  aws_region        = "af-south-1"
  function_names = {
    uptime_check      = "vigilwatch-prod-uptime-check"
    register_endpoint = "vigilwatch-prod-register-endpoint"
    get_checks        = "vigilwatch-prod-get-checks"
  }
  tables               = ["vigilwatch-prod-endpoints", "vigilwatch-prod-history"]
  api_access_log_group = "/aws/apigateway/vigilwatch-prod-http"
  metrics_enabled      = true
}

run "every_alarm_notifies_the_topic_and_carries_the_environment" {
  command = apply

  assert {
    condition     = alltrue([for a in aws_cloudwatch_metric_alarm.alarm : contains(a.alarm_actions, var.topic_arn) && contains(a.ok_actions, var.topic_arn)])
    error_message = "every alarm must notify the alert topic"
  }
  assert {
    condition     = alltrue([for k, a in aws_cloudwatch_metric_alarm.alarm : a.alarm_name == "vigilwatch-prod-${k}"])
    error_message = "alarm names must carry the environment prefix"
  }
  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.alarm)) == toset(["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"])
    error_message = "all five alarms were requested"
  }
}

run "alarms_watch_this_environments_resources" {
  command = apply

  assert {
    condition     = aws_cloudwatch_metric_alarm.alarm["checker-errors"].dimensions["FunctionName"] == "vigilwatch-prod-uptime-check"
    error_message = "the error alarm must watch this environment's checker"
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.alarm["checker-dlq"].dimensions["QueueName"] == "vigilwatch-prod-uptime-check-dlq"
    error_message = "the queue alarm must watch this environment's queue"
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.alarm["api-5xx"].dimensions["ApiId"] == "abc123"
    error_message = "the API alarm must watch this environment's API"
  }
}

run "a_blind_checker_alarms_from_the_control_metric" {
  command = apply

  assert {
    condition = (aws_cloudwatch_metric_alarm.alarm["checker-blind"].metric_name == "ControlProbeFailed"
      && aws_cloudwatch_metric_alarm.alarm["checker-blind"].namespace == "VigilWatch"
    && aws_cloudwatch_metric_alarm.alarm["checker-blind"].dimensions["FunctionName"] == "vigilwatch-prod-uptime-check")
    error_message = "a blind checker must raise an alarm from this environment's ControlProbeFailed series only"
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.alarm["checker-blind"].datapoints_to_alarm == 2 && aws_cloudwatch_metric_alarm.alarm["checker-blind"].evaluation_periods == 3
    error_message = "one control blip must not alarm: require 2 of 3 periods"
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.alarm["checker-blind"].treat_missing_data == "notBreaching"
    error_message = "the metric is only emitted when connectivity was checked, so missing data is healthy"
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.alarm["checker-not-running"].treat_missing_data == "breaching"
    error_message = "silence from the checker is itself the failure"
  }
}

run "only_the_requested_alarms_are_created" {
  command = apply

  variables {
    name_prefix    = "vigilwatch-dev"
    enabled_alarms = ["checker-errors", "checker-not-running"]
  }

  assert {
    condition     = toset(keys(aws_cloudwatch_metric_alarm.alarm)) == toset(["checker-errors", "checker-not-running"])
    error_message = "only the requested alarms may exist, so a second environment stays inside the free tier"
  }
  assert {
    condition     = toset(output.alarm_names) == toset(["vigilwatch-dev-checker-errors", "vigilwatch-dev-checker-not-running"])
    error_message = "created alarm names must be exported"
  }
}

run "rejects_an_unknown_alarm" {
  command = plan
  variables {
    enabled_alarms = ["checker-errors", "made-up"]
  }
  expect_failures = [var.enabled_alarms]
}

run "rejects_duplicate_alarms" {
  command = plan
  variables {
    enabled_alarms = ["checker-errors", "checker-errors"]
  }
  expect_failures = [var.enabled_alarms]
}

run "the_dashboard_shows_the_four_golden_signals" {
  command = apply

  assert {
    condition     = aws_cloudwatch_dashboard.golden_signals.dashboard_name == "vigilwatch-prod-golden-signals"
    error_message = "one dashboard per environment, named after it"
  }
  assert {
    condition = alltrue([for signal in ["Latency", "Traffic", "Errors", "Saturation"] : anytrue([
      for w in jsondecode(aws_cloudwatch_dashboard.golden_signals.dashboard_body).widgets :
      strcontains(try(w.properties.title, ""), signal)
    ])])
    error_message = "latency, traffic, errors and saturation each need a widget"
  }
  assert {
    condition = sum([
      for w in jsondecode(aws_cloudwatch_dashboard.golden_signals.dashboard_body).widgets :
      length(try(w.properties.metrics, []))
    ]) <= 50
    error_message = "a free dashboard shows at most 50 metrics, this one ${sum([for w in jsondecode(aws_cloudwatch_dashboard.golden_signals.dashboard_body).widgets : length(try(w.properties.metrics, []))])}"
  }
}

run "every_metric_is_a_whole_line_namespace_name_and_dimensions" {
  command = apply

  assert {
    condition = alltrue(flatten([
      for w in jsondecode(aws_cloudwatch_dashboard.golden_signals.dashboard_body).widgets : [
        for m in try(w.properties.metrics, []) : can(length(m)) && length(m) >= 4
      ]
    ]))
    error_message = "a metric line split into loose strings (flatten does that) shows nothing"
  }
}

run "the_dashboard_shows_this_environments_resources" {
  command = apply

  assert {
    condition = alltrue([for name in [
      "vigilwatch-prod-uptime-check", "vigilwatch-prod-register-endpoint", "vigilwatch-prod-get-checks",
      "vigilwatch-prod-endpoints", "vigilwatch-prod-history", "vigilwatch-prod-uptime-check-dlq", "abc123",
    ] : strcontains(aws_cloudwatch_dashboard.golden_signals.dashboard_body, name)])
    error_message = "every function, table, the queue and the API appear on the dashboard"
  }
  assert {
    condition     = !strcontains(aws_cloudwatch_dashboard.golden_signals.dashboard_body, "vigilwatch-dev")
    error_message = "no other environment's resources"
  }
  assert {
    condition     = strcontains(aws_cloudwatch_dashboard.golden_signals.dashboard_body, "ControlProbeFailed")
    error_message = "where the checker publishes its control metric, the dashboard shows it"
  }
}

run "the_control_metric_is_shown_only_where_it_is_published" {
  command = apply

  variables {
    metrics_enabled = false
  }

  assert {
    condition     = !strcontains(aws_cloudwatch_dashboard.golden_signals.dashboard_body, "ControlProbeFailed")
    error_message = "dev publishes no custom metric, so an empty widget would only mislead"
  }
}

run "saved_queries_cover_errors_runs_server_errors_and_slow_requests" {
  command = apply

  assert {
    condition     = toset(keys(aws_cloudwatch_query_definition.query)) == toset(["function-errors", "checker-runs", "api-5xx", "api-slow"])
    error_message = "the four triage queries"
  }
  assert {
    condition     = alltrue([for q in aws_cloudwatch_query_definition.query : startswith(q.name, "vigilwatch-prod/")])
    error_message = "queries are grouped under the environment"
  }
  assert {
    condition = toset(aws_cloudwatch_query_definition.query["function-errors"].log_group_names) == toset([
      "/aws/lambda/vigilwatch-prod-uptime-check", "/aws/lambda/vigilwatch-prod-register-endpoint", "/aws/lambda/vigilwatch-prod-get-checks",
    ])
    error_message = "function errors are searched in every function's log group"
  }
  assert {
    condition     = aws_cloudwatch_query_definition.query["checker-runs"].log_group_names == tolist(["/aws/lambda/vigilwatch-prod-uptime-check"])
    error_message = "checker runs come from the checker's log group"
  }
  assert {
    condition = alltrue([for k in ["api-5xx", "api-slow"] :
    aws_cloudwatch_query_definition.query[k].log_group_names == tolist(["/aws/apigateway/vigilwatch-prod-http"])])
    error_message = "API queries read the access log"
  }
  assert {
    condition     = strcontains(aws_cloudwatch_query_definition.query["function-errors"].query_string, "level = \"ERROR\"")
    error_message = "the application logs JSON with a level field (lambda/common/logs.py)"
  }
}
