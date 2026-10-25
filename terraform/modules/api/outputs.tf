output "api_id" {
  description = "ID of the HTTP API, for alarms."
  value       = aws_apigatewayv2_api.http.id
}

output "base_url" {
  description = "Base URL of the HTTP API (no trailing slash)."
  value       = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
}
