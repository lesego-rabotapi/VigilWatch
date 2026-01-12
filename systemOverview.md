1. User adds endpoint to monitor
2. Backend schedules periodic checks
3. Backend performs HTTP request
4. Latency & status stored in DB
5. Incident created if thresholds exceeded
6. CloudWatch metric emitted
7. Dashboard updates

# End-to-end workflow
EventBridge triggers the uptime-check Lambda every 5 minutes
Lambda sends HTTP requests to monitored URLs
Response status and latency are recorded
Results are written to DynamoDB
Logs are sent to CloudWatch Logs
CloudWatch Alarms detect failures
SNS sends email alerts on downtime
Frontend requests metrics via API Gateway
API Gateway invokes stats Lambda
Lambda retrieves metrics from DynamoDB
Dashboard displays uptime status