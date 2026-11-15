# ADR 0003: Local models for development, Bedrock for evaluation and production

**Status:** Accepted, 2026-11-14

## Context

Building a RAG pipeline takes many iterations. Each one that calls a paid model
costs money and needs network access and AWS credentials.

## Decision

All model access goes through a provider interface selected by `KB_LLM_PROVIDER`.
The default is `ollama`. Bedrock is used for evaluation runs, demos and deployed
environments.

## Why

- Iteration on chunking, wiring and tests is free and works offline.
- A fresh clone cannot spend money by accident (covered by a unit test).
- CI can run without AWS credentials.

## Consequences

- Local models are weaker. Answer quality must only be judged on Bedrock.
- Embedding sizes differ between providers (768 locally, 512 on Bedrock), so
  each provider needs its own vector index. Vectors are never mixed.
