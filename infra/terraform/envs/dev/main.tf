provider "aws" {
  region = var.region

  # FinOps foundation: every resource this stack creates gets these tags
  # automatically. Cost Explorer can then answer "what did kb-assistant cost?"
  # Nobody has to remember to tag anything.
  default_tags {
    tags = {
      Project   = var.project
      Env       = var.env
      Owner     = var.owner
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name       = "${var.project}-${var.env}"
  account_id = data.aws_caller_identity.current.account_id

  # Who may assume the app role for local testing.
  developer_arn = coalesce(var.developer_principal_arn, data.aws_caller_identity.current.arn)
}
