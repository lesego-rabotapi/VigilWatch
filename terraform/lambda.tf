data "archive_file" "uptime_checker_zip" {
  type        = "zip"
  source_file = "../lambda/uptime_check.py"
  output_path = "../lambda/uptime_check.zip"
}

resource "aws_lambda_function" "uptime_checker" {
  filename         = data.archive_file.uptime_checker_zip.output_path
  source_code_hash = data.archive_file.uptime_checker_zip.output_base64sha256

  function_name = "uptime_checker"
  handler       = "uptime_checker.lambda_handler"
  runtime       = "python3.11"
  role          = aws_iam_role.lambda_role.arn
  timeout       = 10
}

resource "aws_lambda_function" "register_endpoint" {
  function_name = "register-endpoint"
  handler       = "register_endpoint.lambda_handler"
  runtime       = "python3.10"
  role          = aws_iam_role.lambda_role.arn
  filename      = "register_endpoint.zip"
}