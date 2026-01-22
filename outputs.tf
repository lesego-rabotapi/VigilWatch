output "api_gateway_invoke_url" {
  description = "Invoke URL of the Uptime Monitoring API"
  value       = aws_api_gateway_stage.prod.invoke_url
}

output "frontend_s3_bucket_name" {
  description = "S3 bucket name for frontend"
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_distribution_url" {
  description = "CloudFront distribution URL for frontend"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "dynamodb_table_name" {
  description = "DynamoDB table storing uptime check results"
  value       = aws_dynamodb_table.uptime_table.name
}

output "sns_topic_arn" {
  description = "SNS topic ARN for downtime alerts"
  value       = aws_sns_topic.alerts. arn
}

output "api_gateway_id" {
  description = "API Gateway REST API ID"
  value       = aws_api_gateway_rest_api.uptime_api.id
}

output "region" {
  description = "AWS Region"
  value       = var.aws_region
}
