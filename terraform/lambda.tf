data "archive_file" "uptime_check_zip" {
  type        = "zip"
  source_file = "../lambda/uptime_check.py"
  output_path = "../lambda/uptime_check.zip"
}

resource "aws_lambda_function" "uptime_check" {
  filename         = data.archive_file.uptime_check_zip.output_path
  source_code_hash = data.archive_file.uptime_check_zip.output_base64sha256

  function_name = "uptime_check"
  handler       = "uptime_check.lambda_handler"
  runtime       = "python3.11"
  role          = aws_iam_role.lambda_role.arn
  timeout       = 10
}

# Package register_endpoint lambda 
data "archive_file" "register_endpoint_zip" {
  type        = "zip"
  source_file = "../lambda/register_endpoint.py"
  output_path = "../lambda/register_endpoint.zip"
}

resource "aws_lambda_function" "register_endpoint" {
  filename         = data.archive_file.register_endpoint_zip.output_path
  source_code_hash = data.archive_file.register_endpoint_zip.output_base64sha256

  function_name = "register-endpoint"
  handler       = "register_endpoint.lambda_handler"
  runtime       = "python3.11"
  role          = aws_iam_role.lambda_role.arn
  timeout       = 10
}