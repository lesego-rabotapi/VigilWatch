variable "name_prefix" {
  description = "Prefix for resource names, normally project and environment (vigilwatch-dev)."
  type        = string
}

variable "account_id" {
  description = "AWS account ID. Part of the bucket name because S3 names are global."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "Region of the API the dashboard may call (used in the content security policy)."
  type        = string
}

variable "frontend_dir" {
  description = "Directory holding the dashboard files to upload."
  type        = string
}

variable "api_base_url" {
  description = "Base URL of the deployed API, written to config.js for the dashboard."
  type        = string
}
