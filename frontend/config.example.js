// Local development only. Copy to config.js and set your API URL:
//   terraform -chdir=terraform/envs/dev output -raw api_base_url
// In AWS, Terraform generates config.js in the bucket (terraform/modules/frontend).
// Without "auth" sign-in is off, as on the local stack (scripts/local_api.py); against a deployed
// API, add it from the outputs hosted_ui_url and dashboard_client_id, and serve this page from an
// origin listed in extra_cors_origins (the sign-in callback goes back to it).
window.VIGILWATCH_CONFIG = {
  apiBase: "https://<api-id>.execute-api.af-south-1.amazonaws.com",
  // auth: { hostedUiUrl: "https://<prefix>.auth.af-south-1.amazoncognito.com", clientId: "<id>" },
};
