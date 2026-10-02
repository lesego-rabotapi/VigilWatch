# Alarms watch the monitor itself. Monitored-endpoint downtime is alerted
# directly by the checker (SNS), so it is not duplicated here.
# Four standard alarms; the free tier covers ten.

locals {
  alarms = {
    "checker-errors" = {
      description = "The uptime checker failed internally (DynamoDB/SNS errors, crashes)."
      namespace   = "AWS/Lambda"
      metric      = "Errors"
      dimensions  = { FunctionName = aws_lambda_function.fn["uptime_check"].function_name }
      statistic   = "Sum"
      period      = 300
      periods     = 1
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 1
      missing     = "notBreaching"
    }
    "checker-not-running" = {
      description = "The uptime checker has not been invoked for 30 minutes: monitoring is blind."
      namespace   = "AWS/Lambda"
      metric      = "Invocations"
      dimensions  = { FunctionName = aws_lambda_function.fn["uptime_check"].function_name }
      statistic   = "Sum"
      period      = 900
      periods     = 2
      comparison  = "LessThanThreshold"
      threshold   = 1
      missing     = "breaching"
    }
    "checker-dlq" = {
      description = "A scheduled checker run failed and was dead-lettered."
      namespace   = "AWS/SQS"
      metric      = "ApproximateNumberOfMessagesVisible"
      dimensions  = { QueueName = aws_sqs_queue.checker_dlq.name }
      statistic   = "Maximum"
      period      = 300
      periods     = 1
      comparison  = "GreaterThanThreshold"
      threshold   = 0
      missing     = "notBreaching"
    }
    "api-5xx" = {
      description = "The public API is returning server errors."
      namespace   = "AWS/ApiGateway"
      metric      = "5xx"
      dimensions  = { ApiId = aws_apigatewayv2_api.http.id, Stage = "$default" }
      statistic   = "Sum"
      period      = 300
      periods     = 1
      comparison  = "GreaterThanOrEqualToThreshold"
      threshold   = 5
      missing     = "notBreaching"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "alarm" {
  for_each = local.alarms

  alarm_name          = "${var.project_name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = each.value.statistic
  period              = each.value.period
  evaluation_periods  = each.value.periods
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  treat_missing_data  = each.value.missing
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
