# ---------------------------------------------------------------------------
# The application stack in AWS (Phase 6c-2): VPC, ALB + CloudFront, ECS Fargate,
# Aurora Serverless v2. Off by default: with enable_app = false, plan and apply
# don't touch it, and it costs nothing.
#
# See it without creating it:   make tf-plan-app
# Create it (once Bedrock works): set enable_app = true and the image digests in
# terraform.tfvars, then make tf-plan / make tf-apply.
# ---------------------------------------------------------------------------

module "app" {
  source = "../../modules/aws-app"
  count  = var.enable_app ? 1 : 0

  name          = local.name
  region        = var.region
  api_image     = var.app_api_image
  web_image     = var.app_web_image
  desired_count = var.app_desired_count

  cognito_user_pool_id = aws_cognito_user_pool.main.id
  cognito_client_id    = aws_cognito_user_pool_client.web.id
  cognito_domain       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"

  bedrock_policy_arn = aws_iam_policy.bedrock_invoke.arn
}

locals {
  # Cognito redirects only to exact URLs: add the CloudFront address once the app exists.
  # Index the one output directly: iterating over module.app would depend on the whole
  # module, which uses the Cognito client itself, and Terraform reports a cycle.
  web_app_urls = concat(var.web_app_urls, var.enable_app ? [module.app[0].url] : [])
}
