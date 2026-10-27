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

# Optional tuning. Each is null unless set in terraform.tfvars or with -var, and the stack module
# then applies its own default, so defaults live in one place.
variable "project_name" {
  description = "Project part of every resource name. Unset (null) keeps the module default."
  type        = string
  default     = null
}

variable "check_interval_minutes" {
  description = "Minutes between scheduled uptime checks. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "max_endpoints" {
  description = "Maximum number of monitored URLs. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "failure_threshold" {
  description = "Consecutive DOWN checks before an incident opens and an alert is sent. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "recovery_threshold" {
  description = "Consecutive healthy checks before an incident closes. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "reminder_minutes" {
  description = "Send a 'still down' reminder this often while an incident is open; 0 is off. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "degraded_ms" {
  description = "Latency (ms) at or above which a correct response is DEGRADED. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "extra_control_urls" {
  description = "Independent sites probed to tell a down target from a blind checker. Unset (null) keeps the module default."
  type        = list(string)
  default     = null
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for all log groups. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "api_throttle_rate" {
  description = "Steady-state requests per second allowed on the public API. Unset (null) keeps the module default."
  type        = number
  default     = null
}

variable "api_throttle_burst" {
  description = "Burst requests allowed on the public API. Unset (null) keeps the module default."
  type        = number
  default     = null
}
