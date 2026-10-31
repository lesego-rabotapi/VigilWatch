# req: VW-026
# The user pool and its two app clients (ADR 0007). The AWS provider is mocked.

mock_provider "aws" {
  mock_resource "aws_cognito_user_pool" {
    defaults = {
      id       = "af-south-1_MOCK"
      endpoint = "cognito-idp.af-south-1.amazonaws.com/af-south-1_MOCK"
    }
  }
}

variables {
  name_prefix         = "vigilwatch-prod"
  account_id          = "123456789012"
  aws_region          = "af-south-1"
  callback_urls       = ["https://d111111abcdef8.cloudfront.net"]
  deletion_protection = true
}

run "only_the_owner_creates_users_on_the_free_plan" {
  command = apply

  assert {
    condition     = aws_cognito_user_pool.users.admin_create_user_config[0].allow_admin_create_user_only
    error_message = "no self sign-up: only the owner invites users"
  }
  assert {
    condition     = aws_cognito_user_pool.users.user_pool_tier == "LITE"
    error_message = "the smallest plan, free up to 10,000 monthly active users (ADR 0007)"
  }
  assert {
    condition     = aws_cognito_user_pool.users.deletion_protection == "ACTIVE"
    error_message = "prod's pool is protected from deletion"
  }
  assert {
    condition     = aws_cognito_user_pool.users.name == "vigilwatch-prod-users"
    error_message = "named for the environment"
  }
  assert {
    condition     = aws_cognito_user_pool.users.password_policy[0].minimum_length >= 12
    error_message = "passwords of at least 12 characters"
  }
}

run "a_development_pool_can_be_torn_down" {
  command = apply

  variables {
    name_prefix         = "vigilwatch-dev"
    deletion_protection = false
  }

  assert {
    condition     = aws_cognito_user_pool.users.deletion_protection == "INACTIVE"
    error_message = "dev follows its tables: deletion protection off"
  }
}

run "the_dashboard_signs_in_with_the_code_flow_only" {
  command = apply

  assert {
    condition     = !aws_cognito_user_pool_client.dashboard.generate_secret
    error_message = "a browser cannot keep a secret: the dashboard is a public client"
  }
  assert {
    condition     = toset(aws_cognito_user_pool_client.dashboard.allowed_oauth_flows) == toset(["code"])
    error_message = "the authorization code flow (with PKCE), never the implicit flow"
  }
  assert {
    condition     = aws_cognito_user_pool_client.dashboard.allowed_oauth_flows_user_pool_client
    error_message = "OAuth must be enabled for the client"
  }
  assert {
    condition     = toset(aws_cognito_user_pool_client.dashboard.explicit_auth_flows) == toset(["ALLOW_REFRESH_TOKEN_AUTH"])
    error_message = "the dashboard cannot send passwords to Cognito directly"
  }
  assert {
    condition     = toset(aws_cognito_user_pool_client.dashboard.callback_urls) == toset(["https://d111111abcdef8.cloudfront.net"])
    error_message = "redirects go back to this environment's dashboard only"
  }
  assert {
    condition     = toset(aws_cognito_user_pool_client.dashboard.logout_urls) == toset(["https://d111111abcdef8.cloudfront.net"])
    error_message = "sign-out returns to the dashboard"
  }
  assert {
    condition     = aws_cognito_user_pool_client.dashboard.prevent_user_existence_errors == "ENABLED"
    error_message = "sign-in errors must not tell which users exist"
  }
  assert {
    condition     = aws_cognito_user_pool_client.dashboard.access_token_validity == 60 && aws_cognito_user_pool_client.dashboard.token_validity_units[0].access_token == "minutes"
    error_message = "access tokens live one hour"
  }
}

run "the_smoke_test_client_signs_in_with_a_password_and_nothing_else" {
  command = apply

  assert {
    condition     = toset(aws_cognito_user_pool_client.smoke.explicit_auth_flows) == toset(["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])
    error_message = "the smoke job gets a token for its test user with a password"
  }
  assert {
    condition     = !aws_cognito_user_pool_client.smoke.generate_secret && length(aws_cognito_user_pool_client.smoke.allowed_oauth_flows) == 0
    error_message = "no secret to store, and no hosted-UI flows"
  }
}

run "the_hosted_ui_has_this_environments_domain" {
  command = apply

  assert {
    condition     = aws_cognito_user_pool_domain.hosted_ui.domain == "vigilwatch-prod-123456789012"
    error_message = "prefixes are global in the region: environment plus account"
  }
  assert {
    condition     = output.hosted_ui_url == "https://vigilwatch-prod-123456789012.auth.af-south-1.amazoncognito.com"
    error_message = "the dashboard redirects here to sign in"
  }
  assert {
    condition     = output.issuer == "https://cognito-idp.af-south-1.amazonaws.com/af-south-1_MOCK"
    error_message = "the JWT authorizer checks tokens against this issuer"
  }
  assert {
    condition     = toset(output.audiences) == toset([aws_cognito_user_pool_client.dashboard.id, aws_cognito_user_pool_client.smoke.id])
    error_message = "tokens from either client are accepted, from no other"
  }
}

run "rejects_a_callback_that_is_neither_https_nor_localhost" {
  command = plan

  variables {
    callback_urls = ["http://evil.example"]
  }

  expect_failures = [var.callback_urls]
}
