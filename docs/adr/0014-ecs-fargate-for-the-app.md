# ADR 0014: ECS Fargate for the app, a one-off task for ingestion

**Status:** Proposed, 2026-11-26 (Phase 6c). Becomes Accepted when the dev stack is applied,
which waits for Bedrock access (incident 0002).

## Context

The API and web images are built, scanned and pushed to ECR (Phase 6a, 6c-1). The same
images run on Kubernetes locally (Phase 6b). In AWS they need a place to run. Traffic is
low and bursty: one developer and a few reviewers. Cost while idle matters more than scale.

## Decision

- Run the app on **ECS on Fargate**: one service, one task with two containers
  (web on 8080, API on 8000), behind an ALB. Desired count 1 in dev, 0 when parked.
- Run ingestion as a **one-off Fargate task** from the same API image
  (`kb-ingest`), started by `aws ecs run-task`, not as a Lambda.
- Keep the Helm chart as the Kubernetes path; it is not deployed to AWS.

## Why

| Option | Idle cost (us-east-1, approx.) | Ops work | Verdict |
| --- | --- | --- | --- |
| **ECS Fargate** | 0.25 vCPU / 0.5 GB ≈ $9/month at 24×7; $0 at desired count 0 | Task definitions, no cluster to patch | **Chosen** |
| EKS | Control plane $0.10/h ≈ $73/month before any node | Upgrades, add-ons, node groups | Rejected for dev; right when a platform team already runs EKS |
| App Runner | Simple, but closed to new customers since 2026-04-30 | Low | Rejected: AWS points to ECS Express Mode instead |
| ECS Express Mode | Same Fargate pricing; creates the ALB and scaling for you | Lowest | Noted: good for a quick start, but hides the ALB/SG wiring this project wants to own in Terraform |
| Lambda (API) | Near $0 idle | Low | Rejected: SSE streaming and 15-minute cap, cold start loads the embedder |
| Lambda (ingestion) | Near $0 | Low | Rejected: the embedding model and dependencies exceed the zip limit; a container Lambda works but duplicates the image |

- The Phase 6b work is not wasted: probes, read-only root filesystem, non-root user and
  resource requests map one-to-one to ECS task definition fields.
- One task with two containers keeps web → API on `localhost`, the same as the nginx
  proxy in the compose file. No service discovery needed.

## Consequences

- No Kubernetes in AWS. Interview framing: "I chose ECS for a one-team app; I would pick
  EKS when there is a platform team, many services, or a need for Kubernetes-native tools."
- Scaling is per task, so web and API scale together. Fine at this size; split into two
  services if their load diverges.
- The ingestion task needs the same database and Bedrock permissions as the API, through
  its own task role.
