resource "aws_s3_bucket" "frontend" {
  bucket = "${var.name_prefix}-frontend-${var.account_id}"
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Only this CloudFront distribution may read objects (Origin Access Control).
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

locals {
  # Browser assets only: no tests, package manifests or local config.
  frontend_files = setsubtract(
    setunion(fileset(var.frontend_dir, "*.{html,css,js}"), fileset(var.frontend_dir, "assets/**")),
    ["config.js", "config.example.js"]
  )
  content_types = {
    html = "text/html; charset=utf-8"
    css  = "text/css; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    png  = "image/png"
    svg  = "image/svg+xml"
    ico  = "image/x-icon"
  }
}

resource "aws_s3_object" "site" {
  for_each = local.frontend_files

  bucket        = aws_s3_bucket.frontend.id
  key           = each.value
  source        = "${var.frontend_dir}/${each.value}"
  etag          = filemd5("${var.frontend_dir}/${each.value}")
  content_type  = lookup(local.content_types, reverse(split(".", each.value))[0], "application/octet-stream")
  cache_control = endswith(each.value, ".html") ? "no-cache" : "public, max-age=300"
}

# Runtime configuration for the dashboard, generated from the deployed API.
resource "aws_s3_object" "config" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "config.js"
  content_type  = "application/javascript; charset=utf-8"
  cache_control = "no-cache"
  content       = "window.VIGILWATCH_CONFIG = ${jsonencode({ apiBase = var.api_base_url })};\n"
}

# Served by this deployment's own CloudFront. The checker probes it as a connectivity control: if it
# (or an independent site) answers, the checker can see the internet, so a failing target is really failing.
resource "aws_s3_object" "healthz" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "healthz.txt"
  content_type  = "text/plain"
  cache_control = "no-store"
  content       = "ok\n"
}

locals {
  # AWS-managed cache policy "Managed-CachingOptimized" (a fixed, global ID).
  managed_caching_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6"
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.name_prefix}-frontend"
  description                       = "VigilWatch dashboard bucket (${var.name_prefix})"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${var.name_prefix}-security-headers"

  security_headers_config {
    content_security_policy {
      # API origin is matched by wildcard to avoid a CloudFront <-> API dependency cycle.
      content_security_policy = join("; ", [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self' https://*.execute-api.${var.aws_region}.amazonaws.com",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ])
      override = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  comment             = "VigilWatch dashboard (${var.name_prefix})"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"
  is_ipv6_enabled     = true

  origin {
    origin_id                = "s3-frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id           = "s3-frontend"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    cache_policy_id            = local.managed_caching_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Default *.cloudfront.net certificate; a custom domain + ACM is out of scope.
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
