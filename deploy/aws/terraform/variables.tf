variable "project" {
  description = "Project tag applied to every resource."
  type        = string
  default     = "argus"
}

variable "environment" {
  description = "Environment tag: dev | stg | prd."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "image_uri" {
  description = "Fully-qualified ECR image URI the task definition pulls."
  type        = string
}

variable "cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "memory_mb" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Number of Argus tasks to run. One is almost always enough; the state lives in Redis."
  type        = number
  default     = 1
}

variable "redis_node_type" {
  description = "ElastiCache node type for the incident/dedup store."
  type        = string
  default     = "cache.t4g.small"
}

variable "metrics_port" {
  description = "Prometheus metrics port the task exposes."
  type        = number
  default     = 9090
}

variable "anthropic_workspace_id" {
  description = "Optional ANTHROPIC_WORKSPACE_ID when the API key is user-scoped."
  type        = string
  default     = ""
  sensitive   = true
}

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.40.0.0/16"
}
