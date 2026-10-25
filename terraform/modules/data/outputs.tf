output "endpoints_table_name" {
  description = "DynamoDB table of monitored endpoints."
  value       = aws_dynamodb_table.endpoints.name
}

output "endpoints_table_arn" {
  description = "ARN of the endpoints table."
  value       = aws_dynamodb_table.endpoints.arn
}

output "history_table_name" {
  description = "DynamoDB table of checks, daily rollups and incidents."
  value       = aws_dynamodb_table.history.name
}

output "history_table_arn" {
  description = "ARN of the history table."
  value       = aws_dynamodb_table.history.arn
}
