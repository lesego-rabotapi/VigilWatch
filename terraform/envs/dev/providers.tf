terraform {
  # >= 1.10 for S3 native state locking (use_lockfile) - no DynamoDB lock table to pay for.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }

  # Partial configuration: supply bucket and region with
  #   terraform init -backend-config=backend.hcl
  # (see backend.hcl.example). Each environment has its own state key.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  # Refuse to plan or apply against any other account, whatever credentials are in the shell.
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = {
      Project     = "vigilwatch"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "lesego-rabotapi/VigilWatch"
    }
  }
}
