# ADR 0009: Knowledge-base sources and ingestion cleaning

**Status:** Accepted, 2026-11-21. Evidence: [investigation 0001](../investigations/0001-retrieval-quality.md).

## Context

A misleading citation ("implement shuffle-sharding [3]", sourced from a list of
conference talk titles) led to a measured investigation of the ingested data.
It found ligature characters in 88.5% of chunks, running page headers, table-of-
contents lines and reference lists indexed as guidance, and heavy overlap
between the framework PDF and the pillar PDFs.

## Decision

**Sources.** Index only the AWS Well-Architected **framework** PDF. Drop the
separate pillar PDFs. One authoritative source per topic.

**Cleaning at ingestion,** in the loader and chunker:

| Problem | Fix |
|---|---|
| Ligatures ("ﬁ") | PyMuPDF text flags without `TEXT_PRESERVE_LIGATURES`, plus Unicode NFKC normalisation |
| Running headers/footers | Remove lines found at the top or bottom of at least half the pages |
| Table-of-contents entries | Drop dot-leader lines; skip ToC, revisions and notices sections |
| Reference lists | Drop chunks that are mostly bullets and contain "Related documents/videos", "re:Invent" |

`CHUNKER_VERSION` moves to 2, so every document is re-processed.

**Housekeeping:** `kb remove <id>` and `kb ingest --prune` keep the index in step
with the source folder.

## Why

- The framework PDF covers all six pillars; the separate PDFs cover three, and
  42.5% of a 200-chunk sample from the Reliability pillar had a >0.90-similarity
  counterpart in the framework. Duplicates fill top-k slots with the same advice,
  cost embedding money and blur which source is authoritative.
- Fixing data at ingestion fixes it for every consumer: vector search now, keyword
  search in Phase 4, and anything that quotes chunks to users.
- Cleaning rules are conservative: headers are only detected at page edges, and
  reference lists need both a marker phrase and a mostly-bullet layout, so normal
  guidance written as bullets is kept.

**Rejected:** filtering near-duplicates at query time (keeps paying for duplicate
embeddings and storage; more moving parts); fixing answers with prompt
instructions ("ignore reference lists"), which treats the symptom, not the data.

## Consequences

- Pillar PDFs may hold detail the framework summarises; if evaluation (Phase 3)
  shows gaps, add specific pillar sections back deliberately.
- Cleaning rules are heuristics tuned on AWS documents. New document types need
  their own checks: `make data-quality` reports the same measures for any corpus.
- Removing the "Resources" lists also removes pointers to further reading. A later
  phase could keep them as metadata (links) without embedding them as content.
