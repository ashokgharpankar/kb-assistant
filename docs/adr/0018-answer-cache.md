# ADR 0018: An answer cache in Postgres, exact first, semantic behind a measured threshold

**Status:** Accepted, 2026-11-27 (Phase 8a). **Amended the same day:** semantic matching is
off by default, because the measurement found no safe threshold (see Consequences).

## Context

Every question costs an embedding, a hybrid search and a model call. The model call is
>95% of the money and most of the latency (p95 time to first token 3.0 s locally, Phase 7a).
Internal knowledge assistants see the same questions again and again ("what are the six
pillars?"), often reworded. There is one knowledge base, the same for every user.

Two things make caching an LLM answer riskier than caching a web page:

- **A reworded question isn't always the same question.** "What is RTO?" and "What is RPO?"
  differ by one letter and embed very close together. A semantic hit on the wrong one is a
  confident wrong answer, worse than a slow right one.
- **Answers go stale** when the documents, the prompt, the model or retrieval settings change.

## Decision

- **Two levels, in order.** *Exact*: the question after normalising case, spacing and
  punctuation; always safe, one indexed lookup. *Semantic*: the nearest cached question by
  cosine similarity, used only at or above `KB_CACHE_SEMANTIC_THRESHOLD`. **Off by default**
  (exact-only) after the measurement below; set it only when `kb cache-check` passes for the
  embedding model in use.
- **The threshold is measured, not guessed**, like the similarity floor (incident 0006):
  `make cache-check` embeds labelled pairs in `eval/cache_pairs.jsonl` (same meaning vs
  near misses), reports the gap and fails if the chosen threshold serves any near miss.
- **Namespaces instead of invalidation.** Each entry is stored under a hash of everything
  that changes an answer: chat model, embedding space, prompt version (hash of the system
  prompt), k, floor, retrieval, reranker, answer mode, and a fingerprint of what's indexed
  (`kb_ingest_state`). Re-ingesting a document or editing the prompt starts a new namespace;
  old entries simply stop matching and expire with the TTL (`KB_CACHE_TTL_HOURS`, 7 days).
- **Postgres, not a new service.** Table `kb_answer_cache_<dims>` next to the chunks, a
  unique key for exact lookups and an HNSW index for semantic ones.
- **Order: guardrails → cache → model.** A blocked question never reaches the cache; a cached
  answer still gets the grounding check. Only answers that cost a model call are stored;
  errors never are.
- **Visible everywhere.** The answer says `cache: exact|semantic`, the similarity and what it
  saved; Prometheus counts `kb_cache_requests_total{result}`, tokens and dollars saved; the UI
  labels "From cache"; the trace has a `cache.hit` span.
- **The evaluation bypasses the cache** (`cache=False`): it measures the model, and a warm
  cache would make every second run look perfect and free.

## Why

| Option | Verdict |
|---|---|
| No cache | Rejected: pays full price and latency for every repeat |
| Exact cache only | Safe, but rewordings, the common case, miss |
| **Exact + semantic behind a measured threshold** | **Chosen**; the measurement then turned semantic off for nomic-embed-text. The mechanism stays for an embedding model that passes |
| Redis / ElastiCache (or a semantic-cache library on it) | Rejected for now: a new service to run and pay for (~$12+/month) for a single-tenant app; Postgres already has vectors |
| Bedrock prompt caching | Complementary, not a substitute: it discounts the repeated prompt prefix inside a call, it doesn't skip the call. Revisit when Bedrock is available |
| Invalidate entries on ingest | Rejected: needs to know which answers used which chunks; namespacing is simpler and can't miss a case |

## Consequences

- **Measured (27 Nov, nomic-embed-text): no safe threshold.** Negations in the same
  sentence shape score above true rewordings: "Is it safe…" vs "Is it unsafe…" 0.986, "use"
  vs "not use" 0.967, "use" vs "avoid" 0.941, while "reduce my AWS costs" vs "lower my AWS
  bill" scored 0.897. 0.97 passed on 20 pairs and failed on 24, when the negation pairs were
  added. Semantic matching is therefore off; the exact cache (27–56 ms per hit) stays on.
  Re-measure with Titan embeddings on Bedrock.
- Repeat questions return in tens of milliseconds at $0. Hit ratio and savings are on the
  dashboard, so the cache earns its place with numbers.
- If semantic matching is turned on, a hit can still be wrong for pairs nobody labelled.
  Mitigations: off by default, `make cache-check` in review when the embedding model changes, the hit is
  labelled in the UI, and `make cache-clear` empties it.
- The cache is shared by all users. Correct here; a multi-tenant system must add the tenant
  (and the user's document permissions) to the namespace, or it leaks answers across tenants.
- HNSW is filtered after the scan: with many namespaces in one table, a semantic lookup can
  miss an entry from its own namespace. Fine at this size (old namespaces expire); at scale,
  use pgvector iterative scans or a partial index per namespace.
- `kb_cache_requests_total{result="miss"}` includes questions that never could have hit
  (the first time they're asked), so the hit ratio starts low and grows with traffic.
