# req: VW-015 VW-022
# Alarms that watch the monitor itself. The AWS provider is mocked.

mock_provider "aws" {}

variables {
  name_prefix       = "vigilwatch-prod"
  topic_arn         = "arn:aws:sns:af-south-1:123456789012:vigilwatch-prod-alerts"
  checker_function  = "vigilwatch-prod-uptime-check"
  dead_letter_queue = "vigilwatch-prod-uptime-check-dlq"
  api_id            = "abc123"
  enabled_alarms    = ["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"]
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
    && aws_cloudwatch_metric_alarm.alarm["checker-blind"].dimensions["Service"] == "uptime-check")
    error_message = "a blind checker must raise an alarm from the ControlProbeFailed metric"
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
