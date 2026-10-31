# Provisioned capacity on purpose: the always-free tier covers 25 RCU/WCU of
# provisioned capacity, but on-demand requests are always billed.

resource "aws_dynamodb_table" "endpoints" {
  name                        = "${var.name_prefix}-endpoints"
  billing_mode                = "PROVISIONED"
  read_capacity               = var.capacity
  write_capacity              = var.capacity
  hash_key                    = "endpoint_id"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "endpoint_id"
    type = "S"
  }

  server_side_encryption {
    enabled = false # false = AWS-owned key: encrypted at rest, no KMS charges.
  }
}

resource "aws_dynamodb_table" "history" {
  name                        = "${var.name_prefix}-history"
  billing_mode                = "PROVISIONED"
  read_capacity               = var.capacity
  write_capacity              = var.capacity
  hash_key                    = "endpoint_id"
  range_key                   = "sk"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "endpoint_id"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  # Raw checks expire after 48 h, rollups and incidents after 31 d. TTL deletes are free.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled = false
  }
}
