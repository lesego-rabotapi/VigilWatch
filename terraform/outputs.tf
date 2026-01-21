output "api_gateway_invoke_url" {
  description = "Base invoke URL for the API Gateway stage"
  value       = "https://${aws_api_gateway_rest_api.uptime_api.id}.execute-api.${var.aws_region}.amazonaws.com/${aws_api_gateway_stage.prod.stage_name}"
}

output "dynamodb_table_name" {
  description = "DynamoDB table storing uptime check results"
  value       = aws_dynamodb_table.uptime_table.name
}

output "sns_topic_arn" {
  description = "SNS topic ARN for downtime alerts"
  value       = aws_sns_topic.alerts.arn
}

## resource "aws_api_gateway_stage" "prod" { 
##  stage_name    = "prod"
##  rest_api_id  = aws_api_gateway_rest_api.uptime_api.id
##  deployment_id = aws_api_gateway_deployment.uptime_api.id
##}