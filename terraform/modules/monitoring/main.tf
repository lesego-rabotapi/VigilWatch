# Alarms watch the monitor itself. Monitored-endpoint downtime is alerted
# directly by the checker (SNS), so it is not duplicated here.
# Ten standard alarms are free per account, shared by every environment, so each
# environment asks for only the alarms it needs (enabled_alarms).

locals {
  all_alarms = {
    "checker-errors" = {
      description = "The uptime checker failed internally (DynamoDB/SNS errors, crashes)."
      namespace   = "AWS/Lambda"
      metric      = "Errors"
      dimensions  = { FunctionName = var.checker_function }
      statistic   = "Sum"
      period      = 300
      periods     = 1
      datapoints  = 1
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 1
      missing     = "notBreaching"
    }
    "checker-not-running" = {
      description = "The uptime checker has not been invoked for 30 minutes: monitoring is blind."
      namespace   = "AWS/Lambda"
      metric      = "Invocations"
      dimensions  = { FunctionName = var.checker_function }
      statistic   = "Sum"
      period      = 900
      periods     = 2
      datapoints  = 2
      comparison  = "LessThanThreshold"
      threshold   = 1
      missing     = "breaching"
    }
    "checker-dlq" = {
      description = "A scheduled checker run failed and was dead-lettered."
      namespace   = "AWS/SQS"
      metric      = "ApproximateNumberOfMessagesVisible"
      dimensions  = { QueueName = var.dead_letter_queue }
      statistic   = "Maximum"
      period      = 300
      periods     = 1
      datapoints  = 1
      comparison  = "GreaterThanThreshold"
      threshold   = 0
      missing     = "notBreaching"
    }
    "checker-blind" = {
      description = "The checker cannot reach the internet: its connectivity checks failed. Targets are reported INCONCLUSIVE and no target alerts are sent until it recovers."
      namespace   = "VigilWatch"
      metric      = "ControlProbeFailed"
      dimensions  = { FunctionName = var.checker_function } # the checker sets it from its own name
      statistic   = "Maximum"
      period      = 300
      periods     = 3
      datapoints  = 2
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 1
      missing     = "notBreaching"
    }
    "api-5xx" = {
      description = "The public API is returning server errors."
      namespace   = "AWS/ApiGateway"
      metric      = "5xx"
      dimensions  = { ApiId = var.api_id, Stage = "$default" }
      statistic   = "Sum"
      period      = 300
      periods     = 1
      datapoints  = 1
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 5
      missing     = "notBreaching"
    }
  }

  alarms = { for name, alarm in local.all_alarms : name => alarm if contains(var.enabled_alarms, name) }
}

resource "aws_cloudwatch_metric_alarm" "alarm" {
  for_each = local.alarms

  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = each.value.statistic
  period              = each.value.period
  evaluation_periods  = each.value.periods
  datapoints_to_alarm = each.value.datapoints
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  treat_missing_data  = each.value.missing
  alarm_actions       = [var.topic_arn]
  ok_actions          = [var.topic_arn]
}
