variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "aws_region" {
  description = "Region the functions run in (used to build the ARNs their policies grant)."
  type        = string
}

variable "account_id" {
  description = "AWS account ID. Only Lambda in this account may assume the function roles."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "bundle_path" {
  description = "Path of the prebuilt Lambda zip (scripts/build_bundle.py). Built once and deployed unchanged to every environment."
  type        = string
}

variable "bundle_sha256" {
  description = "Base64 SHA-256 of the bundle, as printed by scripts/build_bundle.py. Terraform redeploys when it changes."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9+/]{43}=$", var.bundle_sha256))
    error_message = "bundle_sha256 must be the base64-encoded SHA-256 printed by scripts/build_bundle.py."
  }
}

variable "endpoints_table" {
  description = "Name of the endpoints table."
  type        = string
}

variable "endpoints_table_arn" {
  description = "ARN of the endpoints table."
  type        = string
}

variable "history_table" {
  description = "Name of the history table."
  type        = string
}

variable "history_table_arn" {
  description = "ARN of the history table."
  type        = string
}

variable "sns_topic_arn" {
  description = "Alert topic the functions publish to."
  type        = string
}

variable "control_urls" {
  description = "Sites the checker probes to tell 'my target is down' from 'I cannot reach the internet'."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.control_urls) <= 5 && alltrue([for u in var.control_urls : startswith(u, "https://")])
    error_message = "control_urls must hold at most 5 https:// URLs."
  }
}

variable "check_interval_minutes" {
  description = "Minutes between scheduled uptime checks."
  type        = number
  default     = 5

  validation {
    condition     = var.check_interval_minutes >= 1 && var.check_interval_minutes <= 60
    error_message = "check_interval_minutes must be between 1 and 60."
  }
}

variable "max_endpoints" {
  description = "Maximum number of monitored URLs. Bounds checker runtime and cost."
  type        = number
  default     = 10

  validation {
    condition     = var.max_endpoints >= 1 && var.max_endpoints <= 50
    error_message = "max_endpoints must be between 1 and 50."
  }
}

variable "failure_threshold" {
  description = "Consecutive DOWN checks before an incident is opened and an alert is sent."
  type        = number
  default     = 2

  validation {
    condition     = var.failure_threshold >= 1 && var.failure_threshold <= 10
    error_message = "failure_threshold must be between 1 and 10."
  }
}

variable "recovery_threshold" {
  description = "Consecutive healthy checks before an incident closes and a RECOVERED email is sent. 1 closes at the first healthy check; raise it to damp flapping sites."
  type        = number
  default     = 1

  validation {
    condition     = var.recovery_threshold >= 1 && var.recovery_threshold <= 10
    error_message = "recovery_threshold must be between 1 and 10."
  }
}

variable "reminder_minutes" {
  description = "While an incident stays open, send a 'still down' email this often. 0 turns reminders off."
  type        = number
  default     = 0

  validation {
    condition     = var.reminder_minutes >= 0 && var.reminder_minutes <= 1440
    error_message = "reminder_minutes must be between 0 (off) and 1440 (daily)."
  }
}

variable "degraded_ms" {
  description = "Latency (ms) at or above which a correct response is reported as DEGRADED."
  type        = number
  default     = 1000
}

variable "metrics_enabled" {
  description = "Publish the checker's custom CloudWatch metrics. Ten custom metrics are free per account and one environment publishes seven, so only one environment should."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the function log groups."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14], var.log_retention_days)
    error_message = "log_retention_days must be one of 1, 3, 5, 7, 14 (kept short for cost)."
  }
}
