# Secrets Manager entries that the task reads at startup. Values are set
# out-of-band (console or `aws secretsmanager put-secret-value`) — Terraform
# only creates the resource shells, so plaintext never lives in state.

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name_prefix = "${var.project}/${var.environment}/anthropic-api-key-"
  description = "Anthropic API key for the Argus investigation agent."
}

resource "aws_secretsmanager_secret" "splunk_token" {
  name_prefix = "${var.project}/${var.environment}/splunk-token-"
  description = "Splunk HEC token for the query_splunk tool."
}

resource "aws_secretsmanager_secret" "github_token" {
  name_prefix = "${var.project}/${var.environment}/github-token-"
  description = "GitHub token for the search_github_prs tool."
}

resource "aws_secretsmanager_secret" "teams_webhook_url" {
  name_prefix = "${var.project}/${var.environment}/teams-webhook-"
  description = "Teams incoming-webhook URL for alerting."
}
