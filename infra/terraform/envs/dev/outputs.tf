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
