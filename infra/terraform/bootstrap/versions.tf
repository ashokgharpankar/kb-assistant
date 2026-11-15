terraform {
  # 1.15+ lets the S3 backend read `aws login` credentials directly.
  required_version = ">= 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }
}
