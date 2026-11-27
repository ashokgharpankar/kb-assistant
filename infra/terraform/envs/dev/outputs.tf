output "app_role_arn" {
  description = "Put this in .env as KB_APP_ROLE_ARN."
  value       = aws_iam_role.app.arn
}

output "allowed_models" {
  description = "Models the app role may invoke."
  value       = var.bedrock_model_ids
}

output "budgets" {
  description = "Budget names and monthly limits (USD, before credits)."
  value = {
    (aws_budgets_budget.account.name) = var.monthly_budget_usd
    (aws_budgets_budget.bedrock.name) = var.bedrock_budget_usd
  }
}

output "developer_arn" {
  description = "The identity allowed to assume the app role."
  value       = local.developer_arn
}

output "cognito_user_pool_id" {
  description = "Put this in .env as KB_COGNITO_USER_POOL_ID."
  value       = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "Put this in .env as KB_COGNITO_CLIENT_ID (and in apps/web/.env.local)."
  value       = aws_cognito_user_pool_client.web.id
}

output "cognito_domain" {
  description = "The managed login (sign-in page) domain."
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "cognito_issuer" {
  description = "Issuer of the tokens; the API checks every token against it."
  value       = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

# Ready-to-paste config: `make cognito-env`
output "env_api" {
  description = "Lines for the repo's .env (the API)."
  value       = <<-EOT
    KB_AUTH_MODE=cognito
    KB_COGNITO_USER_POOL_ID=${aws_cognito_user_pool.main.id}
    KB_COGNITO_CLIENT_ID=${aws_cognito_user_pool_client.web.id}
  EOT
}

output "env_web" {
  description = "Lines for apps/web/.env.local (the UI). None of these are secrets."
  value       = <<-EOT
    VITE_COGNITO_AUTHORITY=https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}
    VITE_COGNITO_CLIENT_ID=${aws_cognito_user_pool_client.web.id}
    VITE_COGNITO_DOMAIN=https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com
  EOT
}

output "ecr_repositories" {
  description = "Image repositories CI pushes to (Phase 6c)."
  value       = { for k, r in aws_ecr_repository.app : k => r.repository_url }
}

output "github_ecr_push_role_arn" {
  description = "Set as the GitHub repository variable AWS_ECR_PUSH_ROLE_ARN (not a secret)."
  value       = aws_iam_role.github_ecr_push.arn
}

output "app" {
  description = "The AWS app stack (null while enable_app is false)."
  value = var.enable_app ? {
    url               = module.app[0].url
    cluster           = module.app[0].cluster_name
    service           = module.app[0].service_name
    database_endpoint = module.app[0].database_endpoint
    log_groups        = module.app[0].log_groups
  } : null
}

output "eval_index_bucket" {
  description = "Private bucket holding the evaluation index for CI (Phase 7c)."
  value       = aws_s3_bucket.eval_index.bucket
}

output "github_eval_role_arn" {
  description = "Role the eval workflow assumes to read the index. Set as repo variable AWS_EVAL_ROLE_ARN."
  value       = aws_iam_role.github_eval_read.arn
}
