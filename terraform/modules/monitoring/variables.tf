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
