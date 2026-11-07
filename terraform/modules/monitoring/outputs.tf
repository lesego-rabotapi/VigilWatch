output "alarm_names" {
  description = "Names of the alarms created in this environment."
  value       = [for alarm in aws_cloudwatch_metric_alarm.alarm : alarm.alarm_name]
}
