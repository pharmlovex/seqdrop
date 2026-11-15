# ---------- Step Functions: the intake workflow ----------

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name}-intake-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

locals {
  workflow_lambdas = ["validate", "extract_metadata", "move_object"]
}

data "aws_iam_policy_document" "sfn" {
  statement {
    sid     = "InvokeWorkflowLambdas"
    actions = ["lambda:InvokeFunction"]
    resources = flatten([
      for f in local.workflow_lambdas : [
        aws_lambda_function.fn[f].arn,
        "${aws_lambda_function.fn[f].arn}:*",
      ]
    ])
  }

  statement {
    sid       = "UpdateRegistry"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.samples.arn]
  }

  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.events.arn]
  }

  # Required for Step Functions to deliver execution logs to CloudWatch.
  statement {
    sid = "LogDelivery"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "XRay"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "workflow"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${local.name}-intake"
  retention_in_days = var.log_retention_days
}

resource "aws_sfn_state_machine" "intake" {
  name     = "${local.name}-intake"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/statemachine/intake.asl.json", {
    validate_arn = aws_lambda_function.fn["validate"].arn
    metadata_arn = aws_lambda_function.fn["extract_metadata"].arn
    move_arn     = aws_lambda_function.fn["move_object"].arn
    table_name   = aws_dynamodb_table.samples.name
    topic_arn    = aws_sns_topic.events.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  depends_on = [aws_iam_role_policy.sfn]
}

# ---------- EventBridge: S3 "Object Created" in incoming/ -> start the workflow ----------

resource "aws_cloudwatch_event_rule" "upload" {
  name        = "${local.name}-upload-received"
  description = "Start the SeqDrop intake workflow when a file lands in incoming/"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.data.bucket] }
      object = { key = [{ prefix = "incoming/" }] }
    }
  })
}

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  name               = "${local.name}-events-start-sfn"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events" {
  name = "start-intake"
  role = aws_iam_role.events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = [aws_sfn_state_machine.intake.arn]
    }]
  })
}

resource "aws_cloudwatch_event_target" "start_intake" {
  rule     = aws_cloudwatch_event_rule.upload.name
  arn      = aws_sfn_state_machine.intake.arn
  role_arn = aws_iam_role.events.arn
}
