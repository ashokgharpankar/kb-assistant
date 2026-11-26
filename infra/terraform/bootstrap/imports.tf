# Phase 6c: adopt the existing state bucket into Terraform state again.
#
# The bootstrap stack's local state file was lost when a folder was overwritten
# (incident 0005). The bucket and its settings still exist in AWS, so instead of
# recreating them, these import blocks tell Terraform "this resource already exists,
# record it in state". The plan shows each one as "import"; nothing is created or
# destroyed. Once applied they're no-ops and can stay as documentation.
import {
  to = aws_s3_bucket.state
  id = local.bucket_name
}

import {
  to = aws_s3_bucket_versioning.state
  id = local.bucket_name
}

import {
  to = aws_s3_bucket_server_side_encryption_configuration.state
  id = local.bucket_name
}

import {
  to = aws_s3_bucket_public_access_block.state
  id = local.bucket_name
}

import {
  to = aws_s3_bucket_lifecycle_configuration.state
  id = local.bucket_name
}

import {
  to = aws_s3_bucket_policy.state
  id = local.bucket_name
}
