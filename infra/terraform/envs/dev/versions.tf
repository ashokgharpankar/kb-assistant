terraform {
  required_version = ">= 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.23"
    }
  }

  # Values come from backend.hcl (written by `make tf-bootstrap`), so the account
  # ID in the bucket name never has to be committed.
  #
  # use_lockfile = true (in backend.hcl) locks state with a small file in the same
  # bucket. The older pattern needed a DynamoDB table just for locking.
  backend "s3" {}
}
