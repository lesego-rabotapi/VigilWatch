variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "notification_email" {
  description = "Address subscribed to alerts. Empty disables the subscription. AWS sends a confirmation email first."
  type        = string
  default     = ""

  validation {
    condition     = var.notification_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.notification_email))
    error_message = "notification_email must be empty or a valid email address."
  }
}
