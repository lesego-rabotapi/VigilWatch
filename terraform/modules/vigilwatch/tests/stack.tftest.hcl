# req: VW-003 VW-004 VW-013 VW-015 VW-016 VW-022
# The composition of all modules for one environment: wiring between modules and isolation between
# environments. Resource-level assertions live next to each module. The AWS provider is mocked.

mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "123456789012" }
  }

  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:af-south-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:af-south-1:123456789012:function:mock"
      invoke_arn = "arn:aws:apigateway:af-south-1:lambda:path/2015-03-31/functions/arn:aws:lambda:af-south-1:123456789012:function:mock/invocations"
    }
  }
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:af-south-1:123456789012:mock"
      url = "https://sqs.af-south-1.amazonaws.com/123456789012/mock"
    }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:af-south-1:123456789012:mock" }
  }
  mock_resource "aws_dynamodb_table" {
    defaults = { arn = "arn:aws:dynamodb:af-south-1:123456789012:table/mock" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:af-south-1:123456789012:rule/mock" }
  }
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
  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      execution_arn = "arn:aws:execute-api:af-south-1:123456789012:abc123"
      api_endpoint  = "https://abc123.execute-api.af-south-1.amazonaws.com"
    }
  }
  mock_resource "aws_apigatewayv2_stage" {
    defaults = { invoke_url = "https://abc123.execute-api.af-south-1.amazonaws.com/" }
  }
}

variables {
  environment   = "dev"
  frontend_dir  = "../../../frontend"
  bundle_path   = "bundle.zip"
  bundle_sha256 = "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="
}

run "everything_is_named_for_the_environment" {
  command = apply

  assert {
    condition     = output.endpoints_table == "vigilwatch-dev-endpoints" && output.history_table == "vigilwatch-dev-history"
    error_message = "tables must be named for the environment"
  }
  assert {
    condition     = output.checker_function_name == "vigilwatch-dev-uptime-check"
    error_message = "functions must be named for the environment"
  }
  assert {
    condition     = output.environment == "dev"
    error_message = "the environment must be exported"
  }
}

run "a_second_environment_shares_no_names_with_the_first" {
  command = apply

  variables {
    environment = "prod"
  }

  assert {
    condition     = output.endpoints_table == "vigilwatch-prod-endpoints" && output.checker_function_name == "vigilwatch-prod-uptime-check"
    error_message = "production must not reuse development names, or the two would collide in one account"
  }
}

run "the_modules_are_wired_together" {
  command = apply

  assert {
    condition     = output.dashboard_url == "https://d111111abcdef8.cloudfront.net"
    error_message = "the dashboard address comes from the frontend module"
  }
  assert {
    condition     = output.api_base_url == "https://abc123.execute-api.af-south-1.amazonaws.com"
    error_message = "the API address comes from the api module with no trailing slash"
  }
  assert {
    condition     = output.sns_topic_arn == "arn:aws:sns:af-south-1:123456789012:mock"
    error_message = "the alert topic comes from the alerts module"
  }
  assert {
    condition     = output.checker_dlq_url == "https://sqs.af-south-1.amazonaws.com/123456789012/mock"
    error_message = "the dead-letter queue comes from the compute module"
  }
}

run "alarms_follow_the_environment" {
  command = apply

  variables {
    enabled_alarms  = ["checker-errors", "checker-not-running"]
    metrics_enabled = false
  }

  assert {
    condition     = toset(output.alarm_names) == toset(["vigilwatch-dev-checker-errors", "vigilwatch-dev-checker-not-running"])
    error_message = "only the requested alarms are created"
  }
}

run "refuses_an_alarm_that_needs_metrics_that_are_switched_off" {
  command = plan
  variables {
    enabled_alarms  = ["checker-blind"]
    metrics_enabled = false
  }
  expect_failures = [var.enabled_alarms]
}

run "rejects_an_environment_name_that_could_collide" {
  command = plan
  variables {
    environment = "Prod!"
  }
  expect_failures = [var.environment]
}

run "rejects_a_name_that_would_overflow_resource_name_limits" {
  command = plan
  variables {
    project_name = "a-very-long-project-name"
    environment  = "production"
  }
  expect_failures = [var.project_name]
}
