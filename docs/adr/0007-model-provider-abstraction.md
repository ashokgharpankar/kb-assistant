# ADR 0007: Model provider abstraction

**Status:** Accepted, 2026-11-21

## Context

The same pipeline must run on local models (Ollama) and on Amazon Bedrock, and
later on other Bedrock models (Claude once the account is on the Paid plan).
Bedrock is currently unavailable on this account (applied quota 0), so
development continues locally.

## Decision

- One module, `providers.py`, is the only code that knows which provider is in
  use. It returns LangChain interfaces: `Embeddings` and `BaseChatModel`.
- `KB_LLM_PROVIDER` selects `ollama` or `bedrock`. Model ids are settings.
- Each embedding model gets its own **embedding space** (table), derived from
  provider, model and dimensions (ADR 0005).
- Token usage is read from LangChain's provider-neutral `usage_metadata`, and
  cost comes from one price table (`pricing.py`).

## Why

- Models change every few months; switching should be a setting, not a rewrite.
- LangChain's chat and embedding interfaces already normalise streaming and
  token usage across providers, which is exactly the part we'd otherwise write.
- Keeping provider logic in one file keeps the blast radius of a library change small.

**Rejected:** a custom HTTP client per provider (duplicates LangChain's work);
LiteLLM proxy (another service to run; worth revisiting for multi-provider routing in Phase 8).

## Consequences

- Provider-specific features (Bedrock Guardrails, prompt caching) need explicit
  handling in `providers.py` when we adopt them.
- Local and Bedrock answers differ in quality; evaluation (Phase 3) must name the provider it measured.
