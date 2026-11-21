-- How much of document A also appears in document B?  Run:
--   make duplicates A=wellarchitected-reliability-pillar B=wellarchitected-framework
-- For a sample of A's chunks, finds the closest chunk in B by EXACT search (index off),
-- because an approximate index plus a selective filter can silently miss matches.

\if :{?t}
\else
  \set t kb_chunks_ollama_nomic_embed_text_768
\endif
\pset footer off

BEGIN;
SET LOCAL enable_indexscan = off;
WITH s AS (
  SELECT chunk_id, embedding FROM :t WHERE document_id = :'a' ORDER BY chunk_id LIMIT 200
)
SELECT count(*) FILTER (WHERE best > 0.95) AS near_duplicates_gt_095,
       count(*) FILTER (WHERE best > 0.90) AS very_similar_gt_090,
       count(best) AS matched,
       count(*)    AS sampled
FROM s LEFT JOIN LATERAL (
  SELECT 1 - (c.embedding <=> s.embedding) AS best
  FROM :t c WHERE c.document_id = :'b'
  ORDER BY c.embedding <=> s.embedding LIMIT 1
) n ON true;
COMMIT;
