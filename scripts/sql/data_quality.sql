-- Data-quality report for one embedding space.  Run:  make data-quality
-- Table defaults to the local Ollama space; override with: -v t=kb_chunks_..._512
-- Each section measured a problem found in docs/investigations/0001-retrieval-quality.md.

\if :{?t}
\else
  \set t kb_chunks_ollama_nomic_embed_text_768
\endif
\pset footer off

\echo '\n=== Chunks per document'
SELECT document_id, count(*) AS chunks FROM :t GROUP BY 1 ORDER BY 1;

\echo '\n=== Ligature characters (target: 0%)'
SELECT count(*) FILTER (WHERE content ~ '[ﬀﬁﬂﬃﬄﬅﬆ]') AS chunks_with_ligatures,
       round(100.0 * count(*) FILTER (WHERE content ~ '[ﬀﬁﬂﬃﬄﬅﬆ]') / greatest(count(*), 1), 1) AS pct
FROM :t;

\echo '\n=== Most common first lines (a repeated first line is usually a page header)'
SELECT left(split_part(content, E'\n', 1), 60) AS first_line, count(*) AS chunks,
       round(100.0 * count(*) / (SELECT count(*) FROM :t), 1) AS pct
FROM :t GROUP BY 1 ORDER BY 2 DESC LIMIT 5;

\echo '\n=== Table-of-contents dot leaders (target: 0)'
SELECT count(*) AS chunks_with_dot_leaders FROM :t WHERE content ~ '\.{5,}\s*\d*\s*(\n|$)';

\echo '\n=== Reference-list markers (target: few, only inside real guidance)'
SELECT count(*) AS chunks_with_reference_markers
FROM :t WHERE content ~* 'related (documents|videos|examples|tools):|re:invent';

\echo '\n=== Sections that carry no guidance (target: none)'
SELECT section, count(*) FROM :t
WHERE section ~* '^(table of contents|contents|document revisions?|notices)$'
GROUP BY 1;
