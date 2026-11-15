# KB Assistant

An AI knowledge assistant that answers questions over the AWS Well-Architected
Framework and engineering runbooks, with citations. Built the way a production
team would build it: evaluated, observable, cost-tracked and deployed with
Terraform.

**Status:** Phase 0 (setup and guardrails) complete.

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
```

AWS setup (budgets, IAM, Bedrock) is in [docs/phase-0-setup.md](docs/phase-0-setup.md).
Run `make` to list every command.

## Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 0 | Setup, FinOps guardrails, least-privilege IAM | Done |
| 1 | Naive RAG, fully local | Next |
| 2 | Bedrock, streaming API and UI | |
| 3 | Evaluation harness | |
| 4 | Hybrid search, reranking, citations, more sources | |
| 5 | MCP server and LangGraph agent | |
| 6 | Terraform deploy to Fargate, CI/CD | |
| 7 | Tracing, guardrails, evaluation gate in CI | |
| 8 | Cost per query, caching, model routing, load test | |

## Documentation

- [Phase 0 guide](docs/phase-0-setup.md)
- [Architecture decision records](docs/adr/)
- [Build log](docs/build-log.md)
