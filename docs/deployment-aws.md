# AWS deployment

Argus deploys to AWS as a single Fargate service backed by ElastiCache
Redis, with secrets in AWS Secrets Manager and logs in CloudWatch.
The Terraform in `deploy/aws/terraform/` is intentionally minimal —
one VPC, one task, one Redis — so it fits on one page and is cheap
enough to run per-environment.

## What gets created

```
                                                 ┌─────────────────────┐
                                                 │ Anthropic API       │
                                                 │ Teams webhook       │
                                                 │ Splunk REST         │
                                                 │ GitHub API          │
                                                 └──────────▲──────────┘
                                                            │ egress via NAT
┌─────────────────────────────────────────────────────────────────────┐
│ VPC 10.40.0.0/16                                                     │
│                                                                      │
│  public subnet AZ-a  ──┐                                             │
│                        ├── NAT GW ──► IGW ──► internet               │
│  public subnet AZ-b  ──┘                                             │
│                                                                      │
│  private subnet AZ-a ─── Fargate task (argus) ───── Prometheus :9090 │
│  private subnet AZ-b ─── ElastiCache Redis cluster                   │
└─────────────────────────────────────────────────────────────────────┘
                   ▲                             ▲
                   │ reads at container start    │
                   │                             │
            CloudWatch Logs              Secrets Manager
                                          anthropic-api-key
                                          splunk-token
                                          github-token
                                          teams-webhook-url
```

## IAM: two roles, least privilege

- **execution_role** — Fargate agent uses this to pull the image and
  read Secrets Manager values into container env vars at start. Has
  the AWS-managed `AmazonECSTaskExecutionRolePolicy` plus one inline
  policy scoped to exactly the four secret ARNs this stack creates.
- **task_role** — the role the running container runs under. Has
  nothing today beyond the CloudWatch log writes that come from the
  execution role. Add scoped read permissions here when the agent
  gets an AWS-aware tool (e.g. `get_cloudwatch_logs`).

Splitting these means a compromised runtime can't rotate its own
secrets, and a bug in the entry point can't grant itself new perms.

## One-time setup

1. **S3 bucket for Terraform state** (any name, Terraform-managed):
   ```bash
   aws s3api create-bucket --bucket argus-tf-state --region us-east-1
   aws s3api put-bucket-versioning --bucket argus-tf-state \
     --versioning-configuration Status=Enabled
   ```

2. **ECR repository**:
   ```bash
   aws ecr create-repository --repository-name argus
   ```

3. **OIDC role for GitHub Actions** — a role whose trust policy allows
   the `token.actions.githubusercontent.com` provider to assume it
   from your repo. The CI workflow uses this via
   `aws-actions/configure-aws-credentials@v4` instead of long-lived
   keys. [AWS docs for the OIDC provider](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html).

4. **GitHub repo/variables and secrets**:
   - Variables: `AWS_REGION`, `ECR_REPOSITORY`, `TF_STATE_BUCKET`
   - Secrets: `AWS_DEPLOY_ROLE_ARN`, `ANTHROPIC_WORKSPACE_ID`
   - Environments (`dev`, `stg`, `prd`) with approval gates on `prd`.

## Deploy flow

Pushing a tag `v*.*.*` or triggering **deploy** manually runs the
`.github/workflows/deploy.yml` workflow, which:

1. Builds `deploy/aws/Dockerfile.prod` and pushes to ECR tagged with
   the commit SHA.
2. Runs `terraform apply` with the fresh image URI, updating the ECS
   task definition and triggering a rolling deploy.

Fargate's `deployment_minimum_healthy_percent = 100` /
`deployment_maximum_percent = 200` config means the new revision is
started before the old one is drained — zero-downtime.

## Setting the secrets

Terraform creates the Secrets Manager shells but no values. Set them
once:

```bash
aws secretsmanager put-secret-value \
  --secret-id argus/prd/anthropic-api-key-xxxx \
  --secret-string 'sk-ant-api03-...'
```

ARNs are in `terraform output -raw secret_arns`.

## Cost rough-cut (us-east-1)

| Resource | Monthly |
|---|---|
| Fargate 0.5 vCPU / 1 GiB, 1 task 24x7 | ~$18 |
| ElastiCache cache.t4g.small | ~$12 |
| NAT Gateway (hourly + per-GB) | ~$33 + egress |
| CloudWatch Logs 30-day retention | ~$1 per GB ingested |
| Secrets Manager (4 secrets) | ~$2 |

Call it ~$70/month for a dev stack if traffic is light, $100-150 for
a staging stack. Prod depends on how much the agent is called —
Anthropic tokens dwarf AWS infra at any realistic volume.

## Rollback

```bash
cd deploy/aws/terraform
terraform apply -var "image_uri=<previous-sha-image-uri>"
```

The ECS service rolls the task definition back the same way it rolled
forward.

## Multi-env

Each environment is a separate Terraform workspace or a separate
state key — the workflow uses the latter via
`-backend-config="key=argus/<env>/terraform.tfstate"`. All resources
include `${var.project}-${var.environment}` in their name, so dev and
prd stacks are visibly distinct in the console.
