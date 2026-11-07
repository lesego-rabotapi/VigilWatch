# Sign-in for the dashboard and the API (ADR 0007): a Cognito user pool on the Lite plan, free up to
# 10,000 monthly active users, with Cognito's classic hosted UI. Only the owner creates users.

resource "aws_cognito_user_pool" "users" {
  name                = "${var.name_prefix}-users"
  user_pool_tier      = "LITE"
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # No self sign-up: an invitation from the owner is the only way in.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_domain" "hosted_ui" {
  domain                = "${var.name_prefix}-${var.account_id}"
  user_pool_id          = aws_cognito_user_pool.users.id
  managed_login_version = 1 # the classic hosted UI
}

# The dashboard: a public client (a browser keeps no secret) using the authorization code flow with
# PKCE. It cannot send passwords to Cognito itself: sign-in happens on the hosted UI.
resource "aws_cognito_user_pool_client" "dashboard" {
  name         = "${var.name_prefix}-dashboard"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = var.callback_urls
  logout_urls                          = var.callback_urls
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# The smoke tests: one test user signs in with its password through Cognito's public endpoint, so
# the pipeline's smoke job needs no AWS credentials. No hosted-UI flows, no secret.
resource "aws_cognito_user_pool_client" "smoke" {
  name         = "${var.name_prefix}-smoke-tests"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"

  access_token_validity  = 15
  id_token_validity      = 15
  refresh_token_validity = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
