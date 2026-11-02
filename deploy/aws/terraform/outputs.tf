output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.argus.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.argus.family
}

output "redis_endpoint" {
  value       = aws_elasticache_cluster.this.cache_nodes[0].address
  description = "Private endpoint of the ElastiCache Redis cluster."
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}

output "secret_arns" {
  value = {
    anthropic_api_key = aws_secretsmanager_secret.anthropic_api_key.arn
    splunk_token      = aws_secretsmanager_secret.splunk_token.arn
    github_token      = aws_secretsmanager_secret.github_token.arn
    teams_webhook_url = aws_secretsmanager_secret.teams_webhook_url.arn
  }
  description = "Pass each ARN to `aws secretsmanager put-secret-value` to set the value."
  sensitive   = true
}
