# ADR 0024: Aurora Serverless v2 with pgvector in AWS (supersedes the AWS half of ADR 0002)

**Status:** Proposed, 2026-11-26 (Phase 6c). Accepted when the dev database is applied.

## Context

ADR 0002 chose S3 Vectors for AWS because it is pay per use. Phase 4 changed the retrieval
design: hybrid search combines vector similarity with Postgres full-text search through
reciprocal rank fusion (ADR 0011). S3 Vectors has no keyword search. Using it would mean
a second store for full-text, two writes per chunk and two failure modes.

Aurora Serverless v2 can now scale to **0 ACUs** and pause when idle (Postgres 13.15+,
14.12+, 15.7+, 16.3+). Resume takes about 15 seconds.

## Decision

- AWS uses **Aurora PostgreSQL Serverless v2 with pgvector**, min 0 ACU, max 2 ACU,
  auto-pause after 10 minutes idle in dev.
- The schema, migrations and SQL are the same as local Postgres. No `VectorStore` code
  change.
- The master password is managed by RDS in **Secrets Manager**
  (`manage_master_user_password`), never in Terraform state or tfvars.

## Why

| Option | Idle cost | Hybrid search | Verdict |
| --- | --- | --- | --- |
| S3 Vectors | ≈ $0 | No full-text | Rejected: breaks ADR 0011 |
| OpenSearch Serverless | Minimum OCUs, ≈ $175+/month | Yes | Rejected: idle floor |
| RDS Postgres db.t4g.micro | ≈ $12/month always on | Yes | Fallback if pause latency hurts |
| **Aurora Serverless v2, 0 ACU min** | Storage only (≈ $0.10/GB-month) when paused | Yes, same SQL | **Chosen** |

## Consequences

- The first request after a pause waits ≈ 15 s. The API's DB connect timeout and the
  ALB/CloudFront timeouts must allow it; the UI shows "waking up".
- ADR 0002 stays as written; its status line now points here for the AWS choice.
- Reviewers asking "why not a vector database" get the measured answer: hybrid search
  raised hit@5 in Phase 4, and only one store gives both halves.
