output "topic_arn" {
  description = "Alert topic: endpoint DOWN and RECOVERED messages and monitor health alarms."
  value       = aws_sns_topic.alerts.arn
}
