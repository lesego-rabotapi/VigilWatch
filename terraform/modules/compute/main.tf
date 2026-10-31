# Three handlers from one prebuilt bundle (stdlib + the runtime's boto3 only). The bundle is built once
# by scripts/build_bundle.py so every environment deploys the same bytes.

locals {
  functions = {
    uptime_check = {
      handler     = "uptime_check.lambda_handler"
      description = "Scheduled probe of all monitored endpoints"
      timeout     = 60
    }
    register_endpoint = {
      handler     = "register_endpoint.lambda_handler"
      description = "POST /register"
      timeout     = 15
    }
    get_checks = {
      handler     = "get_checks.lambda_handler"
      description = "GET /checks"
      timeout     = 5
    }
  }

  function_names = { for key, _ in local.functions : key => "${var.name_prefix}-${replace(key, "_", "-")}" }

  function_env = {
    ENDPOINTS_TABLE    = var.endpoints_table
    HISTORY_TABLE      = var.history_table
    SNS_TOPIC_ARN      = var.sns_topic_arn
    MAX_ENDPOINTS      = tostring(var.max_endpoints)
    FAILURE_THRESHOLD  = tostring(var.failure_threshold)
    DEGRADED_MS        = tostring(var.degraded_ms)
    RECOVERY_THRESHOLD = tostring(var.recovery_threshold)
    REMINDER_MINUTES   = tostring(var.reminder_minutes)
    METRICS_ENABLED    = tostring(var.metrics_enabled)
    PROBE_TIMEOUT_S    = "5"
    CONTROL_URLS       = join(",", var.control_urls)
  }
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each = local.functions

  name              = "/aws/lambda/${local.function_names[each.key]}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = local.function_names[each.key]
  description      = each.value.description
  role             = aws_iam_role.fn[each.key].arn
  handler          = each.value.handler
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 128
  timeout          = each.value.timeout
  filename         = var.bundle_path
  source_code_hash = var.bundle_sha256

  environment {
    variables = local.function_env
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.fn[each.key].name
  }

  depends_on = [aws_iam_role_policy.fn]
}

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.name_prefix}-uptime-check"
  description         = "Runs the VigilWatch uptime checker (${var.name_prefix})"
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
  name                      = "${local.function_names["uptime_check"]}-dlq"
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
