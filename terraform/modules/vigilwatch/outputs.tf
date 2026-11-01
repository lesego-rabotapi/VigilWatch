output "environment" {
  description = "Name of this environment."
  value       = var.environment
}

output "dashboard_url" {
  description = "Public URL of the dashboard."
  value       = module.frontend.dashboard_url
}

output "api_base_url" {
  description = "Base URL of the HTTP API (no trailing slash)."
  value       = module.api.base_url
}

output "cloudfront_distribution_id" {
  description = "Used by CI to invalidate the cache after a deploy."
  value       = module.frontend.distribution_id
}

output "frontend_bucket" {
  description = "S3 bucket holding the dashboard files."
  value       = module.frontend.bucket
}

output "endpoints_table" {
  description = "DynamoDB table of monitored endpoints."
  value       = module.data.endpoints_table_name
}

output "history_table" {
  description = "DynamoDB table of checks, daily rollups and incidents."
  value       = module.data.history_table_name
}

output "sns_topic_arn" {
  description = "Alert topic (endpoint DOWN/RECOVERED and monitor health alarms)."
  value       = module.alerts.topic_arn
}

output "checker_function_name" {
  description = "Scheduled uptime checker Lambda."
  value       = module.compute.checker_function_name
}

output "checker_dlq_url" {
  description = "Dead-letter queue for failed scheduled runs."
  value       = module.compute.dlq_url
}

output "alarm_names" {
  description = "Names of the alarms created in this environment."
  value       = module.monitoring.alarm_names
}

output "region" {
  description = "AWS region."
  value       = var.aws_region
}

output "user_pool_id" {
  description = "Cognito user pool: create users with aws cognito-idp admin-create-user."
  value       = module.auth.user_pool_id
}

output "hosted_ui_url" {
  description = "Cognito hosted UI the dashboard signs in on."
  value       = module.auth.hosted_ui_url
}

output "dashboard_client_id" {
  description = "The dashboard's public Cognito client."
  value       = module.auth.dashboard_client_id
}

output "smoke_client_id" {
  description = "The Cognito client the smoke tests sign in with."
  value       = module.auth.smoke_client_id
}

output "max_endpoints_per_user" {
  description = "The per-user cap in force."
  value       = coalesce(var.max_endpoints_per_user, min(5, var.max_endpoints))
}
