# req: VW-014 VW-016
# Private S3 bucket behind CloudFront. The AWS provider is mocked.

mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn                         = "arn:aws:s3:::mock"
      bucket_regional_domain_name = "mock.s3.af-south-1.amazonaws.com"
    }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      arn         = "arn:aws:cloudfront::123456789012:distribution/EMOCK"
      domain_name = "d111111abcdef8.cloudfront.net"
    }
  }
}

variables {
  name_prefix  = "vigilwatch-dev"
  account_id   = "123456789012"
  aws_region   = "af-south-1"
  frontend_dir = "../../../frontend"
  api_base_url = "https://abc123.execute-api.af-south-1.amazonaws.com"
}

run "bucket_is_private_and_named_for_the_environment" {
  command = apply

  assert {
    condition     = aws_s3_bucket.frontend.bucket == "vigilwatch-dev-frontend-123456789012"
    error_message = "the bucket name must carry the environment and the account"
  }
  assert {
    condition = (aws_s3_bucket_public_access_block.frontend.block_public_acls
      && aws_s3_bucket_public_access_block.frontend.block_public_policy
      && aws_s3_bucket_public_access_block.frontend.ignore_public_acls
    && aws_s3_bucket_public_access_block.frontend.restrict_public_buckets)
    error_message = "the bucket must not be public"
  }
  assert {
    condition     = jsondecode(aws_s3_bucket_policy.frontend.policy).Statement[0].Principal.Service == "cloudfront.amazonaws.com"
    error_message = "only CloudFront may read the bucket"
  }
}

run "cloudfront_is_https_only_and_cheap" {
  command = apply

  assert {
    condition     = alltrue([for o in aws_cloudfront_distribution.frontend.origin : o.origin_access_control_id == aws_cloudfront_origin_access_control.frontend.id])
    error_message = "CloudFront must reach S3 through origin access control"
  }
  assert {
    condition     = aws_cloudfront_distribution.frontend.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "viewers must be redirected to HTTPS"
  }
  assert {
    condition     = aws_cloudfront_distribution.frontend.price_class == "PriceClass_100"
    error_message = "use the cheapest CloudFront price class"
  }
  assert {
    condition     = strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "https://*.execute-api.af-south-1.amazonaws.com")
    error_message = "the content security policy must allow the API of this region and nothing wider"
  }
  assert {
    condition     = output.domain_name == "d111111abcdef8.cloudfront.net" && output.dashboard_url == "https://d111111abcdef8.cloudfront.net"
    error_message = "the dashboard address must be exported"
  }
}

run "dashboard_is_configured_with_the_deployed_api" {
  command = apply

  assert {
    condition     = strcontains(aws_s3_object.config.content, "\"https://abc123.execute-api.af-south-1.amazonaws.com\"")
    error_message = "config.js must point the dashboard at the deployed API"
  }
  assert {
    condition     = contains(keys(aws_s3_object.site), "index.html") && contains(keys(aws_s3_object.site), "app.js")
    error_message = "the dashboard files must be uploaded"
  }
  assert {
    condition     = !contains(keys(aws_s3_object.site), "package.json") && !contains(keys(aws_s3_object.site), "config.js")
    error_message = "only browser assets belong in the bucket and config.js is generated"
  }
  assert {
    condition     = aws_s3_object.healthz.key == "healthz.txt" && aws_s3_object.healthz.content_type == "text/plain"
    error_message = "the bucket must serve the health file the checker uses as a control"
  }
}

run "rejects_a_malformed_account_id" {
  command = plan
  variables {
    account_id = "not-an-account"
  }
  expect_failures = [var.account_id]
}
