output "api_gateway_invoke_url" {
  description = "Invoke URL of the Uptime Monitoring API"
  value       = aws_api_gateway_deployment.uptime_api.invoke_url
}

output "dynamodb_table_name" {
  description = "DynamoDB table storing uptime check results"
  value       = aws_dynamodb_table.uptime_table.name
}

output "sns_topic_arn" {
  description = "SNS topic ARN for downtime alerts"
  value       = aws_sns_topic.alerts.arn
}
