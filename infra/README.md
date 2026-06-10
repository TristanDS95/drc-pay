# infra

Infrastructure as code — **Terraform** — for AWS **Cape Town (af-south-1)**.

To provision (to build): VPC, ECS **Fargate** services (api, webhooks — App Runner is
not available in af-south-1), **RDS Postgres** (the ledger), **ElastiCache Redis**
(sessions / rate limits), **Secrets Manager**, an ALB, and CloudWatch.

**Rules:**
- Separate **sandbox** and **production** accounts / workspaces; never share creds.
- No secrets in state committed to git (remote state + git-ignored `*.tfvars`).
- Least-privilege IAM per service.
