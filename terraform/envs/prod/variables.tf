variable "allowed_account_ids" {
  description = "The only AWS account(s) this configuration may run against. Supplied at plan time, never committed."
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) > 0 && alltrue([for id in var.allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "allowed_account_ids must list at least one 12-digit AWS account ID."
  }
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "aws_region" {
  description = "AWS region. af-south-1 is an opt-in region; enable it on the account first."
  type        = string
  default     = "af-south-1"
}

variable "bundle_path" {
  description = "Path of the prebuilt Lambda zip: python scripts/build_bundle.py prints it with bundle_sha256."
  type        = string
}

variable "bundle_sha256" {
  description = "Base64 SHA-256 of the bundle."
  type        = string
}

variable "notification_email" {
  description = "Address subscribed to alerts. Empty disables the subscription."
  type        = string
  default     = ""
}

variable "dynamodb_capacity" {
  description = "Provisioned RCU and WCU per table. Both environments share one 25-unit free tier."
  type        = number
}

variable "dynamodb_deletion_protection" {
  description = "Protect tables from accidental deletion."
  type        = bool
}

variable "metrics_enabled" {
  description = "Publish the checker's custom CloudWatch metrics (ten are free per account; one environment uses seven)."
  type        = bool
}

variable "enabled_alarms" {
  description = "Alarms to create (ten are free per account across both environments)."
  type        = list(string)
}

variable "extra_cors_origins" {
  description = "Additional origins allowed to call the API."
  type        = list(string)
  default     = []
}
