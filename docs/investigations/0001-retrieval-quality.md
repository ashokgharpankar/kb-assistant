# Investigation 0001: A misleading citation and the data behind it

**Date:** 2026-11-21 · **Phase:** 1 / 2a · **Status:** Fixed and re-measured (section 5); two follow-ups open (5.2)
**Outcome:** [ADR 0009](../adr/0009-knowledge-base-sources-and-cleaning.md)

Investigations record *how* a problem was diagnosed: symptoms, hypotheses, evidence
and what was ruled out. ADRs record the decision that follows. Guides teach a phase.

---

## 1. Symptoms

Asking `kb ask "How should I design for failure?"` produced a confident, cited answer
with three problems:

| Symptom | Example |
|---|---|
| **Misleading citation** | "Implement shuffle-sharding to improve resilience **[3]**": source [3] only listed a conference talk title |
| **Garbled text in the answer** | "shu**ﬄ**e", a single ligature character copied from the source |
| **Slow first request** | `retrieval=7110ms first_token=8466ms total=13180ms` |

Earlier searches showed two more: off-topic questions scored up to 0.578 (above the 0.4
similarity floor), and a "Table of Contents" chunk came back for "best pizza in Mumbai".

## 2. Method

Reproduce → look at what the model was given → form hypotheses → test each one
against the database with a measurement → fix only what the evidence supports.

All measurements ran directly in Postgres against the 4,268 ingested chunks.
The queries are saved as [`scripts/sql/data_quality.sql`](../../scripts/sql/data_quality.sql)
and [`scripts/sql/duplicates.sql`](../../scripts/sql/duplicates.sql), so the same
measurements can be repeated after the fix (`make data-quality`, `make duplicates`).

## 3. Hypotheses and evidence

### H1: Ligature characters break matching. **Confirmed.**

- `content ILIKE '%shuffle-sharding%'` → **0 rows**, although the model quoted it.
- `content LIKE '%Shuﬄe%'` (with the ligature character U+FB04) → 2 rows.
- Chunks containing any ligature: **3,777 of 4,268 (88.5%)**.
- **Root cause:** PyMuPDF's default text-extraction flags include
  `TEXT_PRESERVE_LIGATURES`, so "ﬁ", "ﬂ", "ﬄ" arrive as single characters.
  A one-flag default, not a damaged PDF.

### H2: Reference lists are indexed as guidance. **Confirmed.**

- The chunk behind citation [3], `wellarchitected-reliability-pillar:00447`, begins
  "• Shuﬄe-sharding: AWS re:Invent 2019: Introducing The Amazon Builders' Library (DOP328)".
- Other chunks are lists of service names and "Related videos:" entries.
- **Root cause:** each AWS best practice ends with a "Resources" block. It is *about*
  the topic, so it ranks highly, but it contains titles, not advice; the model then
  turns a title into a recommendation and cites it.

### H3: Running page headers pollute chunks. **Confirmed (lower bound).**

- Chunks *starting* with the header: **26.6%**. Headers that fall mid-chunk (page breaks
  inside a chunk) were not counted, so the true share is higher.
- **Effect:** the same header text in a quarter or more of all vectors pulls every
  score toward every other, narrowing the gap between relevant and off-topic results.

### H4: Table-of-contents text is indexed. **Confirmed.**

- Duplicate-prefix analysis surfaced lines like "Implementation guidance ........" and
  "Resources ........": dot leaders from tables of contents.
- The off-topic "pizza" query's top hit was a "Table of Contents" section.

### H5: The framework PDF duplicates the pillar PDFs. **Partly confirmed.**

Exact nearest-neighbour search (index off) from 200 Reliability-pillar chunks into the framework PDF:

| Similarity to closest framework chunk | Chunks |
|---|---|
| > 0.95 | 11 (5.5%) |
| > 0.90 | **85 (42.5%)** |

Few chunks are identical because the two PDFs split text at different points, but
over two-fifths have a very close counterpart: the same content, chunked differently.

### H6: HNSW plus a document filter dropped results. **Ruled out.**

The first duplicate query appeared to return nothing. The hypothesis was the known
pgvector pitfall: an approximate index collects ~40 candidates (`hnsw.ef_search`)
*then* applies the filter, so a selective filter can leave zero rows.

Running the same 200 chunks with the index (A) and with exact search (B) gave identical
results (200 of 200 matched, 11 near-duplicates in both). The index was fine here
because the filtered document held 64% of all chunks. **The empty result was a terminal
paste problem** (line breaks and spaces stripped when pasting into an interactive
`docker compose exec` session). Lesson: confirm a hypothesis with a controlled
comparison, not a plausible story. The pitfall remains real for selective filters and
is tracked for Phase 4 (metadata filters) and Phase 6 (per-user access).

### H7: Retrieval itself is slow. **Ruled out; two other causes found.**

Timing each step in isolation:

| | embed question | vector search |
|---|---|---|
| First `kb ask` | ~7,000 ms (inside "retrieval") | — |
| Run 1 (script) | 173 ms | 228 ms |
| Run 2 (script) | 26 ms | 47 ms |

- **Cold start:** `ollama ps` showed models are unloaded 5 minutes after last use.
  The 7 seconds were model loading. Development fix: `OLLAMA_KEEP_ALIVE`. Bedrock
  on-demand models have no model-loading step.
- **A new database connection per search** (~30-40 ms of setup each time). Fixed with a
  connection pool.

## 4. Root causes

| # | Root cause | Layer | Fix |
|---|---|---|---|
| 1 | PDF extraction keeps ligatures by default | Loading | Flag off + NFKC normalisation |
| 2 | "Resources" link lists embedded as content | Chunking | Detect and drop reference-list chunks |
| 3 | Running headers/footers kept | Loading | Remove lines repeated at page edges |
| 4 | Table-of-contents text kept | Loading | Drop dot-leader lines; skip ToC/revisions/notices |
| 5 | Overlapping sources | Source selection | Framework PDF only (ADR 0009) |
| 6 | Models unloaded after 5 min | Local runtime | `OLLAMA_KEEP_ALIVE` (dev only) |
| 7 | Connection per query | Storage | `psycopg_pool` connection pool |

None of the root causes were in the model or the prompt. The misleading citation was a
**data** problem that surfaced as a **generation** problem.

## 5. Before and after

Measured on 2026-11-21 after applying the patch and re-ingesting
(`make ingest`, then `kb ingest data/raw --prune`, then `make data-quality`).

| Measure | Before | After |
|---|---|---|
| Documents / chunks | 4 / 4,268 | 1 / 2,499 (framework: 2,717 → 2,499) |
| Chunks with ligatures | 88.5% | 0% |
| Chunks starting with the page header | ≥26.6% | none; top first line is a real heading at 1.4% |
| Chunks with dot leaders | present | 0 |
| "Table of Contents" / "Document revisions" sections | present | none |
| Top score, "What's the weather today?" | 0.578 | 0.571 |
| Top score, "Best pizza in Mumbai" | 0.460 | 0.447 |
| Top score, "How should I design for failure?" | 0.738 | 0.746 (top 5: 0.730-0.746, all Reliability) |
| "Shuffle-sharding" in the design-for-failure answer | yes, citing a talk title | no |
| Retrieval (embed + vector search, warm) | 7,110 ms cold; 47 ms search alone | 90 ms |
| Chunks with reference markers | not measured | 253 (~10%); see 5.2 |

### 5.1 What the numbers say

- **Every cleaning target hit zero.** Each one was a single cause with a single fix.
- **The score gap held, and widened slightly.** Lowest relevant score 0.730 against
  highest off-topic 0.571: a gap of 0.159 (it was about 0.15). The 0.62 floor sits
  near the middle of the gap, so it stays until Phase 3 calibrates it on a test set.
- **Cleaning barely moved the off-topic scores.** Scores are driven by meaning, not
  by noise characters. The gain from cleaning is in *which* chunks win and what
  text the model reads, not in the raw numbers.
- **All five design-for-failure results are now guidance from the Reliability
  pillar**, and the answer no longer cites a conference talk title.

### 5.2 Still open

1. **Mixed reference chunks.** 253 chunks hold guidance followed by a "Resources"
   block. The filter keeps them because they are not mostly links. Next step:
   measure where the marker sits in each chunk; if it is mostly at the end, cut
   "Resources" blocks off before chunking.
2. **Citations that aren't source numbers.** llama3.2 cited best-practice IDs
   (`[REL11-BP01]`) instead of `[n]`. `extract_citations` only reads `[n]`, so
   six of the fifteen bullets have no usable citation. The facts are plausibly in
   chunk [1], but the reader cannot check that. This is a generation problem, not a
   retrieval one: tighten the prompt now, and measure citation accuracy in Phase 3.
3. **Time to first token is 5.3 s** for a 1,055-token prompt. Retrieval is no
   longer the bottleneck; the local 3B model is. Confirm with a second warm run.

## 6. Lessons

1. **Look at the data before tuning the model.** Every root cause was visible in a
   few SQL queries over the chunks.
2. **Measure, then fix.** Each change in ADR 0009 is tied to a number above, and the
   same queries re-measure it.
3. **Rule things out explicitly.** Two plausible hypotheses (H6, H7's "slow retrieval")
   were wrong; a controlled comparison and step-by-step timing showed it.
4. **Defaults matter.** The largest problem (88.5% of chunks) came from one library default.
5. **Absolute similarity scores mean little; gaps do.** Off-topic text scored 0.46-0.58,
   relevant text 0.73+. Thresholds belong in the gap, and Phase 3 will calibrate
   them on a proper test set.

## 7. Interview version

"A RAG answer cited a source that didn't support it. Instead of changing the prompt, I
inspected the retrieved chunks and measured the corpus in SQL: 88% of chunks had
ligature characters because of a PDF-library default, reference lists were embedded as
if they were guidance, page headers and table-of-contents text were in the index, and
two source documents overlapped heavily. I ruled out an index-filtering theory with a
controlled comparison, fixed the issues at ingestion, kept the diagnostic queries in the
repo, and re-measured."
