# Production environment: a thin root. Everything it deploys is defined in ../../modules/vigilwatch, and the
# values that make it production are in terraform.tfvars.

module "stack" {
  source = "../../modules/vigilwatch"

  environment                  = var.environment
  aws_region                   = var.aws_region
  frontend_dir                 = "${path.module}/../../../frontend"
  bundle_path                  = var.bundle_path
  bundle_sha256                = var.bundle_sha256
  notification_email           = var.notification_email
  dynamodb_capacity            = var.dynamodb_capacity
  dynamodb_deletion_protection = var.dynamodb_deletion_protection
  metrics_enabled              = var.metrics_enabled
  enabled_alarms               = var.enabled_alarms
  extra_cors_origins           = var.extra_cors_origins
}
