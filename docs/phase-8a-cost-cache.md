# Phase 8a: Cost per question and an answer cache

**Time:** 1–1.5 hours. **Cost:** $0 (local models, the existing Postgres).

**Goal:** know what one question costs before the bill does, and stop paying (in money and
seconds) for questions already answered.

**You finish with:**

- An answer cache: exact match first, then semantic behind a threshold you **measured**, in a
  Postgres table next to the chunks. Guardrails run first; cached answers still get the
  grounding check.
- `make cache-check`: labelled question pairs → a recommended threshold, and a failure if the
  threshold would serve a near miss ("RTO" for "RPO").
- **Projected cost** in every evaluation: the local run's tokens priced on the hosted model
  (`KB_PROJECTED_PRICE_MODEL`, Nova Micro by default), in total and per question.
- Cache metrics (`kb_cache_requests_total{result}`, tokens and dollars saved), a dashboard row,
  a "From cache" label in the UI.
- ADR 0018.

---

## Part 1: Concepts

### 1. Unit economics: cost per question

The number a TPM or architect is asked for is **cost per question** (and per user per month),
not the monthly bill. It has two parts:

| Part | Example (Nova Micro, ~850 tokens in / ~100 out) | Scales with |
|---|---|---|
| Variable: model + embeddings | 850 × $0.035/M + 100 × $0.14/M ≈ **$0.00004** | questions |
| Fixed: Aurora, ALB, Fargate, CloudFront | roughly **$40–60 / month** in dev | time |

At 1,000 questions a day the model costs about $1.20 a month; the platform costs fifty times
that. Two lessons: at low volume **fixed costs dominate** (scale-to-zero Aurora and no NAT,
ADR 0015/0024, matter more than tokens), and the model share only dominates at high volume,
with a bigger model, or with an agent that searches and generates several times per question.

Local runs cost $0, which tells you nothing about production. So the evaluation now prices the
same tokens on the hosted model: `cost.projected_usd` and `cost.projected_usd_per_question`.
A prompt change that adds 2,000 tokens of context shows up as a cost regression in review,
before deploy.

### 2. Where caching helps an LLM app

| Layer | What it skips | Risk |
|---|---|---|
| **Exact answer cache** | the whole pipeline, for the same question | none (if namespaced) |
| **Semantic answer cache** | the whole pipeline, for a reworded question | a confident answer to a different question |
| Embedding cache | re-embedding the same text | none; small saving |
| Provider prompt caching (Bedrock, Anthropic) | re-processing a repeated prompt prefix | none; discount, not a skip |

The answer cache is the big one: a hit costs one embedding and one indexed lookup (tens of
milliseconds, $0) instead of seconds and a model call.

### 3. The semantic threshold is a classifier

"Is this new question the same as a cached one?" is a binary decision made by a similarity
threshold, exactly like the similarity floor (incident 0006). So it gets the same treatment:
labelled examples, a measured gap, and a test that fails on the dangerous errors.

The dangerous error is asymmetric. A miss costs one model call. A wrong hit returns a fluent,
cited answer to a question the user didn't ask. So the pairs file is mostly **near misses**:
RTO/RPO, multi-AZ/multi-Region, at rest/in transit, before/after, "use"/"avoid". If no
threshold separates them, keep exact-only: that's a legitimate outcome, not a failure.

### 4. Staleness: namespace, don't invalidate

An answer is only valid for the documents, prompt, model and retrieval settings that produced
it. Tracking which cached answers used which chunks is complicated. Instead every entry lives
in a **namespace**: a hash of the model, embedding space, prompt version, k, floor, retrieval,
reranker, answer mode and a fingerprint of the index. Change any of them and the cache is
effectively empty; old rows expire with the TTL. You can't forget a case.

### 5. Order of the wrappers

```
question → guardrails (input screen) → cache → pipeline/agent → model
                                   ↑ hit: replay sources + answer
answer ← guardrails (refusal, citations, grounding) ←┘
```

A blocked injection never touches the cache (nothing to store, nothing to poison), and a cached
answer is checked for grounding like a fresh one.

### 6. Cancelled streams: don't pay for tokens nobody reads

The cheapest token is one that's never generated. When the user presses Stop or closes the
tab, the API closes the pipeline, which closes the model client's HTTP stream, so the model
server sees the disconnect. That's now tested end to end against a fake Ollama server (it sees
the disconnect and sends a fraction of the answer). Whether a real provider then stops
generating, and billing, is its side of the contract: check it. The cancelled request is its
own outcome, `cancelled`, which the error SLO excludes. Found by a reader's comment: incident 0016.

### 7. Shared cache, one tenant

All users share the cache, which is right for one public knowledge base. With per-user or
per-tenant documents, the tenant (and permissions) must be part of the namespace, or the cache
becomes a data leak. Say this in an interview before anyone asks.

---

## Part 2: Build

Apply the zip, then:

```bash
uv sync
uv run kb init-db                      # unchanged; the cache table is created on first use
uv run mypy && make lint && make test
```

### Step 1: measure the threshold (and expect "no")

```bash
make cache-check
```

It embeds both sides of each pair in `eval/cache_pairs.jsonl` with your embedding model
(nomic-embed-text locally) and prints them sorted by similarity, then the lowest same-meaning
score, the highest different-meaning score and the gap. At the configured threshold it lists
any **WRONG** hit and exits 1.

- Clean gap → set `KB_CACHE_SEMANTIC_THRESHOLD` inside it (the recommended value is the middle),
  rounded **up**.
- No gap → `KB_CACHE_SEMANTIC_THRESHOLD=` (exact-only), and note it in the ADR.

Record the numbers in the Results section below.

### Step 2: see a hit

```bash
uv run kb ask "What is a game day?"          # model call, stored
uv run kb ask "what is a game day"           # exact hit: "from cache: exact (similarity 1.000)"
uv run kb ask "Can you explain what a game day is?"   # semantic hit, if above the threshold
uv run kb ask "What is a game day?" --no-cache        # bypass
```

Compare `total=` on the first and second call.

### Step 3: projected cost

```bash
make eval
```

The report has two new lines: `cost.projected_usd` (the run on Nova Micro) and
`cost.projected_usd_per_question`. Multiply the second by expected questions a month: that's
the variable half of the budget. The evaluation always bypasses the cache.

### Step 4: dashboard

```bash
make app-up obs-up
```

Ask a few repeats in the UI (it labels "From cache (same question)" / "(similar question, 98%)"
and shows `$0 (cached)`). Grafana → **Answer cache (Phase 8a)**: hit ratio, lookups by result,
tokens and dollars saved.

`make cache-clear` empties the cache for the current embedding space.

---

## Part 3: Verify

- [ ] `make cache-check` passes at the configured threshold (or threshold unset, with the reason).
- [ ] The second identical question shows `from cache: exact`, 0 tokens, and a total in ms.
- [ ] An injection is still blocked and nothing is stored for it.
- [ ] `make eval` shows projected cost; numbers unchanged otherwise (the cache is bypassed).
- [ ] `make obs-check` passes (new rules, the hit-ratio and cancelled-streams unit tests).
- [ ] In the UI, press **Stop** mid-answer: "Streams stopped by the user" goes up, the error
      ratio doesn't. Watch Ollama's CPU in Activity Monitor: it should drop right after Stop.
      That's Ollama's side of the contract; record what you see in incident 0016.
- [ ] Grafana shows the cache row with data.

## Results

Measured 27 Nov 2026: nomic-embed-text, llama3.2, 37-case evaluation.

| | Value |
|---|---|
| Lowest same-meaning similarity | 0.897 ("reduce my AWS costs" ~ "lower my AWS bill") |
| Highest different-meaning similarity | **0.986** ("Is it **safe** to store secrets in environment variables?" ~ "Is it **unsafe** …") |
| Gap / recommended threshold | **−0.089: no clean separation** |
| Threshold chosen | **none: exact-only** (semantic matching off by default) |
| Projected cost per question (Nova Micro) | **$0.000040** ($0.0015 per 37-case run) |
| Exact hit vs miss, CLI | **27–56 ms** vs 6.7 s; 0 tokens, 1,328 saved |

**How the decision changed, in two runs:**

1. First run, 20 pairs: the worst near miss was use/avoid reserved instances at 0.941. A
   threshold of 0.97 had a 0.029 margin, 0 wrong hits, and served 4 of 10 rewordings. Kept,
   with more negation pairs to come.
2. Second run, +4 negation pairs: **"safe" vs "unsafe" scored 0.986**, and "use" vs "not use"
   spot instances 0.967. At 0.97 the check failed with a wrong hit: a question about whether
   something is *unsafe* would have been served the answer about whether it's *safe*. Above
   0.986, only 2 of 10 rewordings hit, and those are nearly exact anyway.

So **semantic matching is off by default**; the exact cache stays on. The code, the check and
the setting remain: a different embedding model (Titan on Bedrock) may separate better, and
`make cache-check` decides.

What the pairs showed:

- **The dangerous pairs aren't the ones you'd guess.** RTO vs RPO scored only 0.767. The near
  misses that come closest are **negations in the same sentence shape**: safe/unsafe (0.986),
  use/not use (0.967), use/avoid (0.941), enable/disable (0.931). A one-word change of polarity
  barely moves the vector.
- **True rewordings with different words score lower** ("lower my AWS bill", 0.897). Any
  threshold low enough to catch them serves opposites.
- **More test cases changed the answer.** 20 pairs said 0.97 was safe; 24 said it wasn't. The
  check is only as good as its near misses, so it leans on negation.

Evaluation noise (same configuration, three runs): `answer.grounding_score` 57%, 49%, 53%. One
reworded answer moves it about 4 points, so it now has its own 10-point regression tolerance
(`METRIC_TOLERANCE` in `report.py`); everything else keeps 5. Input tokens were identical on
every run (31,165), which confirms the evaluation bypasses the cache.

Follow-up fixes from these numbers:

- **Exact hits no longer embed the question**: 1.3 s → 27–56 ms on the CLI.
- The CLI labels a hit's time `cache_lookup=` instead of `retrieval=`.
- `KB_CACHE_SEMANTIC_THRESHOLD=` (empty) now means "off"; before, it failed to parse.

---

## Interview framing

**"How would you reduce the cost of a RAG assistant?"** Start with unit economics: cost per
question, split into variable (tokens) and fixed (platform). At low volume the platform
dominates, so scale-to-zero matters more than tokens. Then the levers in order of safety:
exact cache, trimming context (k, chunk size: measured in the eval as projected cost), prompt
caching at the provider, model routing (8b), and only then a semantic cache with a measured
threshold.

**"What can go wrong with a semantic cache?"** Wrong hits on near-identical questions with
different meanings, stale answers after the documents change, and cross-tenant leaks. Answers:
a labelled near-miss test that gates the threshold, namespacing by everything that changes an
answer, and the tenant in the namespace.

**"How do you know it's working?"** Hit ratio, dollars and tokens saved on the dashboard; the
UI and the trace label every hit; the evaluation bypasses the cache so quality numbers stay
honest.
