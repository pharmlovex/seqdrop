variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-2"
}

variable "aws_profile" {
  description = "Named AWS CLI profile (e.g. your IAM Identity Center portfolio profile). Null uses the default credential chain."
  type        = string
  default     = null
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "seqdrop"
}

variable "notification_email" {
  description = "Email to subscribe to the SNS topic. Leave empty to skip. You must confirm the subscription email AWS sends."
  type        = string
  default     = ""
}

variable "max_file_mb" {
  description = "Largest upload accepted (enforced by the presigned POST policy and re-checked in validation)."
  type        = number
  default     = 100
}

variable "upload_url_ttl_seconds" {
  description = "How long a presigned upload stays valid."
  type        = number
  default     = 900
}

variable "log_retention_days" {
  description = "CloudWatch log retention for Lambda, API and Step Functions logs."
  type        = number
  default     = 14
}
