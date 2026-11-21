# KB Assistant

An AI knowledge assistant that answers questions over the AWS Well-Architected
Framework and engineering runbooks, with citations. Built the way a production
team would build it: evaluated, observable, cost-tracked and deployed with
Terraform.

**Status:** Phase 1 (local RAG with citations) complete. Bedrock waiting on an AWS quota increase.

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI, Pydantic v2 |
| Orchestration | LangChain (RAG), LangGraph (agent) |
| Models | Ollama locally; Amazon Bedrock (Nova, Titan Embeddings) in AWS |
| Vector store | pgvector locally; Amazon S3 Vectors in AWS |
| Agent interface | MCP server |
| Evaluation | Ragas, pytest |
| Observability | Langfuse, OpenTelemetry, CloudWatch |
| Infrastructure | Terraform, ECS Fargate (ARM64), Lambda, GitHub Actions with OIDC |

## Quick start

```bash
make setup          # Python deps, git hooks, .env
make up             # Postgres + pgvector
make smoke-ollama   # free local model check
make lint test

make fetch-sources  # AWS Well-Architected PDFs into data/raw/
make ingest         # load, chunk, embed, store (skips unchanged files)
make ask Q="What are the design principles of the Reliability pillar?"
```

AWS setup (budgets, IAM, Bedrock) is in [docs/phase-0-setup.md](docs/phase-0-setup.md).
Run `make` to list every command.

## Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 0 | Setup, FinOps guardrails, least-privilege IAM | Done |
| 1 | RAG with citations, fully local | Done |
| 1.5 | Quality gate: coverage, Dependabot (SonarQube Cloud ready, switched on later) | Done |
| 2 | Bedrock, streaming API, React UI with Cognito sign-in | Next |
| 3 | Evaluation harness | |
| 4 | Hybrid search, reranking, more sources | |
| 5 | MCP server and LangGraph agent (ADR: LangGraph vs CrewAI) | |
| 6 | Terraform, Fargate, Cognito, CI/CD; Kubernetes with Helm on kind | |
| 7 | Tracing, guardrails, evaluation gate; Prometheus + Grafana | |
| 8 | Cost per query, caching, model routing, load test | |

## Documentation

- [Phase 0 guide](docs/phase-0-setup.md)
- [Phase 1 guide](docs/phase-1-local-rag.md)
- [Phase 1.5 guide](docs/phase-1_5-quality-gate.md)
- [Phase 2a guide](docs/phase-2a-streaming-tracing.md)
- [Architecture](docs/architecture/README.md)
- [Investigations](docs/investigations/) (how problems were diagnosed)
- [Architecture decision records](docs/adr/)
- [Build log](docs/build-log.md)
