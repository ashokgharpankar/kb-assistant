# ADR 0011: Heading-path chunks, hybrid search and an optional reranker

**Status:** Accepted, 2026-11-24 (defaults confirmed by measurement, same day)

## Context

Phase 3's first evaluation run (ADR 0010) put hit rate @4 at 79%, and every miss was
the same kind of question: "What are the design principles of the X pillar?". SQL
showed the principles text existed (one chunk per pillar) but ranked below overview
chunks describing the pillar in general. Two causes: sections were cut at TOC depth 2,
so the heading "Design principles" was never part of the chunk; and a bullet list of
short phrases embeds weakly against a question, while a descriptive paragraph about
"the Security pillar" embeds close to it. The same run showed cosine similarity can't
separate answerable from off-topic questions (gap −0.013).

## Decision

1. **Sections follow the table of contents to depth 4** (`KB_TOC_DEPTH`), and each
   heading is located in the text, so sections start exactly at their heading even
   when several share a page. Sections are titled with their **heading path**:
   "Security > Design principles".
2. **Chunks are embedded under their heading path** (`KB_CHUNK_HEADERS`). The stored
   text is unchanged; only the vector sees the path. A cheap form of contextual
   retrieval: no model call at ingestion.
3. **"Resources" blocks are removed** from chunks (from "Resources"/"Related …:" to the
   next best practice), finishing investigation 0001's cleanup.
4. **Hybrid search** (`KB_RETRIEVAL_MODE=hybrid`): Postgres full-text search next to
   vector search, both ranking 20 candidates, merged with **reciprocal rank fusion**
   (score = Σ 1/(60 + rank)). The full-text vector weights the heading path above the
   body. Keyword matching ORs the question's stemmed words.
5. **Optional reranker** (`KB_RERANKER=flashrank`): a small cross-encoder
   (ms-marco-MiniLM-L-12-v2, ONNX, CPU) re-orders the candidates before the top k are
   kept. **Off by default:** measured, it made retrieval worse on this corpus (see Results).
6. The cosine floor still applies per chunk, after ranking.
7. One `Retriever` serves the pipeline, `kb search` and `kb eval`, so evaluation always
   scores the strategy users get.

## Results (24 Nov 2026)

llama3.2 (3B), k=4, floor 0.62, 34 cases, 2,711 chunks.

| Run | hit@4 | MRR | pass | false refusals | fact recall | citation validity | TTFT p50 |
|---|---|---|---|---|---|---|---|
| Phase 3 baseline | 79% | 0.72 | 85% | 4% | 73% | 88% | 1.19 s |
| Heading-path chunks, vector | 83% | 0.76 | 88% | 8% | 72% | 90% | 1.72 s |
| **+ hybrid search (default)** | **96%** | **0.79** | **94%** | 4% | 73% | 87% | 1.88 s |
| + FlashRank reranker | 88% | 0.76 | 91% | 0% | 68% | 80% | 2.37 s |
| Hybrid, after the label fix (baseline) | 100% | 0.81 | 97% | 4% | 68% | 84% | 1.88 s |

- **Hybrid on:** the exact words "design principles" in the heading path are what the
  embedding ranked too low; full-text search catches them.
- **Reranker off:** it demoted the principles lists (Security to rank 7, Operations to 5),
  lowered fact recall and citation validity, and added ~0.5 s. The MS MARCO model favours
  answer-shaped paragraphs over bullet lists. Re-test with a Bedrock rerank model (Phase 7).
- **Floor stays at 0.62:** the gap between the groups is 0.007, too narrow to tune to.
- `eval/gate.toml`: hit rate @k minimum raised to 0.90.

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| OpenSearch / a separate search engine | Another service to run and pay for; Postgres already has full-text search next to the vectors. |
| True BM25 (ParadeDB pg_search) | Not available on Amazon RDS/Aurora; `ts_rank_cd` is good enough for keyword *recall*, and RRF only uses ranks. |
| Weighted sum of scores | Cosine and text-rank scores live on different scales and drift; RRF needs no calibration. |
| LLM-written context per chunk ("contextual retrieval") | A model call per chunk at ingestion (~2,500 calls); the heading path gets much of the benefit for free. Revisit if headers aren't enough. |
| sentence-transformers cross-encoder | Pulls in PyTorch (~1 GB); FlashRank runs the same kind of model on ONNX in ~170 MB. |
| Bedrock rerank models | The right choice on AWS, once the account's Bedrock quota is fixed; the `Reranker` interface allows it. |
| Raising k instead | More tokens and cost on every question; doesn't fix ranking. |

## Consequences

- Re-ingestion needed (chunker version 3); the Phase 3 baseline was built with the old
  chunks, so the first Phase 4 run compares old and new end to end.
- More, smaller sections at depth 4; chunk count changes. Section paths appear in
  citations and in the UI, which is more useful to readers.
- The reranker, when enabled, adds ~0.5 s to time to first token (20 pairs on CPU) and a
  ~30 MB download.
- `flashrank` and `onnxruntime` are now dependencies (~170 MB installed).
- Reranker scores are a candidate relevance floor (better than cosine); evaluate in Phase 7.
