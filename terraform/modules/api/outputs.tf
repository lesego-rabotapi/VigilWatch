output "api_id" {
  description = "ID of the HTTP API, for alarms."
  value       = aws_apigatewayv2_api.http.id
}

output "base_url" {
  description = "Base URL of the HTTP API (no trailing slash)."
  value       = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
}

output "access_log_group" {
  description = "Log group of the access log, for the saved Logs Insights queries."
  value       = aws_cloudwatch_log_group.api_access.name
}
