variable "aws_region" {
  description = "Region to deploy all resources"
  type        = string
  default     = "af-south-1"
}

variable "project_name" {
  description = "Project name used as a prefix for resources"
  type        = string
  default     = "vigilwatch"
}

variable "check_interval_minutes" {
  description = "Interval in minutes between uptime checks"
  type        = number
  default     = 5
}

variable "notification_email" {
  description = "Email address to receive uptime notifications"
  type        = string
  default     = ""
}