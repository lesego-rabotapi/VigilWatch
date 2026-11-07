variable "aws_region" {
  description = "Region for the state bucket (use the same region as the main stack)."
  type        = string
  default     = "af-south-1"
}

variable "github_repository" {
  description = "owner/repo allowed to assume the deploy role."
  type        = string
  default     = "lesego-rabotapi/VigilWatch"
}