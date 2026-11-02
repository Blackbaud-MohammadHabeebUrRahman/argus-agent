# Two roles so secret-reading privilege doesn't come with task-runtime privilege.
# - execution_role: used by the Fargate agent to pull the image and read secrets
#   into env vars at container start.
# - task_role: the role the running container runs under. Scoped to what Argus
#   actually needs — CloudWatch log writes, nothing else by default.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution_role" {
  name               = "${var.project}-${var.environment}-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.anthropic_api_key.arn,
      aws_secretsmanager_secret.splunk_token.arn,
      aws_secretsmanager_secret.github_token.arn,
      aws_secretsmanager_secret.teams_webhook_url.arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_read_secrets" {
  name   = "${var.project}-${var.environment}-read-secrets"
  role   = aws_iam_role.execution_role.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_iam_role" "task_role" {
  name               = "${var.project}-${var.environment}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# The task doesnt directly call AWS APIs today — the only runtime permission
# it needs is CloudWatch Logs, which Fargates execution role already handles.
# Add tighter outbound permissions here when / if the agent gets AWS tools
# (e.g. a get_cloudwatch_logs implementation).
