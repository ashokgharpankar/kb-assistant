# KB Assistant

An AI knowledge assistant that answers questions over the AWS Well-Architected
Framework and engineering runbooks, with citations. Built the way a production
team would build it: evaluated, observable, cost-tracked and deployed with
Terraform.

**Status:** Phases 0–7 done: local RAG with citations, streaming API with tracing, React UI with Cognito sign-in, evaluation harness with a CI gate, hybrid search, MCP server and LangGraph agent, containers, Helm on kind, Terraform for AWS (ECS Fargate, Aurora Serverless, CloudFront), Prometheus and Grafana with SLO alerts, guardrails. Phase 8 (cost and caching) in progress. The AWS deploy waits on a Bedrock quota increase.

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

make api            # terminal 1: API on :8000 (needs Cognito settings, see Phase 2c)
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
| 1.5 | Quality gate: coverage, Dependabot | Done |
| 2 | Streaming + tracing, React UI, Cognito sign-in | Done (Bedrock switch waiting on quota) |
| 3 | Evaluation harness: golden set, floor calibration, baseline and gate | Done |
| 4 | Heading-path chunks, hybrid search, reranking | Done |
| 5 | MCP server and LangGraph agent | Done |
| 6 | Containers and supply chain, Helm on kind, Terraform: ECR via GitHub OIDC, ECS Fargate, Aurora | Done (first apply after Bedrock) |
| 7 | Prometheus + Grafana with SLO burn-rate alerts, guardrails, evaluation in CI | Done |
| 8 | Cost per question, answer cache (8a); model routing and spend cap (8b) | In progress |

## Documentation

- [Phase 0 guide](docs/phase-0-setup.md)
- [Phase 1 guide](docs/phase-1-local-rag.md)
- [Phase 1.5 guide](docs/phase-1_5-quality-gate.md)
- [Phase 2a guide](docs/phase-2a-streaming-tracing.md)
- [Phase 2b guide](docs/phase-2b-web-ui.md)
- [Phase 2c guide](docs/phase-2c-cognito.md)
- [Phase 3 guide](docs/phase-3-evaluation.md)
- [Phase 4 guide](docs/phase-4-retrieval.md)
- [Phase 5a guide](docs/phase-5a-mcp.md)
- [Phase 5b guide](docs/phase-5b-agent.md)
- [Phase 6a guide](docs/phase-6a-containers.md)
- [Phase 6b guide](docs/phase-6b-kubernetes.md)
- [Phase 6c guide](docs/phase-6c-aws.md)
- [Phase 7a guide](docs/phase-7a-observability.md)
- [Phase 7b guide](docs/phase-7b-guardrails.md)
- [Phase 7c guide](docs/phase-7c-eval-in-ci.md)
- [Phase 8a guide](docs/phase-8a-cost-cache.md)
- [Decisions (ADRs)](docs/adr/README.md) · [Investigations and incidents](docs/investigations/README.md)
- [Architecture](docs/architecture/README.md)
- [Architecture decision records](docs/adr/)
- [Build log](docs/build-log.md)
