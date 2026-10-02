# Not KMS-encrypted on purpose: CloudWatch alarms cannot publish to a topic
# encrypted with the AWS-managed aws/sns key, and a customer key costs $1/month.
resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.notification_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.notification_email
}
