terraform {
  # 1.15+ lets the S3 backend read `aws login` credentials directly.
  required_version = ">= 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }

  # Phase 6c: this stack's own state now lives in the bucket it manages, under
  # bootstrap/terraform.tfstate, instead of a local file that can be lost (incident 0005).
  # `make tf-bootstrap-plan` passes the bucket via -backend-config.
  #
  # Brand-new account (no bucket yet): comment this block out, `terraform apply`
  # with local state, uncomment it, then `terraform init -migrate-state`.
  backend "s3" {}
}
