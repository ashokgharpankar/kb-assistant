# ADR 0025: The evaluation as a CI gate, in two tiers

**Status:** Accepted, 2026-11-27 (Phase 7c).

## Context

`kb eval` scores retrieval, answers, refusals, guardrails and cost on 37 labelled cases, and
`eval/gate.toml` says what's acceptable. Until now it only ran on the laptop, when someone
remembered. A change to chunking, retrieval, prompts or the dataset could merge without it.

CI runners have no GPU and no index. The local model on CPU takes roughly 20–40 s per answered
question; Bedrock, which would make full runs fast and cheap, is still blocked (incident 0002).

## Decision

- **Tier 1, every relevant pull request:** `kb eval --retrieval-only`. Real Postgres + pgvector,
  the real index, the real embedding model (Ollama in a service container), no chat model.
  Measures hit rate, MRR, the similarity floor and the input screen; gated on the same
  `gate.toml` (answer metrics are skipped, not failed) and compared with `eval/baseline.json`.
  Deterministic and about 3 minutes.
- **Tier 2, nightly, on demand, or with the label `eval:full`:** the full evaluation with the
  local model on CPU. Slow, $0. After the Bedrock switch it runs against Bedrock through the
  GitHub OIDC role: a few cents per run, minutes instead of tens of minutes.
- **The index is a versioned fixture:** a plain-SQL dump of the chunks and embeddings,
  published as a GitHub release asset; its sha256 is committed in `eval/index.sha256`, and CI
  refuses a dump that doesn't match. A new index is a reviewed one-line change.
- Pinned versions: `pgvector/pgvector:pg17`, `ollama/ollama:0.40.18`. Latency is reported,
  not gated, on CPU runners.

## Why

| Option | Verdict |
|---|---|
| Full evaluation on every PR, local model on CPU | Rejected: 20+ minutes per PR, and generation on CPU isn't the production model anyway |
| Only unit tests in CI | Rejected: retrieval regressions (Phase 4: 79% → 96% hit rate came from config) pass unit tests |
| **Two tiers: deterministic retrieval on PRs, full nightly / on label** | **Chosen**: the most common regressions blocked cheaply, generation checked daily |
| Re-ingest the PDFs in CI | Rejected: minutes of embedding per run, and a different index than the baseline |
| Commit the dump to git | Rejected: large binary in history; a release asset plus a committed checksum gives the same integrity |
| Self-hosted runner with a GPU | Later, if ever: cost and maintenance for one person |

## Consequences

- A retrieval regression now fails a pull request before review.
- Generation regressions (prompt, model) are caught within a day, or before merge with
  `eval:full`.
- When the corpus or chunking changes, the index must be re-published and the checksum
  committed in the same PR (`make eval-index-publish`), otherwise CI tests the old index.
- CPU generation differs slightly from the laptop's GPU; the nightly full run compares against
  a baseline made locally, so small answer-metric drifts are expected until runs move to Bedrock.
