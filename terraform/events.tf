resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.project_name}-uptime-checker"
  schedule_expression = "rate(${var.check_interval_minutes} minutes)"
}