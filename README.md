# KB Assistant

An AI knowledge assistant that answers questions over the AWS Well-Architected
Framework and engineering runbooks, with citations. Built the way a production
team would build it: evaluated, observable, cost-tracked and deployed with
Terraform.

**Status:** Phases 1–2b done: local RAG with citations, streaming API with tracing, and a React UI. Bedrock waiting on an AWS quota increase.

## Stack

| Layer | Choice |
|---|---|
| Web UI | React + TypeScript (Vite), Vitest |
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
make setup          # Python and web deps, git hooks, .env
make up             # Postgres + pgvector
make smoke-ollama   # free local model check
make lint test

make fetch-sources  # AWS Well-Architected PDFs into data/raw/
make ingest         # load, chunk, embed, store (skips unchanged files)
make ask Q="What are the design principles of the Reliability pillar?"

make api            # terminal 1: API on :8000
make web-dev        # terminal 2: UI on http://localhost:5173
```

No Ollama or database at hand? `make web-demo` runs the API with a scripted answer.

AWS setup (budgets, IAM, Bedrock) is in [docs/phase-0-setup.md](docs/phase-0-setup.md).
Run `make` to list every command.

## Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 0 | Setup, FinOps guardrails, least-privilege IAM | Done |
| 1 | RAG with citations, fully local | Done |
| 1.5 | Quality gate: coverage, Dependabot (SonarQube Cloud ready, switched on later) | Done |
| 2 | 2a streaming + tracing (done), 2b React UI (done), 2c Cognito sign-in + Bedrock | In progress |
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
- [Phase 2b guide](docs/phase-2b-web-ui.md)
- [Decisions (ADRs)](docs/adr/README.md) · [Investigations](docs/investigations/)
- [Architecture](docs/architecture/README.md)
- [Investigations](docs/investigations/) (how problems were diagnosed)
- [Architecture decision records](docs/adr/)
- [Build log](docs/build-log.md)
