output "url" {
  description = "HTTPS address of the app (add it to Cognito's callback URLs)."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}/"
}

output "cluster_name" {
  description = "ECS cluster, for aws ecs commands."
  value       = aws_ecs_cluster.main.name
}

output "service_name" {
  description = "ECS service, for aws ecs update-service."
  value       = aws_ecs_service.app.name
}

output "database_endpoint" {
  description = "Aurora writer endpoint (private subnets only)."
  value       = aws_rds_cluster.main.endpoint
}

output "database_secret_arn" {
  description = "Secrets Manager secret RDS manages for the master user."
  value       = local.db_secret_arn
}

output "log_groups" {
  description = "CloudWatch log groups of the containers."
  value       = { for k, g in aws_cloudwatch_log_group.app : k => g.name }
}
