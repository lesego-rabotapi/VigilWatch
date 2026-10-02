variable "aws_region" {
  description = "AWS region to deploy into. af-south-1 is an opt-in region; enable it on the account first."
  type        = string
  default     = "af-south-1"
}

variable "project_name" {
  description = "Prefix for resource names."
  type        = string
  default     = "vigilwatch"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.project_name))
    error_message = "project_name must be 3-21 lowercase letters, digits or hyphens."
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

variable "notification_email" {
  description = "Email address subscribed to alerts. Empty disables the subscription. AWS sends a confirmation email first."
  type        = string
  default     = ""

  validation {
    condition     = var.notification_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "notification_email must be empty or a valid email address."
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

variable "degraded_ms" {
  description = "Latency (ms) at or above which a correct response is reported as DEGRADED."
  type        = number
  default     = 1000
}

variable "dynamodb_capacity" {
  description = "Provisioned RCU and WCU for each of the two tables. The always-free tier covers 25 of each in total."
  type        = number
  default     = 5

  validation {
    condition     = var.dynamodb_capacity >= 1 && var.dynamodb_capacity * 2 <= 25
    error_message = "dynamodb_capacity * 2 tables must stay within the 25 RCU/WCU free tier (max 12)."
  }
}

variable "dynamodb_deletion_protection" {
  description = "Protect tables from accidental deletion. Set to false before terraform destroy."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for all log groups."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14], var.log_retention_days)
    error_message = "log_retention_days must be one of 1, 3, 5, 7, 14 (kept short for cost)."
  }
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
  description = "Additional origins allowed to call the API (e.g. a local dev server)."
  type        = list(string)
  default     = ["http://localhost:3000"]
}
