resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.project}/${var.environment}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "this" {
  name = "${var.project}-${var.environment}"
}

resource "aws_ecs_task_definition" "argus" {
  family                   = "${var.project}-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory_mb
  execution_role_arn       = aws_iam_role.execution_role.arn
  task_role_arn            = aws_iam_role.task_role.arn

  container_definitions = jsonencode([
    {
      name      = "argus"
      image     = var.image_uri
      essential = true
      portMappings = [
        {
          containerPort = var.metrics_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "ARGUS_ENVIRONMENT", value = var.environment },
        { name = "ARGUS_LOG_LEVEL", value = "INFO" },
        {
          name  = "ARGUS_REDIS_URL",
          value = "redis://${aws_elasticache_cluster.this.cache_nodes[0].address}:6379/1"
        },
        { name = "ANTHROPIC_WORKSPACE_ID", value = var.anthropic_workspace_id },
      ]
      secrets = [
        {
          name      = "ANTHROPIC_API_KEY",
          valueFrom = aws_secretsmanager_secret.anthropic_api_key.arn
        },
        {
          name      = "ARGUS_SPLUNK_TOKEN",
          valueFrom = aws_secretsmanager_secret.splunk_token.arn
        },
        {
          name      = "ARGUS_GITHUB_TOKEN",
          valueFrom = aws_secretsmanager_secret.github_token.arn
        },
        {
          name      = "ARGUS_TEAMS_WEBHOOK_URL",
          valueFrom = aws_secretsmanager_secret.teams_webhook_url.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "argus"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "argus" {
  name                               = "${var.project}-${var.environment}"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.argus.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.argus_task.id]
    assign_public_ip = false
  }
}
