# One role per function, each scoped to exactly the resources and actions it uses.
#
# The policy documents are built from names and variables only (never from resource attributes), so
# they are known at plan time. That lets a test render the exact documents and enforce them against
# the handlers without an AWS account (see output.function_policies).

locals {
  log_group_arn = {
    for key, name in local.function_names :
    key => "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${name}:*"
  }
  dlq_arn = "arn:aws:sqs:${var.aws_region}:${var.account_id}:${local.function_names["uptime_check"]}-dlq"

  log_statement = {
    for key, _ in local.functions : key => {
      Sid      = "WriteOwnLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = [local.log_group_arn[key]]
    }
  }

  function_statements = {
    uptime_check = [
      {
        Sid      = "ReadAndUpdateEndpoints"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = [var.endpoints_table_arn]
      },
      {
        Sid      = "WriteHistory"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = [var.history_table_arn]
      },
      {
        Sid      = "PublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [var.sns_topic_arn]
      },
      {
        Sid      = "DeadLetter"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [local.dlq_arn]
      },
    ]

    register_endpoint = [
      {
        Sid      = "RegisterEndpoints"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = [var.endpoints_table_arn]
      },
      {
        Sid      = "FirstCheckHistory"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Resource = [var.history_table_arn]
      },
      {
        Sid      = "PublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [var.sns_topic_arn]
      },
    ]

    get_checks = [
      {
        Sid      = "ReadEndpoint"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = [var.endpoints_table_arn]
      },
      {
        Sid      = "ReadHistory"
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = [var.history_table_arn]
      },
    ]
  }

  function_policies = {
    for key, _ in local.functions : key => jsonencode({
      Version   = "2012-10-17"
      Statement = concat([local.log_statement[key]], local.function_statements[key])
    })
  }
}

resource "aws_iam_role" "fn" {
  for_each = local.functions

  name = local.function_names[each.key]

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions

  name   = "least-privilege"
  role   = aws_iam_role.fn[each.key].id
  policy = local.function_policies[each.key]
}
