locals {
  functions = {
    create_upload    = { timeout = 10, memory = 256 }
    get_sample       = { timeout = 10, memory = 256 }
    list_samples     = { timeout = 10, memory = 256 }
    validate         = { timeout = 300, memory = 1024 }
    extract_metadata = { timeout = 300, memory = 1024 }
    move_object      = { timeout = 60, memory = 512 }
  }

  # Least privilege: each function gets only what it touches.
  function_statements = {
    create_upload = [
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${local.bucket_arn}/incoming/*"] },
      { Effect = "Allow", Action = ["dynamodb:PutItem"], Resource = [local.table_arn] },
    ]
    get_sample = [
      { Effect = "Allow", Action = ["dynamodb:GetItem"], Resource = [local.table_arn] },
    ]
    list_samples = [
      { Effect = "Allow", Action = ["dynamodb:Scan", "dynamodb:Query"], Resource = [local.table_arn, "${local.table_arn}/index/*"] },
    ]
    validate = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.bucket_arn}/incoming/*"] },
    ]
    extract_metadata = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.bucket_arn}/incoming/*"] },
    ]
    move_object = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:DeleteObject"], Resource = ["${local.bucket_arn}/incoming/*"] },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${local.bucket_arn}/validated/*", "${local.bucket_arn}/quarantine/*"] },
    ]
  }
}

data "archive_file" "fn" {
  for_each    = local.functions
  type        = "zip"
  source_dir  = "${path.module}/../src/${each.key}"
  output_path = "${path.module}/build/${each.key}.zip"
  excludes    = ["__pycache__"]
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.functions
  name               = "${local.name}-${replace(each.key, "_", "-")}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "fn_logs" {
  for_each   = local.functions
  role       = aws_iam_role.fn[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions
  name     = "access"
  role     = aws_iam_role.fn[each.key].id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.function_statements[each.key]
  })
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${replace(each.key, "_", "-")}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${local.name}-${replace(each.key, "_", "-")}"
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.fn[each.key].output_path
  source_code_hash = data.archive_file.fn[each.key].output_base64sha256
  timeout          = each.value.timeout
  memory_size      = each.value.memory

  environment {
    variables = {
      TABLE_NAME             = aws_dynamodb_table.samples.name
      BUCKET_NAME            = aws_s3_bucket.data.bucket
      MAX_FILE_BYTES         = tostring(local.max_bytes)
      UPLOAD_URL_TTL_SECONDS = tostring(var.upload_url_ttl_seconds)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.fn,
    aws_iam_role_policy_attachment.fn_logs,
    aws_iam_role_policy.fn,
  ]
}
