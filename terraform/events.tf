resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.project_name}-uptime-check"
  description         = "Runs the VigilWatch uptime checker"
  schedule_expression = var.check_interval_minutes == 1 ? "rate(1 minute)" : "rate(${var.check_interval_minutes} minutes)"
}

resource "aws_cloudwatch_event_target" "checker" {
  rule = aws_cloudwatch_event_rule.schedule.name
  arn  = aws_lambda_function.fn["uptime_check"].arn
}

resource "aws_lambda_permission" "events_invoke_checker" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["uptime_check"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

# A failed scheduled run is not retried (the next run is minutes away) but is
# kept for inspection, and the DLQ alarm fires.
resource "aws_sqs_queue" "checker_dlq" {
  name                      = "${var.project_name}-uptime-check-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_lambda_function_event_invoke_config" "checker" {
  function_name                = aws_lambda_function.fn["uptime_check"].function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 300

  destination_config {
    on_failure {
      destination = aws_sqs_queue.checker_dlq.arn
    }
  }
}
