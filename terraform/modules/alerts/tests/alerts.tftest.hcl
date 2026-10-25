# req: VW-010 VW-015
# The alert topic and its optional email subscription. The AWS provider is mocked.

mock_provider "aws" {
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:af-south-1:123456789012:mock" }
  }
}

variables {
  name_prefix = "vigilwatch-dev"
}

run "topic_carries_the_environment_prefix" {
  command = apply

  assert {
    condition     = aws_sns_topic.alerts.name == "vigilwatch-dev-alerts"
    error_message = "the topic name must carry the environment prefix"
  }
  assert {
    condition     = output.topic_arn == aws_sns_topic.alerts.arn
    error_message = "the topic ARN must be exported"
  }
  assert {
    condition     = length(aws_sns_topic_subscription.email) == 0
    error_message = "no subscription without an email address"
  }
}

run "email_subscription_when_configured" {
  command = apply

  variables {
    notification_email = "ops@example.com"
  }

  assert {
    condition     = length(aws_sns_topic_subscription.email) == 1 && aws_sns_topic_subscription.email[0].protocol == "email"
    error_message = "an email subscription must be created when an address is given"
  }
}

run "rejects_invalid_email" {
  command = plan
  variables {
    notification_email = "not-an-email"
  }
  expect_failures = [var.notification_email]
}
