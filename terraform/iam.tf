# One role per function, each scoped to exactly the resources and actions it uses.

locals {
  log_statement = {
    for name, _ in local.functions : name => {
      Sid      = "WriteOwnLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${aws_cloudwatch_log_group.fn[name].arn}:*"]
    }
  }

  function_statements = {
    uptime_check = [
      {
        Sid      = "ReadAndUpdateEndpoints"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.endpoints.arn]
      },
      {
        Sid      = "WriteHistory"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.history.arn]
      },
      {
        Sid      = "PublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.alerts.arn]
      },
      {
        Sid      = "DeadLetter"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.checker_dlq.arn]
      },
    ]

    register_endpoint = [
      {
        Sid      = "RegisterEndpoints"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.endpoints.arn]
      },
      {
        Sid      = "FirstCheckHistory"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Resource = [aws_dynamodb_table.history.arn]
      },
      {
        Sid      = "PublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.alerts.arn]
      },
    ]

    get_checks = [
      {
        Sid      = "ReadEndpoint"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = [aws_dynamodb_table.endpoints.arn]
      },
      {
        Sid      = "ReadHistory"
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = [aws_dynamodb_table.history.arn]
      },
    ]
  }
}

resource "aws_iam_role" "fn" {
  for_each = local.functions

  name = "${var.project_name}-${replace(each.key, "_", "-")}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions

  name = "least-privilege"
  role = aws_iam_role.fn[each.key].id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = concat([local.log_statement[each.key]], local.function_statements[each.key])
  })
}
