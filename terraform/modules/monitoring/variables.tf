variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "topic_arn" {
  description = "Alert topic every alarm notifies."
  type        = string
}

variable "checker_function" {
  description = "Name of the scheduled checker function."
  type        = string
}

variable "dead_letter_queue" {
  description = "Name of the checker's dead-letter queue."
  type        = string
}

variable "api_id" {
  description = "ID of the HTTP API."
  type        = string
}

variable "enabled_alarms" {
  description = "Which alarms to create. Ten alarms are free per account across all environments."
  type        = list(string)

  validation {
    condition     = alltrue([for a in var.enabled_alarms : contains(["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"], a)])
    error_message = "enabled_alarms may only contain checker-errors, checker-not-running, checker-dlq, checker-blind and api-5xx."
  }

  validation {
    condition     = length(distinct(var.enabled_alarms)) == length(var.enabled_alarms)
    error_message = "enabled_alarms must not list an alarm twice."
  }
}

variable "aws_region" {
  description = "Region the dashboard reads its metrics from."
  type        = string
}

variable "function_names" {
  description = "Function name by key (uptime_check, register_endpoint, get_checks)."
  type        = map(string)

  validation {
    condition     = contains(keys(var.function_names), "uptime_check")
    error_message = "function_names must include the checker, uptime_check."
  }
}

variable "tables" {
  description = "Names of this environment's DynamoDB tables, shown on the dashboard."
  type        = list(string)
}

variable "api_access_log_group" {
  description = "Log group of the HTTP API's access log, read by the saved queries."
  type        = string
}

variable "metrics_enabled" {
  description = "Whether the checker publishes its custom metrics here; the dashboard shows ControlProbeFailed only then."
  type        = bool
}
