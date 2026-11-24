# ADR 0010: Evaluation framework and quality thresholds

**Status:** Accepted, 2026-11-23

## Context

Until now, quality was judged by reading answers. That doesn't scale and can't
catch regressions: a chunking change can improve one question and quietly break
five others. Phases 4 to 8 all change retrieval, models or prompts, and each
change needs a before/after number. The similarity floor (0.62) was set from a
handful of manual searches and needs a measured basis.

## Decision

1. **A versioned evaluation set** in the repo, `eval/dataset.jsonl`: answerable
   questions (spread over every pillar, plus paraphrases), out-of-scope questions
   (including a near-domain one about another cloud) and prompt-injection attempts.
   Labels are **evidence phrases**, not chunk IDs, so they survive re-chunking.
2. **Retrieval is scored separately from generation.** For each question we
   search 10 ranks deep with no floor and record where the first chunk containing
   evidence appears: **hit rate @k** (is it among the k chunks the model sees?)
   and **MRR**. Then the real pipeline answers, and we score the answer.
3. **Deterministic metrics first:** citation validity (markers that point to a
   real source; `[REL11-BP01]` counts as invalid), share of answers with a valid
   citation, fact recall (expected facts mentioned, any phrasing), false refusals,
   correct refusals, injection resistance (refused and nothing forbidden in the
   answer), tokens, cost, time-to-first-token p50/p95.
4. **The floor is calibrated from data:** each question's best score; the report
   sweeps floors from 0.30 to 0.90 and recommends the middle of the gap between
   the lowest answerable and the highest off-topic score, when there is a gap.
5. **LLM-as-judge is optional** (`--judge`): a second model scores groundedness 1–5
   from the sources, with JSON output and a fixed rubric. Reported, never gated:
   a small local judge is noisy.
6. **A gate and a baseline.** `eval/gate.toml` sets minimums; `eval/baseline.json`
   (committed) is the reference run. `kb eval` exits 1 when a gated metric misses
   or a score drops more than 0.05 below the baseline (cost and latency: more
   than 25% worse). Every run is saved under `eval/results/` (git-ignored).
7. **Local for now.** The run needs Postgres and a model, so CI only validates the
   dataset. Phase 7 runs the gate in CI against Bedrock.

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| RAGAS / DeepEval as the core | Mostly LLM-judged metrics: slower, cost money on hosted models, and harder to explain when a score moves. Worth adding later beside the deterministic ones, not instead. |
| Chunk-ID labels | Every chunking change (Phase 4) would invalidate the labels. |
| Judge-only scoring | Judges favour fluent answers and vary between runs; deterministic checks catch the concrete failures we've seen (bad citations, wrong refusals). |
| Gating citation validity now | llama3.2 (3B) fails it by design; gate it once the production model is measured. |
| Langfuse datasets | Good for team review; adds a moving part before the metrics are settled. Revisit in Phase 7. |

## Consequences

- Labels can be wrong. The first runs are partly a review of the dataset: a
  failing case is either a system problem or a label problem, and both get fixed.
- 34 cases give coarse percentages (one case ≈ 4% of the answerable ones). Grow the
  set when a phase targets a specific weakness; every real bug becomes a case.
- Runs are cheap locally (Ollama) but a judge run doubles model calls.
- Evaluation traffic is not traced in Langfuse, so traces stay real-user only.
