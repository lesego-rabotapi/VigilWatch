output "user_pool_id" {
  description = "The user pool; users are created in it with aws cognito-idp admin-create-user."
  value       = aws_cognito_user_pool.users.id
}

output "issuer" {
  description = "Token issuer the JWT authorizer trusts."
  value       = "https://${aws_cognito_user_pool.users.endpoint}"
}

output "audiences" {
  description = "Client ids whose tokens the API accepts."
  value       = [aws_cognito_user_pool_client.dashboard.id, aws_cognito_user_pool_client.smoke.id]
}

output "dashboard_client_id" {
  description = "The dashboard's public client."
  value       = aws_cognito_user_pool_client.dashboard.id
}

output "smoke_client_id" {
  description = "The smoke tests' password client."
  value       = aws_cognito_user_pool_client.smoke.id
}

output "hosted_ui_url" {
  description = "Where the dashboard sends the browser to sign in."
  value       = "https://${aws_cognito_user_pool_domain.hosted_ui.domain}.auth.${var.aws_region}.amazoncognito.com"
}
