variable "project" {
  description = "Project name, used in resource names and the Project tag."
  type        = string
  default     = "kb-assistant"
}

variable "env" {
  description = "Environment name."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Value for the Owner tag."
  type        = string
  default     = "ashok"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "alert_email" {
  description = "Where budget and anomaly alerts are sent."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly spend ceiling for the whole account, before credits."
  type        = number
  default     = 15
}

variable "bedrock_budget_usd" {
  description = "Monthly spend ceiling for Amazon Bedrock alone, before credits."
  type        = number
  default     = 5
}

variable "enable_project_tag_budget" {
  description = <<-EOT
    Create a budget filtered to the Project tag. Leave false on day one: AWS only
    lets you activate a cost allocation tag after it has appeared in billing data,
    which takes up to 24 hours after the first tagged resource exists.
  EOT
  type        = bool
  default     = false
}

variable "enable_anomaly_detection" {
  description = <<-EOT
    Create a Cost Anomaly Detection monitor. New accounts often already have a
    default "AWS services" monitor and AWS allows only one of that type, so check
    Billing > Cost Anomaly Detection in the console before setting this to true.
  EOT
  type        = bool
  default     = false
}

variable "anomaly_threshold_usd" {
  description = "Alert when an anomaly's total impact is at least this many dollars."
  type        = number
  default     = 2
}

variable "bedrock_model_ids" {
  description = "Foundation models the app may invoke. Nothing else is allowed."
  type        = list(string)
  default = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.titan-embed-text-v2:0",
  ]
}

variable "developer_principal_arn" {
  description = <<-EOT
    IAM principal allowed to assume the app role for local testing. Defaults to
    the identity running Terraform, which is right when you log in as an IAM user.
    Set it explicitly (to the IAM role ARN) if you log in through a federated role.
  EOT
  type        = string
  default     = null
}

variable "web_app_urls" {
  description = <<-EOT
    Where the web UI runs. Cognito only redirects back to these exact URLs after
    sign-in and sign-out. 5173: the Vite dev server. 8080: the web container
    (Docker Compose and kind, Phase 6). The AWS URL is added when the app is deployed.
  EOT
  type        = list(string)
  default     = ["http://localhost:5173/", "http://localhost:8080/"]
}

variable "github_repository" {
  description = <<-EOT
    The GitHub repository whose main branch may push images (Phase 6c), exactly as it
    appears in the OIDC token's "sub" claim, without the "repo:" prefix. Repositories
    with immutable subject claims (default for repos created after mid-2026) use
    owner@OWNER_ID/name@REPO_ID; older ones use owner/name. Find yours with:
      gh api repos/OWNER/NAME/actions/oidc/customization/sub
  EOT
  type        = string
  default     = "ashokgharpankar@15262181/kb-assistant@1459131240"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?$", var.github_repository))
    error_message = "Use owner/name or owner@id/name@id, without wildcards."
  }
}
