resource "aws_security_group" "argus_task" {
  name        = "${var.project}-${var.environment}-task"
  description = "Argus Fargate task"
  vpc_id      = aws_vpc.this.id

  # Prometheus scrape from inside the VPC only.
  ingress {
    from_port   = var.metrics_port
    to_port     = var.metrics_port
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "Prometheus metrics (VPC-local)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "all egress (Anthropic API, Teams webhook, Splunk, GitHub)"
  }
}

resource "aws_security_group" "redis" {
  name        = "${var.project}-${var.environment}-redis"
  description = "ElastiCache Redis for Argus incident/dedup store"
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.argus_task.id]
    description     = "Argus task"
  }
}
