# req: VW-013 VW-016 VW-017
# The development environment as committed in terraform.tfvars. The AWS provider is mocked.

mock_provider "aws" {
  override_data {
    target = module.stack.data.aws_caller_identity.current
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
  allowed_account_ids = ["123456789012"]
  bundle_path         = "bundle.zip"
  bundle_sha256       = "47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU="
}

run "development_is_named_for_itself_and_can_be_torn_down" {
  command = apply

  assert {
    condition     = output.environment == "dev" && output.endpoints_table == "vigilwatch-dev-endpoints"
    error_message = "the development environment must be named dev"
  }
}

run "development_stays_quiet_so_both_environments_fit_the_free_tier" {
  command = apply

  assert {
    condition     = toset(output.alarm_names) == toset(["vigilwatch-dev-checker-errors", "vigilwatch-dev-checker-not-running"])
    error_message = "development keeps only the alarms that use free Lambda metrics"
  }
}

run "rejects_a_malformed_account_id" {
  command = plan
  variables {
    allowed_account_ids = ["not-an-account"]
  }
  expect_failures = [var.allowed_account_ids]
}

run "rejects_an_empty_account_list" {
  command = plan
  variables {
    allowed_account_ids = []
  }
  expect_failures = [var.allowed_account_ids]
}
