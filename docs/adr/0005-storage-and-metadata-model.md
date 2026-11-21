# ADR 0005: Storage schema and document metadata model

**Status:** Accepted, 2026-11-19

## Context

Chunks and their vectors need a home in Postgres + pgvector (ADR 0002). Two
embedding providers produce vectors of different sizes (768 locally, 512 on
Bedrock) that must never be compared with each other. Re-ingesting hundreds of
pages should not re-embed text that has not changed.

## Decision

Own the schema with plain SQL (psycopg + pgvector), not `langchain-postgres`.

| Table | Holds |
| --- | --- |
| `kb_documents` | One row per source file: id, title, URI |
| `kb_chunks_<provider>_<model>_<dims>` | Chunks with text, section, page, vector, and a full-text column |
| `kb_ingest_state` | Per embedding space: which document, which fingerprint, how many chunks |

- One chunks table per **embedding space**, named from provider, model and size.
- HNSW index with cosine distance on the vector column.
- A generated `tsvector` column for keyword search, unused until Phase 4.
- A document's chunks are replaced in one transaction.
- Document ids come from file names, so re-ingesting updates in place.

## Why

- Mixing vector sizes in one column is impossible; mixing models of the same size
  is possible and silently wrong. Separate tables make both impossible.
- Owning the schema lets us add hybrid search, filters and ingest tracking
  without fighting a library's table layout.
- HNSW gives fast approximate search with good recall and no training step.
- Transactions mean a reader never sees half of a re-ingested document.

**Rejected:** `langchain-postgres` `PGVector` (fixed schema, one JSONB metadata
column, harder to extend); one table with a `space` column (one vector size per
column, so it cannot hold both providers).

## Consequences

- We maintain a little SQL that a library would otherwise own.
- Switching provider means re-ingesting into the other space. Both can exist side
  by side, which lets us compare them in Phase 3.
- File renames create a new document id; the old one must be deleted by hand for now.
