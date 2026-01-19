resource "aws_dynamodb_table" "uptime_table" {
  name         = "uptime_checks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "endpoint_id"
  range_key    = "timestamp"

  attribute {
    name = "endpoint_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }
}
