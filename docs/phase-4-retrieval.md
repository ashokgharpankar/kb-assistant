# Phase 4: Better retrieval, measured

**Time:** half a day. **AWS cost:** $0 (all local).

**Goal (from Phase 3):** hit rate @4 from 79% to at least 95%. All misses were "What are the
design principles of the X pillar?": the text exists, but overview chunks outrank it.

**You finish with:**

- Sections that follow the PDF's headings to depth 4, titled with their heading path
  ("Security > Design principles"), and each chunk embedded under that path.
- "Resources" link lists removed from chunks.
- Hybrid search: Postgres full-text search plus vectors, merged with reciprocal rank fusion.
- An optional local reranker (FlashRank).
- A before/after table from `make eval`, one change at a time. That table is the result of
  this phase, and the core of the next blog post.

---

## Part 1: Concepts

### 1. Why the principles list lost

Embeddings compare meaning. The question *"What are the design principles of the Security
pillar?"* is very close in meaning to a paragraph that says *"The security pillar describes
how to…"*, and not very close to a list of short phrases (*"Implement a strong identity
foundation • Maintain traceability • …"*). The list never says what it is: in the PDF, the
heading "Design principles" sits above it, but our Phase 1 sections stopped at depth 2
("Security"), so that heading never reached the chunk or its embedding.

### 2. Fix 1: heading paths (cheap context)

The loader now splits at TOC headings down to depth 4, finds each heading in the text (so
sections start exactly at the heading, even several per page), and titles each section with
its path: `Security > Design principles`. At ingestion, each chunk is embedded as
`"<heading path>\n\n<chunk text>"`. The stored text is unchanged; the vector now "knows"
what the list is.

This is a cheap version of **contextual retrieval**: some teams have a model write a sentence
of context for every chunk at ingestion. That's a model call per chunk (~2,500 here); the
heading path is free and often gets much of the benefit.

### 3. Fix 2: hybrid search

Vector search finds *similar meaning*; keyword search finds *the same words*. Each misses
what the other catches:

| Query | Vector search | Keyword search |
|---|---|---|
| "How can my architecture keep working when parts break?" | ✅ finds "withstand component failures" | ❌ few shared words |
| "design principles security" | ❌ prefers overviews | ✅ "design principles" in the heading |
| "REL10-BP01", "RPO", product names | ❌ IDs embed poorly | ✅ exact match |

**Hybrid** runs both and merges them. Postgres does full-text search natively: each chunk has a
`search_tsv` column (stemmed words, heading path weighted above the body) with a GIN index.

**Merging: reciprocal rank fusion (RRF).** Cosine similarity (0.76) and text rank (3.0) are on
different scales, so adding scores is meaningless. RRF uses only **ranks**: each list gives a
chunk `1 / (60 + rank)`, summed. A chunk near the top of both lists wins; a chunk at the top
of one still scores well. No calibration needed.

### 4. Fix 3: a reranker (cross-encoder)

The embedding model is a **bi-encoder**: question and chunk are encoded *separately* and
compared as vectors. Fast (chunks are encoded once, at ingestion) but coarse.

A **cross-encoder** reads the question and a chunk *together* and outputs "how well does this
answer that?". Much better at relevance, but it must run for every (question, chunk) pair, so
it only re-orders a short candidate list: retrieve 20, rerank, keep 4.

FlashRank runs a small cross-encoder (`ms-marco-MiniLM-L-12-v2`) on ONNX on the CPU: no GPU,
no API, ~30 MB downloaded once. Cost: some milliseconds per question, measured below.

### 5. One change at a time

Each fix is a setting, so its effect is measured separately:

| Setting | Values | Needs re-ingest? |
|---|---|---|
| `KB_TOC_DEPTH` | 1–8 (default 4) | yes |
| `KB_CHUNK_HEADERS` | true / false | yes |
| `KB_RETRIEVAL_MODE` | vector / hybrid (default) | no |
| `KB_RERANKER` | none (default) / flashrank | no |
| `KB_RETRIEVAL_CANDIDATES` | pool size for hybrid/rerank (20) | no |

`make ingest` re-processes a document whenever any ingestion setting or the chunker
changes (the fingerprint includes them), so switching back and forth is just a re-run (~1 min).

---

## Part 2: What changed in the repo

| Path | What |
|---|---|
| `kb_core/loaders.py` | `build_sections()`: headings located in the text, heading paths, configurable depth |
| `kb_core/chunking.py` | `strip_resources()`, `embedding_text()` (heading path + chunk), chunker version 3 |
| `kb_core/store.py` | `search_tsv` column (heading weighted 'A', body 'B') + GIN index; `hybrid_search()` with RRF in one SQL query; old `content_tsv` dropped |
| `kb_core/retrieval.py` | New: `Retriever` (vector / hybrid, candidate pool, optional reranker, floor last), `FlashRankReranker` |
| `kb_core/factory.py`, `rag.py` | The pipeline ranks through the retriever |
| `kb_core/cli.py` | `kb search` shows the strategy and rerank scores; `kb eval` records the strategy; new `kb toc` |
| `kb_core/settings.py`, `.env.example` | The five settings above |
| tests | `test_retrieval.py` (sections, Resources, headers, retriever, reranker); hybrid search and schema upgrade on real Postgres |
| `docs/adr/0011-hybrid-search-reranking.md` | The decisions |

---

## Part 3: Step by step

### Step 1: Apply (10 min)

```bash
git checkout main && git pull && git checkout -b phase-4
unzip -o ~/Downloads/kb-assistant-phase4.zip -d .
uv sync                          # adds flashrank + onnxruntime (~170 MB)
make lint test                   # 150 passed, 11 skipped (161 with make test-integration)
make up && make init-db          # adds the full-text column and index to your table
```

### Step 2: Look at the table of contents (5 min)

```bash
uv run kb toc data/raw/wellarchitected-framework.pdf --depth 6 --match "design principles"
```

Note the **level** (L2, L3, L4 …) of the "… > Design principles" entries. `KB_TOC_DEPTH`
must be at least that level. If they're deeper than 4, set `KB_TOC_DEPTH` in `.env` to that
level. Also try `--depth 3` without `--match` to get a feel for the structure.

### Step 3: The experiments (30–40 min)

Run each and copy the key rows into the table below (`--no-save` keeps your results folder
tidy; drop it if you want the reports). Each `kb eval` compares with the Phase 3 baseline, so
the **Change** column is your before/after.

```bash
# A. New chunks (heading paths, headers, Resources removed), vector search only
make ingest
KB_RETRIEVAL_MODE=vector uv run kb eval --no-save

# B. Same chunks, hybrid search (the new default)
uv run kb eval --no-save

# C. Hybrid + reranker (first run downloads the model)
KB_RERANKER=flashrank uv run kb eval --no-save

# D. (optional) Is it the headers or the sections? Embed without headers:
KB_CHUNK_HEADERS=false make ingest
KB_RETRIEVAL_MODE=vector uv run kb eval --no-save
make ingest                       # back to headers on
```

Latency is shown but no longer flagged as a regression by default: on a laptop it moves by
50% between identical runs. `--gate-latency` turns the check back on (Phase 7 uses it in CI).

| Run | hit@4 | MRR | pass | false refusals | fact recall | citation validity | TTFT p50 | total p95 |
|---|---|---|---|---|---|---|---|---|
| Phase 3 baseline | 79% | 0.72 | 85% | 4% | 73% | 88% | 1.19 s | 7.8 s |
| A. new chunks, vector | 83% | 0.76 | 88% | 8% | 72% | 90% | 1.72 s | 7.0 s |
| **B. hybrid** | **96%** | **0.79** | **94%** | 4% | 73% | 87% | 1.88 s | 6.4 s |
| C. hybrid + rerank | 88% | 0.76 | 91% | 0% | 68% | 80% | 2.37 s | 8.5 s |

Measured 24 Nov 2026: llama3.2 (3B), k=4, floor 0.62, 2,711 chunks. Off-topic rejected at the
floor: 40% (A), 50% (B).

Also look at the five "design principles" cases in each report: which change turned them green?

### Step 4: Check the data (5 min)

```bash
make data-quality
uv run kb search "What are the design principles of the Security pillar?" --k 5
KB_RERANKER=flashrank uv run kb search "What are the design principles of the Security pillar?" --k 5
```

In `data-quality`, the **reference markers** count should drop well below the 253 from
investigation 0001. In `kb search`, look for a section titled `… > Design principles` near the
top, and compare the rerank scores of the principles chunk and the overviews.

### Step 5: Choose the defaults and save the baseline (10 min)

Pick the configuration with the best quality you can afford in latency:

- If **C** clearly beats **B** and the reranker's extra time is acceptable, set
  `KB_RERANKER=flashrank` in `.env` (and tell me, so the code default changes too).
- If B is as good, keep the reranker off: simpler and faster.

Then, with the chosen settings:

```bash
uv run kb eval                    # final run: the Change column vs Phase 3, saved to eval/results/
make eval-baseline                # this becomes the reference for the next phases
```

If the floor table now shows a clean gap, consider the recommended floor too. And if hit@4 is
now ≥ 95%, raise `retrieval.hit_rate_at_k` in `eval/gate.toml` to just below it.

### Step 6: Commit

Put the experiment table in the PR description: that's the record of why the defaults are what
they are.

```bash
git add -A
git commit -m "Phase 4: heading-path chunks, hybrid search, optional reranker"
git push -u origin phase-4
gh pr create --fill
gh pr view --web                 # paste the experiment table into the description
gh pr checks --watch && gh pr merge --squash
gh pr view --json state          # wait for MERGED before deleting the branch
```

### Results and decision (24 Nov 2026)

**Hybrid on, reranker off.** These are now the code defaults (`retrieval_mode = "hybrid"`,
`reranker = "none"`); ADR 0011 records why.

- **Headers and sections (A)** helped a little: hit@4 79% → 83%.
- **Hybrid search (B)** met the target: hit@4 96%, pass rate 94%, four of the six "design
  principles" questions fixed. The words "design principles" in the heading path are an exact
  keyword match that the embedding alone ranked too low. Answer quality held; total p95 even
  improved.
- **The reranker (C) made it worse:** hit@4 88%, fact recall 68%, citation validity 80%, and
  +0.5 s to first token. It pushed the principles lists back down (Security to rank 7,
  Operations to rank 5). Likely cause: the MS MARCO model learned that answers are paragraphs,
  so a bullet list of short phrases scores below an overview paragraph. Its one gain was 0%
  false refusals. Revisit with a Bedrock rerank model in Phase 7, measured the same way.
- **The floor stays at 0.62.** The recommended 0.712 sits in a gap of 0.007, about one
  question wide, so it would flip with the next change.
- **Gate:** `retrieval.hit_rate_at_k` raised to 0.90 (one miss of headroom).

Still failing with hybrid:

- `sec-principles`: the evidence is in the top 4 but llama3.2 refuses. A generation problem;
  test with qwen2.5:7b or Bedrock.
- `perf-principles`: the label was wrong, not retrieval. See
  [incident 0008](investigations/0008-stale-eval-label.md).

### Problems found while measuring (24 Nov 2026)

Written up as [incident 0007](investigations/0007-eval-top-score-bug.md).

**1. An evaluation bug misreported top scores under hybrid search.**

- *Symptom:* in run B (hybrid), every question's "top score" dropped (e.g. `rel-principles`
  0.806 → 0.734) although only the ranking had changed.
- *Cause:* `kb eval` recorded each question's top score as the similarity of the **first**
  retrieved chunk. With vector search the first chunk is the most similar one, so Phase 3 was
  right. With hybrid search (and a reranker) the first chunk is the best **fused** result,
  often less similar. The floor analysis compared the wrong numbers. The pipeline itself was
  never affected: it applies the floor to every chunk.
- *Fix:* the top score is now the **highest** similarity among the retrieved chunks, with a
  test that uses a fused order where the first chunk isn't the most similar. After the fix:
  `rel-principles` 0.770, gap −0.009 → +0.007.
- *Correction:* I first blamed this bug for `off_topic_rejected` rising from 40% to 50% and
  predicted the fix would undo it. It didn't: 50% after the fix too. That change is real and
  comes from hybrid search retrieving different chunks.
- *Lesson:* when the retrieval strategy changes, re-check the assumptions the evaluation makes
  about it. And confirm a fix's predicted effect by re-running before writing it down.

**2. Laptop latency was flagged as a regression twice.**

- Median time to first token went 1.19 s → 1.72 s (run A) → 1.93 s (run B), while the 95th
  percentile stayed flat and total time improved. Input tokens rose only ~50 per question.
- The baseline's 1.19 s was a fast run; local model timings vary with whatever else the laptop
  is doing. Treating that as a regression produces false alarms that teach people to ignore the
  gate.
- *Change:* latency is still reported, but only counts as a regression with `--gate-latency`.
  Phase 7 turns it on in CI against Bedrock, where timings are steadier. See ADR 0010's amendment.

**3. A "retrieval miss" was a stale label** ([incident 0008](investigations/0008-stale-eval-label.md)).

- `perf-principles` never found its evidence ("mechanical sympathy") in the top 10, under any
  setting. SQL on the "Design principles" chunks showed this edition's Performance principles
  are different ("Use managed services to reduce operational complexity", "Deploy workloads
  closer to your customers", …). The label came from an older edition.
- *Fix:* evidence and facts rewritten from the indexed text.
- *Also seen:* the Security and Sustainability "Design principles" sections each start with a
  tiny chunk that is only the heading and one sentence. It ranks well (pure heading match) but
  carries no answer. Candidate fix: merge chunks under ~50 tokens into the next one (chunker v4).

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Chunk context | Heading path, embedded | LLM-written context per chunk | Free at ingestion; covers the measured failure |
| Keyword search | Postgres full-text (`ts_rank_cd`) | OpenSearch; BM25 extension | No new service; works on RDS/Aurora; RRF only needs ranks |
| Fusion | Reciprocal rank fusion (k=60) | Weighted score sum | No calibration across different score scales |
| Reranker | FlashRank (ONNX, CPU), optional | sentence-transformers; Bedrock rerank | ~170 MB vs ~1 GB (PyTorch); Bedrock when the quota is fixed |
| Candidates | 20, then keep 4 | Larger k | Better ranking without more tokens per answer |
| Floor | Cosine, per chunk, after ranking | Reranker score | Keep one change at a time; reranker scores evaluated later |

---

## Part 5: Interview hooks

1. *"Vector search or keyword search?"* Both: vectors for meaning and paraphrases, keywords for
   exact terms, IDs and headings. Merge with reciprocal rank fusion, which needs no score
   calibration. Postgres can do both in one query.
2. *"Bi-encoder vs cross-encoder?"* Bi-encoders embed separately: fast and precomputed, good for
   recall over thousands of chunks. Cross-encoders read the pair together: accurate but per-pair,
   so they rerank a short list. Retrieve wide, rerank narrow.
3. *"How do you improve retrieval without a bigger model?"* Find the failing question type with
   an evaluation set, look at what was retrieved, then fix the cause: here, chunks that didn't
   carry their heading, and a ranking that preferred overviews. Measure each change separately.
4. *"What's contextual retrieval?"* Giving each chunk context before embedding: its heading path
   (free) or a model-written summary (costly). I started with the free version, measured.
5. *"Did the reranker help?"* No, and I can show it: hit@4 fell from 96% to 88%, fact recall
   and citation validity dropped, and time to first token rose ~0.5 s. The off-the-shelf model
   prefers paragraph-shaped answers over bullet lists. I kept it off and kept the interface, to
   re-test with a hosted rerank model. "More components" isn't the same as "better".

**Resume line:** "Raised RAG retrieval hit rate @4 from 79% to 96% with heading-path chunk context
and hybrid search (Postgres full-text + pgvector, reciprocal rank fusion); measured and rejected a
cross-encoder reranker that lowered quality on this corpus."

---

## Part 6: Done checklist

- [x] `make lint test` and `make test-integration` pass
- [x] TOC inspected; `KB_TOC_DEPTH` covers the "Design principles" level
- [x] Experiments A–C in the table
- [x] Defaults chosen (hybrid on, reranker off); gate raised to 0.90
- [ ] New baseline saved (after the label fix)
- [ ] Reference-marker count re-measured
- [ ] Merged with the table in the PR description

**Next:** Phase 5, MCP and LangGraph. The retriever becomes a tool an agent can call.
