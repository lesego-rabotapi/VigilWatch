output "function_names" {
  description = "Function name by key (uptime_check, register_endpoint, get_checks)."
  value       = { for key, f in aws_lambda_function.fn : key => f.function_name }
}

output "function_invoke_arns" {
  description = "Invoke ARN by function key, for API Gateway integrations."
  value       = { for key, f in aws_lambda_function.fn : key => f.invoke_arn }
}

output "checker_function_name" {
  description = "Scheduled uptime checker Lambda."
  value       = aws_lambda_function.fn["uptime_check"].function_name
}

output "dlq_name" {
  description = "Dead-letter queue for failed scheduled runs."
  value       = aws_sqs_queue.checker_dlq.name
}

output "dlq_url" {
  description = "URL of the dead-letter queue."
  value       = aws_sqs_queue.checker_dlq.url
}

output "function_policies" {
  description = "The exact IAM policy document of each function, by key. Rendered at plan time so a test can enforce them."
  value       = local.function_policies
}
