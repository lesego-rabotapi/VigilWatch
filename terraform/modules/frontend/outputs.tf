output "domain_name" {
  description = "CloudFront domain of the dashboard."
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "dashboard_url" {
  description = "Public URL of the dashboard."
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "distribution_id" {
  description = "Used by CI to invalidate the cache after a deploy."
  value       = aws_cloudfront_distribution.frontend.id
}

output "bucket" {
  description = "S3 bucket holding the dashboard files."
  value       = aws_s3_bucket.frontend.bucket
}
