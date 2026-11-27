# ---------------------------------------------------------------------------
# The evaluation index for CI (Phase 7c): a private S3 bucket and a read-only role.
#
# The index holds chunks of the AWS documents (their text) plus embeddings. The
# repository is public, so the index must not be: a public release asset would
# redistribute the documents' text. CI reads it through GitHub OIDC, like the ECR push.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "eval_index" {
  #checkov:skip=CKV_AWS_18:Access logging needs a second bucket; CloudTrail covers reads of one object.
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles cost for a file we can regenerate.
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) is free; a KMS key adds ~$1/month for public-source text.
  #checkov:skip=CKV2_AWS_62:No consumer for event notifications.
  bucket        = "${local.name}-eval-index-${local.account_id}"
  force_destroy = true # regenerable: make eval-index-publish
}

resource "aws_s3_bucket_ownership_controls" "eval_index" {
  bucket = aws_s3_bucket.eval_index.id
  rule {
    object_ownership = "BucketOwnerEnforced" # no ACLs
  }
}

resource "aws_s3_bucket_public_access_block" "eval_index" {
  bucket                  = aws_s3_bucket.eval_index.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "eval_index" {
  bucket = aws_s3_bucket.eval_index.id
  versioning_configuration {
    status = "Enabled" # an overwritten index can be recovered
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "eval_index" {
  bucket = aws_s3_bucket.eval_index.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "eval_index" {
  bucket = aws_s3_bucket.eval_index.id
  rule {
    id     = "expire-old-index-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "eval_index_tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.eval_index.arn, "${aws_s3_bucket.eval_index.arn}/*"]
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

resource "aws_s3_bucket_policy" "eval_index" {
  bucket = aws_s3_bucket.eval_index.id
  policy = data.aws_iam_policy_document.eval_index_tls_only.json
}

# --- Read-only role for the eval workflow -------------------------------------

data "aws_iam_policy_document" "github_eval_trust" {
  statement {
    sid     = "GitHubActionsPullRequestsAndMain"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Pull requests in this repository (tier 1) and runs on main (nightly, Run workflow).
    # Pull requests from forks get no OIDC token from GitHub, so they can't assume it.
    # The role can only read one object, so even a malicious PR in this repo gets nothing
    # beyond the index CI already uses.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:pull_request",
        "repo:${var.github_repository}:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "github_eval_read" {
  name                 = "${local.name}-github-eval-read"
  description          = "Assumed by the eval workflow to download the evaluation index."
  assume_role_policy   = data.aws_iam_policy_document.github_eval_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "eval_read" {
  statement {
    sid       = "ReadTheIndexOnly"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.eval_index.arn}/kb-index.sql.gz"]
  }
}

resource "aws_iam_role_policy" "github_eval_read" {
  name   = "eval-index-read"
  role   = aws_iam_role.github_eval_read.id
  policy = data.aws_iam_policy_document.eval_read.json
}
