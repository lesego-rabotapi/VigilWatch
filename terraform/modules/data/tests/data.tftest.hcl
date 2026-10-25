# req: VW-013 VW-016
# The two DynamoDB tables. The AWS provider is mocked.

mock_provider "aws" {
  mock_resource "aws_dynamodb_table" {
    defaults = { arn = "arn:aws:dynamodb:af-south-1:123456789012:table/mock" }
  }
}

variables {
  name_prefix = "vigilwatch-dev"
}

run "tables_are_named_for_the_environment_and_provisioned" {
  command = apply

  assert {
    condition     = output.endpoints_table_name == "vigilwatch-dev-endpoints" && output.history_table_name == "vigilwatch-dev-history"
    error_message = "table names must carry the environment prefix"
  }
  assert {
    condition     = aws_dynamodb_table.endpoints.billing_mode == "PROVISIONED" && aws_dynamodb_table.history.billing_mode == "PROVISIONED"
    error_message = "on-demand DynamoDB is not covered by the always-free tier"
  }
  assert {
    condition     = aws_dynamodb_table.history.ttl[0].enabled && aws_dynamodb_table.history.ttl[0].attribute_name == "expires_at"
    error_message = "history must expire via TTL (free deletes)"
  }
  assert {
    condition     = aws_dynamodb_table.history.range_key == "sk" && aws_dynamodb_table.endpoints.range_key == null
    error_message = "history is keyed by endpoint and sort key; endpoints by id only"
  }
}

run "capacity_and_protection_follow_the_inputs" {
  command = apply

  variables {
    capacity            = 3
    deletion_protection = false
  }

  assert {
    condition = (aws_dynamodb_table.endpoints.read_capacity == 3 && aws_dynamodb_table.endpoints.write_capacity == 3
    && aws_dynamodb_table.history.read_capacity == 3 && aws_dynamodb_table.history.write_capacity == 3)
    error_message = "capacity must come from the input"
  }
  assert {
    condition     = !aws_dynamodb_table.endpoints.deletion_protection_enabled && !aws_dynamodb_table.history.deletion_protection_enabled
    error_message = "deletion protection must follow the input"
  }
}

run "tables_are_protected_by_default" {
  command = apply

  assert {
    condition     = aws_dynamodb_table.endpoints.deletion_protection_enabled && aws_dynamodb_table.history.deletion_protection_enabled
    error_message = "protection is the safe default"
  }
}

run "rejects_capacity_beyond_the_free_tier" {
  command = plan
  variables {
    capacity = 13
  }
  expect_failures = [var.capacity]
}

run "rejects_zero_capacity" {
  command = plan
  variables {
    capacity = 0
  }
  expect_failures = [var.capacity]
}
