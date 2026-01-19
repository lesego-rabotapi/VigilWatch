resource "aws_dynamodb_table_item" "demo_endpoint" {
  table_name = aws_dynamodb_table.uptime.name
  hash_key   = "endpoint_id"
  range_key  = "timestamp"

  item = jsonencode({
    endpoint_id = { S = "demo-google" }
    timestamp   = { S = "seed" }
    status      = { S = "UP" }
    status_code = { N = "200" }
    latency_ms  = { N = "100" }
  })
}