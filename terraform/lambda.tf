# One bundle of lambda/ (stdlib + the runtime's boto3 only), three handlers.
data "archive_file" "bundle" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/.build/vigilwatch.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

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

  function_env = {
    ENDPOINTS_TABLE   = aws_dynamodb_table.endpoints.name
    HISTORY_TABLE     = aws_dynamodb_table.history.name
    SNS_TOPIC_ARN     = aws_sns_topic.alerts.arn
    MAX_ENDPOINTS     = tostring(var.max_endpoints)
    FAILURE_THRESHOLD = tostring(var.failure_threshold)
    DEGRADED_MS       = tostring(var.degraded_ms)
    PROBE_TIMEOUT_S   = "5"
  }
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each = local.functions

  name              = "/aws/lambda/${var.project_name}-${replace(each.key, "_", "-")}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${var.project_name}-${replace(each.key, "_", "-")}"
  description      = each.value.description
  role             = aws_iam_role.fn[each.key].arn
  handler          = each.value.handler
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 128
  timeout          = each.value.timeout
  filename         = data.archive_file.bundle.output_path
  source_code_hash = data.archive_file.bundle.output_base64sha256

  environment {
    variables = local.function_env
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.fn[each.key].name
  }

  depends_on = [aws_iam_role_policy.fn]
}
