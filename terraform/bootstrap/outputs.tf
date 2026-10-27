output "state_bucket" {
  description = "Put this in terraform/backend.hcl as bucket = ..."
  value       = aws_s3_bucket.state.bucket
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.deploy.arn
}

output "plan_role_arn" {
  description = "Set as the AWS_PLAN_ROLE_ARN repository variable in GitHub (read-only: PR plans, drift)."
  value       = aws_iam_role.plan.arn
}
