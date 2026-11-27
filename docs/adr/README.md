# Architecture decision records

One file per significant decision. Accepted ADRs are never rewritten: a changed
decision gets a new ADR that supersedes the old one.

| ADR | Title | Phase | Status |
| --- | --- | --- | --- |
| [0001](0001-python-for-the-ai-backend.md) | Python for the AI backend | 0 | Accepted |
| [0002](0002-vector-store.md) | pgvector locally, S3 Vectors in AWS | 0 | Accepted; AWS half superseded by 0024 |
| [0003](0003-local-first-model-development.md) | Local models for development, Bedrock for evaluation and production | 0 | Accepted |
| [0004](0004-chunking-strategy.md) | Chunking strategy | 1 | Accepted, revisit in Phase 3 |
| [0005](0005-storage-and-metadata-model.md) | Storage schema and document metadata model | 1 | Accepted |
| [0006](0006-quality-gates.md) | Quality gates: SonarQube Cloud, coverage, Dependabot | 1.5 | Accepted |
| [0007](0007-model-provider-abstraction.md) | Model provider abstraction | 2 | Accepted |
| [0008](0008-streaming-responses-sse.md) | Streaming responses over SSE | 2 | Accepted |
| [0009](0009-knowledge-base-sources-and-cleaning.md) | Knowledge-base sources and ingestion cleaning | 1 | Accepted |
| [0020](0020-web-ui.md) | Web UI: Vite + React, same-origin API, model output as text | 2 | Accepted |
| [0021](0021-authentication-cognito.md) | Sign-in with Cognito; the API verifies access tokens | 2 | Accepted |
| [0022](0022-container-images-and-supply-chain.md) | Container images and supply-chain checks | 6a | Accepted |
| [0023](0023-kubernetes-with-helm-on-kind.md) | Kubernetes with a Helm chart, run locally on kind | 6b | Accepted |
| [0010](0010-evaluation.md) | Evaluation framework and quality thresholds | 3 | Accepted |
| [0011](0011-hybrid-search-reranking.md) | Heading-path chunks, hybrid search and an optional reranker | 4 | Accepted |
| [0012](0012-mcp-server.md) | An MCP server for retrieval only | 5 | Accepted |
| [0013](0013-langgraph-for-the-agent.md) | LangGraph for the agent, not CrewAI | 5 | Accepted |
| [0014](0014-ecs-fargate-for-the-app.md) | ECS Fargate for the app, a one-off task for ingestion | 6c | Proposed |
| [0015](0015-network-without-nat.md) | Network design without a NAT Gateway | 6c | Proposed |
| [0024](0024-aurora-serverless-for-aws.md) | Aurora Serverless v2 with pgvector in AWS | 6c | Proposed |
| [0016](0016-observability-metrics.md) | Prometheus metrics and Grafana dashboards; traces stay in Langfuse | 7a | Accepted |
| 0017 | Guardrails and prompt-injection handling | 7 | Planned |
| 0018 | Caching strategy | 8 | Planned |
| 0019 | Model routing by cost and quality | 8 | Planned |

Numbers are identifiers, not phase order: planned numbers are reserved, so a
decision that comes up mid-phase takes the next free number.

Template: Status · Context · Decision · Why (with rejected options) · Consequences.
