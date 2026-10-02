terraform {
  # >= 1.10 for S3 native state locking (use_lockfile) - no DynamoDB lock table to pay for.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Partial configuration: supply bucket/key/region with
  #   terraform init -backend-config=backend.hcl
  # (see backend.hcl.example and terraform/bootstrap/).
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Repo      = "lesego-rabotapi/VigilWatch"
    }
  }
}
