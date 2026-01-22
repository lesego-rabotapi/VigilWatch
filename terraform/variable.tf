variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
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