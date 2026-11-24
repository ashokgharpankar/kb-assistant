# Incident 0008: A "retrieval miss" was a stale evaluation label

**Date:** 2026-11-24 · **Phase:** 4 · **Severity:** low (one case wrong), but it skews every run
**Status:** Fixed; the other five principles cases still to audit

## Summary

`perf-principles` ("What are the design principles of the Performance Efficiency pillar?")
failed retrieval in every Phase 4 configuration: its evidence phrase, "mechanical sympathy",
was never in the top 10. Hybrid search fixed four of the six principles questions in one step,
so a case immune to every change looked suspicious.

## Evidence

One SQL query listed every chunk whose section is a "Design principles" heading:

```sql
SELECT section, page, left(replace(content, E'\n', ' '), 220) AS starts_with
FROM kb_chunks_ollama_nomic_embed_text_768
WHERE section ILIKE '%design principles%'
ORDER BY page;
```

The Performance efficiency section (pp. 829–830) exists, ranks fine, and lists principles such as
"Use managed services to reduce operational complexity" and "Deploy workloads closer to your
customers". "Mechanical sympathy", "serverless" and "experiment more often" belong to an older
edition of the framework.

## Root cause

The label was written from memory of an earlier edition, not from the indexed document. The
evaluation scored the system against a fact that wasn't in its corpus, so no retrieval change
could ever fix it.

## Resolution

- Evidence: `closer to your customers`, `reduce operational complexity`; facts: `managed services`,
  `closer to your customers`, all copied from the indexed text.
- Rule for the dataset: **evidence phrases are copied from the corpus**, never typed from memory.
  When the source document is replaced with a new edition, re-check every label.
- Follow-up: audit the facts of the other five principles cases the same way (they pass
  retrieval, but stale facts would lower fact recall).

## Also found: heading-only chunks

The Security (p. 396) and Sustainability (p. 1069) sections start with a chunk containing only
the heading and one sentence ("In the cloud, a number of principles can help you strengthen your
workload security: Design principles"). It matches the question's words almost perfectly, so it
ranks high, but it holds no answer and takes a slot in the top 4. Candidate fix for chunker v4:
merge chunks under ~50 tokens into the next one, then re-measure.

## What we learned

1. Before blaming the system for a failure no change can move, check the label.
2. Labels come from the corpus, with a page reference, and get re-checked when the corpus changes.
3. A short SQL query against the stored chunks settles "is it there?" faster than more experiments.

## Interview version

"Hybrid search fixed four of six failing questions in one step; one stayed at zero under every
configuration. Instead of tuning further, I queried the stored chunks: the expected phrase came
from an older edition of the document. The system was right and my test was wrong. Since then,
every evidence phrase is copied from the indexed text, and labels are re-checked when the
source document changes."

## Links

Phase 4 guide ("Problems found while measuring") · `eval/dataset.jsonl` · incident 0006 (the
other evaluation-design lesson)
