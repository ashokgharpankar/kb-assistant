# ADR 0015: Network design without a NAT Gateway

**Status:** Proposed, 2026-11-26 (Phase 6c). Accepted when the dev VPC is applied.

## Context

Fargate tasks need to reach ECR (image pulls), CloudWatch Logs, Secrets Manager, Bedrock
and Cognito's JWKS endpoint. The usual answer is private subnets with a NAT Gateway.
A NAT Gateway costs about $0.045/hour (≈ $33/month) per AZ plus $0.045/GB, whether or not
anything runs.

## Decision

- A VPC with **two public subnets** (ALB requires two AZs) and **two private subnets**
  for Aurora.
- Fargate tasks run in the **public subnets with a public IP**, and their security group
  accepts traffic **only from the ALB's security group**. Nothing on the internet can open
  a connection to a task.
- **No NAT Gateway and no interface endpoints in dev.** One free **S3 gateway endpoint**
  (ECR layers are stored in S3).
- CloudFront in front of the ALB gives HTTPS on a `*.cloudfront.net` name without buying a
  domain. Cognito needs an HTTPS callback URL. The ALB accepts traffic only from the
  CloudFront origin-facing prefix list.

## Why

| Option | Fixed cost/month (approx.) | Verdict |
| --- | --- | --- |
| NAT Gateway, 2 AZs | ≈ $66 | Rejected for dev: larger than the rest of the bill |
| NAT Gateway, 1 AZ | ≈ $33 | Rejected for dev; the production choice with interface endpoints |
| Interface endpoints (ECR api+dkr, logs, secrets, bedrock-runtime, sts) | ≈ $7.30 each per AZ → $80+ | Rejected for dev |
| **Public subnet + public IP, SG locked to the ALB** | Public IPv4 ≈ $3.65 per task | **Chosen** |

- Security group rules, not subnet type, decide who can connect. A public IP with no
  inbound rule from the internet is not reachable.
- Aurora stays in private subnets with no public access; only the task SG can reach 5432.

## Consequences

- Egress from tasks is not inspected or filtered by a NAT or firewall. Acceptable for dev;
  production should use private subnets, a NAT or endpoints, and egress rules.
- Each running task uses a public IPv4 address (billed since 2024).
- This decision is stated as a dev trade-off in interviews, not as best practice.
