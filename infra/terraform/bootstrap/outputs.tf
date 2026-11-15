output "state_bucket" {
  description = "Name of the S3 bucket holding Terraform state."
  value       = aws_s3_bucket.state.bucket
}

# `make tf-bootstrap` writes this straight into envs/dev/backend.hcl.
output "backend_hcl" {
  description = "Ready-made backend config for the environment stacks."
  value       = <<-EOT
    bucket       = "${aws_s3_bucket.state.bucket}"
    key          = "envs/dev/terraform.tfstate"
    region       = "${var.region}"
    encrypt      = true
    use_lockfile = true
  EOT
}
