resource "aws_dynamodb_table" "uptime_table" {
  name         = "uptime_checks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "target_url"
  range_key    = "timestamp"

  attribute {
    name = "target_url"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }
}
