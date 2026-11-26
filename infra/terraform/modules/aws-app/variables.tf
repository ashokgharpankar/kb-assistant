variable "name" {
  description = "Name prefix for every resource, e.g. kb-assistant-dev."
  type        = string
}

variable "region" {
  description = "AWS region (also passed to the API for Bedrock and Cognito)."
  type        = string
}

variable "vpc_cidr" {
  description = "Address range of the VPC. Subnets are /24s carved from it."
  type        = string
  default     = "10.40.0.0/16"
}

variable "api_image" {
  description = "API image, pinned by digest: <repo-url>@sha256:..."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "Pin the API image by digest (repo@sha256:...), not by tag."
  }
}

variable "web_image" {
  description = "Web image, pinned by digest: <repo-url>@sha256:..."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.web_image))
    error_message = "Pin the web image by digest (repo@sha256:...), not by tag."
  }
}

variable "desired_count" {
  description = "Running tasks. 0 parks the app: no Fargate or public IPv4 cost."
  type        = number
  default     = 1

  validation {
    condition     = var.desired_count >= 0 && var.desired_count <= 4
    error_message = "Use 0 to 4 tasks in dev."
  }
}

variable "task_cpu" {
  description = "Fargate task CPU units (both containers share it). 512 = 0.5 vCPU."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory in MiB (both containers share it)."
  type        = number
  default     = 1024
}

variable "aurora_postgres_major" {
  description = "Aurora PostgreSQL major version; the latest minor is used. Scale-to-zero needs 16.3+."
  type        = string
  default     = "16"
}

variable "aurora_max_acu" {
  description = "Upper bound of Aurora capacity units. 1 ACU is about 2 GiB of memory."
  type        = number
  default     = 2
}

variable "aurora_pause_after_seconds" {
  description = "Idle time before Aurora pauses (min capacity 0). Resume takes about 15 s."
  type        = number
  default     = 600
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the containers."
  type        = number
  default     = 14
}

variable "cognito_user_pool_id" {
  description = "Cognito user pool the API verifies tokens against."
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito app client of the web UI."
  type        = string
}

variable "cognito_domain" {
  description = "Managed login domain, https://....amazoncognito.com"
  type        = string
}

variable "bedrock_policy_arn" {
  description = "Managed policy that allows the approved Bedrock models (from the Phase 0 stack)."
  type        = string
}

variable "api_environment" {
  description = "Extra KB_* settings for the API container (non-secret)."
  type        = map(string)
  default     = {}
}
