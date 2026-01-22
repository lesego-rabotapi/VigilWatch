
# Force new deployment on changes
resource "null_resource" "api_deployment_trigger" {
  triggers = {
    redeployment = timestamp()
  }

  depends_on = [
    aws_api_gateway_deployment.uptime_api
  ]
}
