# One-time setup, applied manually with local state (see docs/RUNBOOK.md):
#   - S3 bucket for the main stack's remote state (native lockfile, no DynamoDB)
#   - GitHub Actions OIDC provider + deploy role (no long-lived AWS keys in CI)

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "vigilwatch"
      ManagedBy = "terraform-bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Fixed, not a variable: the environments always use the stack module's default prefix, so any
  # other value here would scope the deploy role to names nothing creates.
  project_name = "vigilwatch"
  state_bucket = "vigilwatch-tfstate-${data.aws_caller_identity.current.account_id}"
}

# ---- remote state --------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Keep old state versions for recovery, but not forever.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_policy" "state_tls_only" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---- GitHub Actions OIDC -------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's certificate chain itself; thumbprints are kept for older provider behaviour.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

resource "aws_iam_role" "deploy" {
  name                 = "vigilwatch-github-deploy"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        # Workflows on main, and prod's apply job, whose subject becomes environment:production.
        # A job can declare an environment from any branch, so the only trusted one is gated by a
        # required reviewer and limited to main (runbook, section 1). Dev applies run as main.
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            "repo:${var.github_repository}:ref:refs/heads/main",
            "repo:${var.github_repository}:environment:production",
          ]
        }
      }
    }]
  })
}

# Scoped to the services and name prefixes the stack uses. IAM is limited to the
# environments' function roles, and denied on this role, so the pipeline cannot escalate.
resource "aws_iam_role_policy" "deploy" {
  name = "vigilwatch-deploy"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "State"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      },
      {
        Sid    = "StackServices"
        Effect = "Allow"
        Action = [
          "dynamodb:*", "lambda:*", "apigateway:*", "events:*", "sns:*", "sqs:*",
          "logs:*", "cloudwatch:*", "cloudfront:*",
        ]
        Resource = "*"
      },
      {
        # S3 only on the dashboard bucket; never the state bucket's settings.
        Sid    = "FrontendBucketOnly"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket",
          "s3:GetBucket*", "s3:PutBucket*", "s3:DeleteBucketPolicy",
          "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration",
          "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration",
          "s3:GetAccelerateConfiguration", "s3:GetAnalyticsConfiguration",
          "s3:GetObject", "s3:GetObjectTagging", "s3:PutObject", "s3:DeleteObject",
        ]
        Resource = [
          # One dashboard bucket per environment: <project>-<env>-frontend-<account>.
          "arn:aws:s3:::${local.project_name}-*-frontend-${data.aws_caller_identity.current.account_id}",
          "arn:aws:s3:::${local.project_name}-*-frontend-${data.aws_caller_identity.current.account_id}/*",
        ]
      },
      {
        Sid    = "OwnRolesOnly"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:UpdateRole",
          "iam:TagRole", "iam:UntagRole", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
          "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
          "iam:ListInstanceProfilesForRole", "iam:UpdateAssumeRolePolicy", "iam:PassRole",
        ]
        # The function roles of each environment (<project>-<env>-<function>), never vigilwatch-*:
        # that would include this role itself.
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_name}-dev-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_name}-prod-*",
        ]
      },
      {
        # An explicit deny wins over any allow, including one added to this policy by mistake.
        Sid      = "NeverItself"
        Effect   = "Deny"
        Action   = ["iam:*"]
        Resource = [aws_iam_role.deploy.arn]
      },
      {
        Sid      = "Identity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
    ]
  })
}

# ---- Read-only role: pull request plans and drift checks ------------------

# A pull request's code has not been reviewed yet, so its plan runs with a role that can read the
# state and the stack's resources and change nothing. The weekly drift check (on main) uses it too.
resource "aws_iam_role" "plan" {
  name                 = "vigilwatch-github-plan"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            "repo:${var.github_repository}:pull_request",
            "repo:${var.github_repository}:ref:refs/heads/main",
          ]
        }
      }
    }]
  })
}

# Only Get/List/Describe actions: what `terraform plan` needs to refresh the stack. Plans run with
# -lock=false, so the state is only ever read.
resource "aws_iam_role_policy" "plan" {
  name = "vigilwatch-plan"
  role = aws_iam_role.plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadState"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetObject"]
        Resource = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      },
      {
        Sid    = "ReadStack"
        Effect = "Allow"
        Action = [
          "dynamodb:Describe*", "dynamodb:List*", "lambda:Get*", "lambda:List*", "apigateway:GET",
          "events:Describe*", "events:List*", "sns:Get*", "sns:List*", "sqs:Get*", "sqs:List*",
          "logs:Describe*", "logs:List*", "cloudwatch:Describe*", "cloudwatch:List*",
          "cloudwatch:Get*", "cloudfront:Get*", "cloudfront:List*",
        ]
        Resource = "*"
      },
      {
        Sid    = "ReadDashboardBuckets"
        Effect = "Allow"
        Action = ["s3:Get*", "s3:List*"]
        Resource = [
          "arn:aws:s3:::${local.project_name}-*-frontend-${data.aws_caller_identity.current.account_id}",
          "arn:aws:s3:::${local.project_name}-*-frontend-${data.aws_caller_identity.current.account_id}/*",
        ]
      },
      {
        Sid    = "ReadFunctionRoles"
        Effect = "Allow"
        Action = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_name}-dev-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_name}-prod-*",
        ]
      },
      {
        Sid      = "Identity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
    ]
  })
}
