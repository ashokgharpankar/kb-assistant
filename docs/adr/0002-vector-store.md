# ADR 0002: pgvector locally, S3 Vectors in AWS

**Status:** Accepted, 2026-11-14. The AWS half (S3 Vectors) is superseded by
[ADR 0024](0024-aurora-serverless-for-aws.md) (Phase 6c): hybrid search needs full-text search.

## Context

RAG needs a vector store. On AWS the common options are OpenSearch Serverless,
Aurora/RDS with pgvector, and S3 Vectors.

## Decision

- Local development: Postgres with pgvector in Docker.
- AWS: Amazon S3 Vectors.
- Code depends on a `VectorStore` interface, not on either product.

## Why

- OpenSearch Serverless bills a minimum amount of compute whether or not it is queried.
  For a low-traffic assistant that floor would dominate the bill.
- S3 Vectors is pay per use: storage, writes and queries. Idle cost is close to zero.
- pgvector gives SQL, metadata filtering and full-text search in one local container.

## Consequences

- S3 Vectors has no keyword search. Hybrid search in AWS will need a second
  component or a different store. Phase 4 measures whether that matters for our data.
- Two implementations of one interface to keep in step. Contract tests cover both.
