# ADR 0001: Python for the AI backend

**Status:** Accepted, 2026-11-14

## Context

The team's strongest language is TypeScript. The AI backend could be written in
either TypeScript (LangChain.js) or Python.

## Decision

Python (FastAPI) for the API, ingestion and MCP server. TypeScript stays on the
frontend.

## Why

- LangChain, LangGraph, Ragas and most evaluation tooling ship features in Python first.
- Most GenAI job descriptions and reference architectures assume Python.
- FastAPI and Pydantic give the same typed-contract discipline as TypeScript.

## Consequences

- Two languages in one repository, so two toolchains in CI.
- API types must be shared with the frontend through the OpenAPI schema, not by importing code.
