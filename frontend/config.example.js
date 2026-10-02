// Local development only. Copy to config.js and set your API URL:
//   terraform -chdir=terraform output -raw api_base_url
// In AWS, Terraform generates config.js in the bucket (terraform/frontend.tf).
window.VIGILWATCH_CONFIG = {
  apiBase: "https://<api-id>.execute-api.af-south-1.amazonaws.com",
};
