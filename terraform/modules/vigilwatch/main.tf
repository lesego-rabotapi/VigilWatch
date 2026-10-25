# One complete VigilWatch environment. The environments under terraform/envs/ call this module with
# their own names and sizes; everything else lives in the focused modules it composes.

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
}

module "alerts" {
  source = "../alerts"

  name_prefix        = local.name_prefix
  notification_email = var.notification_email
}

module "data" {
  source = "../data"

  name_prefix         = local.name_prefix
  capacity            = var.dynamodb_capacity
  deletion_protection = var.dynamodb_deletion_protection
}

module "compute" {
  source = "../compute"

  name_prefix            = local.name_prefix
  aws_region             = var.aws_region
  account_id             = local.account_id
  bundle_path            = var.bundle_path
  bundle_sha256          = var.bundle_sha256
  endpoints_table        = module.data.endpoints_table_name
  endpoints_table_arn    = module.data.endpoints_table_arn
  history_table          = module.data.history_table_name
  history_table_arn      = module.data.history_table_arn
  sns_topic_arn          = module.alerts.topic_arn
  control_urls           = concat(["https://${module.frontend.domain_name}/healthz.txt"], var.extra_control_urls)
  check_interval_minutes = var.check_interval_minutes
  max_endpoints          = var.max_endpoints
  failure_threshold      = var.failure_threshold
  recovery_threshold     = var.recovery_threshold
  reminder_minutes       = var.reminder_minutes
  degraded_ms            = var.degraded_ms
  metrics_enabled        = var.metrics_enabled
  log_retention_days     = var.log_retention_days
}

module "api" {
  source = "../api"

  name_prefix          = local.name_prefix
  function_invoke_arns = module.compute.function_invoke_arns
  function_names       = module.compute.function_names
  allowed_origins      = concat([module.frontend.dashboard_url], var.extra_cors_origins)
  throttle_rate        = var.api_throttle_rate
  throttle_burst       = var.api_throttle_burst
  log_retention_days   = var.log_retention_days
}

module "frontend" {
  source = "../frontend"

  name_prefix  = local.name_prefix
  account_id   = local.account_id
  aws_region   = var.aws_region
  frontend_dir = var.frontend_dir
  api_base_url = module.api.base_url
}

module "monitoring" {
  source = "../monitoring"

  name_prefix       = local.name_prefix
  topic_arn         = module.alerts.topic_arn
  checker_function  = module.compute.checker_function_name
  dead_letter_queue = module.compute.dlq_name
  api_id            = module.api.api_id
  enabled_alarms    = var.enabled_alarms
}
