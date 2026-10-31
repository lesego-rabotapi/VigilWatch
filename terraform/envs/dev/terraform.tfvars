# Development: cheap to run, safe to break, small enough that dev and prod fit one free tier together.
environment                  = "dev"
dynamodb_capacity            = 2 # two tables x 2 units here, two tables x 5 in prod: 14 of the 25 free units
dynamodb_deletion_protection = false
# Seven custom metrics are free, fourteen are not: only prod publishes them, so dev has no blind-checker alarm.
metrics_enabled    = false
enabled_alarms     = ["checker-errors", "checker-not-running"]
extra_cors_origins = ["http://localhost:3000"]
