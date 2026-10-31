# Production: every alarm, the metrics behind them, and tables that cannot be deleted by accident.
environment                  = "prod"
dynamodb_capacity            = 5
dynamodb_deletion_protection = true
metrics_enabled              = true
enabled_alarms               = ["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"]
extra_cors_origins           = []
