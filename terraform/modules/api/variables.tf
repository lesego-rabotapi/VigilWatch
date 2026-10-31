variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "function_invoke_arns" {
  description = "Invoke ARN of the register_endpoint and get_checks functions, by key."
  type        = map(string)
}

variable "function_names" {
  description = "Name of the register_endpoint and get_checks functions, by key."
  type        = map(string)
}

variable "allowed_origins" {
  description = "Origins allowed to call the API from a browser: the dashboard, plus a local dev server if wanted."
  type        = list(string)

  validation {
    condition     = length(var.allowed_origins) > 0 && !contains(var.allowed_origins, "*")
    error_message = "allowed_origins must name at least one origin and must not contain *."
  }
}

variable "throttle_rate" {
  description = "Steady-state requests per second allowed on the public API."
  type        = number
  default     = 5

  validation {
    condition     = var.throttle_rate >= 1 && var.throttle_rate <= 10
    error_message = "throttle_rate must be between 1 and 10 requests per second (cost bound)."
  }
}

variable "throttle_burst" {
  description = "Burst requests allowed on the public API."
  type        = number
  default     = 10

  validation {
    condition     = var.throttle_burst >= 1 && var.throttle_burst <= 20
    error_message = "throttle_burst must be between 1 and 20 requests (cost bound)."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the access log."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14], var.log_retention_days)
    error_message = "log_retention_days must be one of 1, 3, 5, 7, 14 (kept short for cost)."
  }
}
