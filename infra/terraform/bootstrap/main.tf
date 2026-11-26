# Bootstrap: the S3 bucket that holds every stack's Terraform state.
# It was first created with local state (that file was lost: incident 0005). Since
# Phase 6c its state lives in the bucket itself (see versions.tf and imports.tf).

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      Env       = "shared"
      Owner     = var.owner
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Bucket names are global across all of AWS, so include the account ID.
  bucket_name = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}-${var.region}"
}

resource "aws_s3_bucket" "state" {
  # checkov findings accepted for a single-person state bucket (Phase 6a, reviewed):
  #checkov:skip=CKV_AWS_18:Access logging needs a second bucket; CloudTrail covers who touched state.
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles cost; versioning covers recovery.
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) is free; a KMS key adds ~$1/month for no extra control here.
  #checkov:skip=CKV2_AWS_62:No consumer for event notifications on a state bucket.
  bucket = local.bucket_name

  lifecycle {
    prevent_destroy = true # losing state means Terraform forgets what it built
  }
}

# Versioning = undo button. A corrupted state file can be rolled back.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3: free. A KMS key would cost about $1/month.
    }
  }
}

# State can contain secrets. Never public.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Old state versions pile up. Keep 30 days of history, then delete.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # Failed or abandoned multipart uploads keep their parts (and their cost) forever
  # unless something cleans them up. Added in 6c, once the state was re-imported.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Refuse any request that is not over TLS.
data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}
