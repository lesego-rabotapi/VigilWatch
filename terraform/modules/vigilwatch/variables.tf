variable "project_name" {
  description = "Project part of every resource name."
  type        = string
  default     = "vigilwatch"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,11}$", var.project_name))
    error_message = "project_name must be 3-12 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Environment part of every resource name (dev, prod). Two environments in one account must differ here."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.environment))
    error_message = "environment must be 2-10 lowercase letters or digits, starting with a letter."
  }
}

variable "aws_region" {
  description = "Region the environment is deployed into. af-south-1 is an opt-in region; enable it on the account first."
  type        = string
  default     = "af-south-1"
}

variable "frontend_dir" {
  description = "Directory holding the dashboard files to upload."
  type        = string
}

variable "bundle_path" {
  description = "Path of the prebuilt Lambda zip (scripts/build_bundle.py)."
  type        = string
}

variable "bundle_sha256" {
  description = "Base64 SHA-256 of the bundle, as printed by scripts/build_bundle.py."
  type        = string
}

variable "notification_email" {
  description = "Address subscribed to alerts. Empty disables the subscription."
  type        = string
  default     = ""
}

variable "check_interval_minutes" {
  description = "Minutes between scheduled uptime checks."
  type        = number
  default     = 5
}

variable "max_endpoints" {
  description = "Maximum number of monitored URLs. Bounds checker runtime and cost."
  type        = number
  default     = 10
}

variable "failure_threshold" {
  description = "Consecutive DOWN checks before an incident is opened and an alert is sent."
  type        = number
  default     = 2
}

variable "recovery_threshold" {
  description = "Consecutive healthy checks before an incident closes."
  type        = number
  default     = 1
}

variable "reminder_minutes" {
  description = "While an incident stays open, send a 'still down' email this often. 0 turns reminders off."
  type        = number
  default     = 0
}

variable "degraded_ms" {
  description = "Latency (ms) at or above which a correct response is reported as DEGRADED."
  type        = number
  default     = 1000
}

variable "extra_control_urls" {
  description = "Independent sites the checker probes to tell 'my target is down' from 'I cannot reach the internet'. This environment's own health file is always added."
  type        = list(string)
  default     = ["https://www.cloudflare.com/cdn-cgi/trace"]

  validation {
    condition     = length(var.extra_control_urls) <= 4 && alltrue([for u in var.extra_control_urls : startswith(u, "https://")])
    error_message = "extra_control_urls must hold at most 4 https:// URLs (5 controls in total with the built-in one)."
  }
}

variable "metrics_enabled" {
  description = "Publish the checker's custom CloudWatch metrics. Ten are free per account and one environment publishes seven."
  type        = bool
  default     = true
}

variable "enabled_alarms" {
  description = "Which alarms to create. Ten are free per account across all environments."
  type        = list(string)
  default     = ["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"]

  validation {
    condition     = var.metrics_enabled || !contains(var.enabled_alarms, "checker-blind")
    error_message = "checker-blind alarms on a custom metric, so it needs metrics_enabled = true."
  }
}

variable "dynamodb_capacity" {
  description = "Provisioned RCU and WCU for each of the two tables. The free tier covers 25 of each per account."
  type        = number
  default     = 5
}

variable "dynamodb_deletion_protection" {
  description = "Protect tables from accidental deletion."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for all log groups."
  type        = number
  default     = 14
}

variable "api_throttle_rate" {
  description = "Steady-state requests per second allowed on the public API."
  type        = number
  default     = 5
}

variable "api_throttle_burst" {
  description = "Burst requests allowed on the public API."
  type        = number
  default     = 10
}

variable "extra_cors_origins" {
  description = "Additional origins allowed to call the API (for example a local dev server)."
  type        = list(string)
  default     = []
}
