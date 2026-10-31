variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "capacity" {
  description = "Provisioned RCU and WCU for each of the two tables. The always-free tier covers 25 of each per account, shared by every environment."
  type        = number
  default     = 5

  validation {
    condition     = var.capacity >= 1 && var.capacity * 2 <= 25
    error_message = "capacity * 2 tables must stay within the 25 RCU/WCU free tier (max 12)."
  }
}

variable "deletion_protection" {
  description = "Protect tables from accidental deletion. Turn off before destroying a development environment."
  type        = bool
  default     = true
}
