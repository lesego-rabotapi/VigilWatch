resource "aws_lambda_function" "uptime_checker" {
  function_name = "uptime_checker"
  role          = aws_iam_role.lambda_role.arn
  handler       = "uptime_checker.lambda_handler"
  runtime       = "python3.11"

  filename = "../lambda/uptime_checker.zip"

  timeout = 10
  memory_size = 128
}


resource "aws_lambda_function" "register_endpoint" {
  function_name = "register-endpoint"
  handler       = "register_endpoint.lambda_handler"
  runtime       = "python3.10"
  role          = aws_iam_role.lambda_role.arn
  filename      = "register_endpoint.zip"
}