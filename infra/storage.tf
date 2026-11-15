data "aws_caller_identity" "current" {}

locals {
  name        = var.project
  bucket_name = "${var.project}-${data.aws_caller_identity.current.account_id}-${var.region}"
  max_bytes   = var.max_file_mb * 1024 * 1024
  bucket_arn  = aws_s3_bucket.data.arn
  table_arn   = aws_dynamodb_table.samples.arn
}

# ---------- S3: one bucket, three prefixes (incoming/ validated/ quarantine/) ----------

resource "aws_s3_bucket" "data" {
  bucket        = local.bucket_name
  force_destroy = true # demo project: lets `terraform destroy` clean up uploaded files
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # Anything left in incoming/ never finished processing.
  rule {
    id     = "expire-stale-incoming"
    status = "Enabled"
    filter {
      prefix = "incoming/"
    }
    expiration {
      days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  rule {
    id     = "expire-quarantine"
    status = "Enabled"
    filter {
      prefix = "quarantine/"
    }
    expiration {
      days = 30
    }
  }
}

# Browser uploads with the presigned POST need CORS.
resource "aws_s3_bucket_cors_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = ["*"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# Send object events to EventBridge (the rule in events.tf filters to incoming/).
resource "aws_s3_bucket_notification" "data" {
  bucket      = aws_s3_bucket.data.id
  eventbridge = true
}

# ---------- DynamoDB: the sample registry ----------

resource "aws_dynamodb_table" "samples" {
  name         = "${local.name}-samples"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sample_id"

  attribute {
    name = "sample_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by_status"
    projection_type = "ALL"

    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

# ---------- SNS: notifications ----------

resource "aws_sns_topic" "events" {
  name = "${local.name}-events"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.events.arn
  protocol  = "email"
  endpoint  = var.notification_email
}
