output "api_url" {
  description = "Base URL of the HTTP API."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "bucket_name" {
  value = aws_s3_bucket.data.bucket
}

output "table_name" {
  value = aws_dynamodb_table.samples.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.intake.arn
}

output "state_machine_console_url" {
  description = "Open this for the workflow graph screenshot in your article."
  value       = "https://${var.region}.console.aws.amazon.com/states/home?region=${var.region}#/statemachines/view/${aws_sfn_state_machine.intake.arn}"
}
