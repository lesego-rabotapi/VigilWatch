output "environment" {
  description = "Name of this environment."
  value       = module.stack.environment
}

output "dashboard_url" {
  description = "Public URL of the dashboard."
  value       = module.stack.dashboard_url
}

output "api_base_url" {
  description = "Base URL of the HTTP API (no trailing slash)."
  value       = module.stack.api_base_url
}

output "cloudfront_distribution_id" {
  description = "Used by CI to invalidate the cache after a deploy."
  value       = module.stack.cloudfront_distribution_id
}

output "frontend_bucket" {
  description = "S3 bucket holding the dashboard files."
  value       = module.stack.frontend_bucket
}

output "endpoints_table" {
  description = "DynamoDB table of monitored endpoints."
  value       = module.stack.endpoints_table
}

output "history_table" {
  description = "DynamoDB table of checks, daily rollups and incidents."
  value       = module.stack.history_table
}

output "sns_topic_arn" {
  description = "Alert topic (endpoint DOWN/RECOVERED and monitor health alarms)."
  value       = module.stack.sns_topic_arn
}

output "checker_function_name" {
  description = "Scheduled uptime checker Lambda."
  value       = module.stack.checker_function_name
}

output "checker_dlq_url" {
  description = "Dead-letter queue for failed scheduled runs."
  value       = module.stack.checker_dlq_url
}

output "alarm_names" {
  description = "Names of the alarms created in this environment."
  value       = module.stack.alarm_names
}

output "region" {
  description = "AWS region."
  value       = module.stack.region
}
