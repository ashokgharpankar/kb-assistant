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
