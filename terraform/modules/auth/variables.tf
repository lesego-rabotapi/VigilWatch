variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "account_id" {
  description = "AWS account ID. Part of the hosted UI's domain prefix, which must be unique in the region."
  type        = string
}

variable "aws_region" {
  description = "Region of the user pool, for the hosted UI's address."
  type        = string
}

variable "callback_urls" {
  description = "Where Cognito may send the browser back after sign-in and sign-out: the dashboard, plus local development origins in dev."
  type        = list(string)

  validation {
    condition     = length(var.callback_urls) > 0 && alltrue([for u in var.callback_urls : can(regex("^(https://[^/]+|http://localhost(:[0-9]+)?)$", u))])
    error_message = "callback_urls must be https origins, or http://localhost with an optional port."
  }
}

variable "deletion_protection" {
  description = "Protect the user pool from deletion. Off in dev, which can be torn down."
  type        = bool
}
