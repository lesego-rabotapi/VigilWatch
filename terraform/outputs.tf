output "dashboard_url" {
  description = "Public URL of the dashboard."
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "api_base_url" {
  description = "Base URL of the HTTP API (no trailing slash)."
  value       = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
}

output "cloudfront_distribution_id" {
  description = "Used by CI to invalidate the cache after a deploy."
  value       = aws_cloudfront_distribution.frontend.id
}

output "frontend_bucket" {
  description = "S3 bucket holding the dashboard files."
  value       = aws_s3_bucket.frontend.bucket
}

output "endpoints_table" {
  description = "DynamoDB table of monitored endpoints."
  value       = aws_dynamodb_table.endpoints.name
}

output "history_table" {
  description = "DynamoDB table of checks, daily rollups and incidents."
  value       = aws_dynamodb_table.history.name
}

output "sns_topic_arn" {
  description = "Alert topic (endpoint DOWN/RECOVERED and monitor health alarms)."
  value       = aws_sns_topic.alerts.arn
}

output "checker_function_name" {
  description = "Scheduled uptime checker Lambda."
  value       = aws_lambda_function.fn["uptime_check"].function_name
}

output "checker_dlq_url" {
  description = "Dead-letter queue for failed scheduled runs."
  value       = aws_sqs_queue.checker_dlq.url
}

output "region" {
  description = "AWS region."
  value       = var.aws_region
}
