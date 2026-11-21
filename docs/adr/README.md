# Architecture decision records

One file per significant decision. Accepted ADRs are never rewritten: a changed
decision gets a new ADR that supersedes the old one.

| ADR | Title | Phase | Status |
| --- | --- | --- | --- |
| [0001](0001-python-for-the-ai-backend.md) | Python for the AI backend | 0 | Accepted |
| [0002](0002-vector-store.md) | pgvector locally, S3 Vectors in AWS | 0 | Accepted, revisit in Phase 4 |
| [0003](0003-local-first-model-development.md) | Local models for development, Bedrock for evaluation and production | 0 | Accepted |
| [0004](0004-chunking-strategy.md) | Chunking strategy | 1 | Accepted, revisit in Phase 3 |
| [0005](0005-storage-and-metadata-model.md) | Storage schema and document metadata model | 1 | Accepted |
| 0006 | Model provider abstraction | 2 | Planned |
| 0007 | Streaming responses over SSE | 2 | Planned |
| 0008 | Evaluation framework and quality thresholds | 3 | Planned |
| 0009 | Hybrid search and reranking | 4 | Planned |
| 0010 | MCP server boundaries | 5 | Planned |
| 0011 | LangGraph for the agent | 5 | Planned |
| 0012 | Fargate for the API, Lambda for ingestion | 6 | Planned |
| 0013 | Network design without a NAT Gateway | 6 | Planned |
| 0014 | Observability stack | 7 | Planned |
| 0015 | Guardrails and prompt-injection handling | 7 | Planned |
| 0016 | Caching strategy | 8 | Planned |
| 0017 | Model routing by cost and quality | 8 | Planned |

Template: Status · Context · Decision · Why (with rejected options) · Consequences.
