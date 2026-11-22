# Phase 2a: Streaming answers and LLM tracing

**Time:** half a day. **AWS cost:** $0 (local models, local Langfuse).

**You finish with:**

- `kb ask` printing the answer word by word as the model writes it.
- `POST /ask/stream` sending sources, tokens and a final summary as Server-Sent Events.
- Latency broken down: retrieval, **time to first token**, total.
- Every question recorded in Langfuse as one trace: retrieval results, the exact prompt, the answer, tokens and cost.

Phase 2 has three parts: **2a** (this), **2b** React UI, **2c** Cognito sign-in and the Bedrock switch.

---

## Part 1: Concepts

### 1. Why stream?

A small local model takes 3 to 10 seconds to write a full answer. Without streaming, the user stares at a spinner for all of it. With streaming, the first words appear in well under a second and the rest follows as they read. The total time is the same; the *perceived* speed is completely different.

That's why production LLM apps track **time to first token (TTFT)** as their main latency number, not total time. A typical target: p95 TTFT under 2 seconds.

### 2. How streaming works, layer by layer

```
Ollama/Bedrock ──chunks──► LangChain .stream() ──► RagPipeline.stream() ──► FastAPI StreamingResponse ──► browser / curl
                           (AIMessageChunk)        (SourcesEvent,             (text/event-stream)
                                                    TokenEvent, DoneEvent)
```

- The **model** sends small pieces as it generates them. Ollama sends newline-separated JSON; Bedrock's ConverseStream sends events.
- **LangChain** hides that difference: `chat_model.stream(messages)` yields `AIMessageChunk`s for every provider. The *last* chunk carries token usage.
- **Our pipeline** turns that into three event types: `SourcesEvent` (once, before generation), `TokenEvent` (many), `DoneEvent` (once, with citations, tokens, cost and timings).
- **FastAPI** sends each event as soon as it's yielded.

`answer()` now simply consumes `stream()` and returns the final result, so the streaming and non-streaming endpoints share one code path.

### 3. Server-Sent Events (SSE)

SSE is a simple text format over a normal HTTP response:

```
event: sources
data: [{"number": 1, "section": "Reliability", "page": 657, ...}]

event: token
data: {"text": "Deploy "}

event: done
data: {"answer": "...", "citations": [...], "cost_usd": "0", "time_to_first_token_ms": 412.0, ...}
```

Each event is an `event:` line, a `data:` line and a blank line. We JSON-encode the data so a newline inside a token can't break the format.

**Why SSE and not WebSockets?** We only need server-to-client. SSE is plain HTTP, works through load balancers and CloudFront, and you can watch it with `curl -N`. See ADR 0008.

**One catch:** once streaming starts, the HTTP status (200) has already been sent. If something fails mid-answer, the API sends an `event: error` instead of a 500. Clients must handle it.

### 4. LLM tracing with Langfuse

Normal logs tell you a request took 4 seconds. A **trace** tells you *why*, and what the model actually saw:

```
rag.answer   (chain)       question → answer, cost, tokens, timings
├── retrieve (retriever)   question → chunk ids, sections, pages, similarity scores
└── generate (generation)  full prompt → answer, model, token usage, cost
```

When an answer is bad, open its trace: if `retrieve` returned the wrong chunks, it's a retrieval problem; if the right chunks are in the `generate` input but the answer ignores them, it's the model or prompt. That's the debugging method from Phase 1, now one click away for every question, not just the ones you ran with `--show-context`.

Langfuse v5 is built on **OpenTelemetry**, the industry standard for traces, so the same data could go to other tools (X-Ray, Grafana Tempo) later.

**Tracing is optional:** with no Langfuse keys in `.env`, a no-op tracer runs and nothing leaves your machine. The pipeline code is identical either way.

**Privacy note:** traces contain the full prompt, including retrieved document text and the user's question. Fine for public AWS docs on your laptop; in production that's a data-classification decision (where traces are stored, retention, masking).

---

## Part 2: What changed in the repo

```
packages/kb_core/src/kb_core/
  models.py     + SourcesEvent, TokenEvent, DoneEvent; Answer gains retrieval_ms, time_to_first_token_ms, total_ms
  rag.py        RagPipeline.stream() generator; answer() consumes it; trace spans around retrieve/generate
  tracing.py    New: Tracer interface, NoopTracer, LangfuseTracer (Langfuse v5 SDK)
  factory.py    Builds the tracer from settings
  cli.py        `kb ask` streams by default (--no-stream to wait); prints timings; flushes traces on exit
apps/api/src/kb_api/main.py   + POST /ask/stream (SSE), error event, no-buffering headers
tests: test_streaming.py (event order, timings, trace shape), SSE endpoint tests, CLI streaming tests
docs/adr/0007, 0008; docs/architecture/README.md updated
```

---

## Part 3: Step by step

### Step 1: Apply and test (10 min)

```bash
unzip -o ~/Downloads/kb-assistant-phase2a.zip -d ~/Projects/kb-assistant
uv sync
make lint test               # 64 passed, 4 skipped
make test-integration        # 68 passed
```

### Step 2: Watch it stream in the terminal (5 min)

```bash
make up
uv run kb ask "What are the design principles of the Reliability pillar?"
```

The answer appears word by word. The last line now shows timings:

```
model=llama3.2 tokens=1190 in / 149 out cost=$0.000000 retrieved=4 retrieval=85ms first_token=640ms total=4210ms
```

Note your numbers in the build log. On a Mac with llama3.2, first token is typically well under a second; most of the total is generation.

### Step 3: Watch the raw SSE stream (5 min)

```bash
make api
# second terminal:
curl -N -X POST localhost:8000/ask/stream \
  -H 'content-type: application/json' \
  -d '{"question":"How should I design for failure?"}'
```

`-N` turns off curl's buffering so you see each event as it arrives.

### Step 4: Turn on tracing (15 min)

```bash
make langfuse-up
```

1. Open http://localhost:3000, sign up (local account), create an organisation and a project named `kb-assistant`.
2. **Settings → API Keys → Create**. Copy both keys into `.env`:
   ```
   KB_LANGFUSE_HOST=http://localhost:3000
   KB_LANGFUSE_PUBLIC_KEY=pk-lf-...
   KB_LANGFUSE_SECRET_KEY=sk-lf-...
   ```
3. Ask two or three questions, including an off-topic one:
   ```bash
   uv run kb ask "What does the framework say about tagging?"
   uv run kb ask "What is the capital of France?"
   ```
4. In Langfuse open **Tracing**. Click a trace and look at:
   - `retrieve`: which chunks, which pages, which scores.
   - `generate`: the exact prompt (system rules, escaped sources, question), the answer, token counts.
   - The off-topic question: a trace with **no** `generate` step: the "not found" short-circuit, visible.
   - The timeline view: how much of the total is retrieval versus generation.

If Langfuse's containers are too heavy for your Mac's memory, use Langfuse Cloud's free plan instead and set `KB_LANGFUSE_HOST` to its URL. The code doesn't change.

### Step 5: Commit

```bash
git checkout -b phase-2a
git add -A && git commit -m "Phase 2a: SSE streaming, TTFT metrics, Langfuse tracing"
git push -u origin phase-2a
gh pr create --fill && gh pr checks --watch
gh pr merge --squash
```

Working on a branch with a PR is a good habit now, even solo: CI runs on the PR before anything reaches `main`.

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Streaming transport | SSE over POST | WebSockets; GET EventSource | One-way is all we need; plain HTTP; questions stay out of URLs and logs |
| Event design | sources → tokens → done | Tokens only | UI can show citations while the answer is still being written |
| Error mid-stream | `error` event | Closing the connection | Status is already 200; the client needs a clear signal |
| One code path | `answer()` consumes `stream()` | Separate invoke path | One place for retrieval, tracing, cost and citations |
| Tracing integration | Direct Langfuse spans | LangChain callback handler | Retrieval and generation in one tree, provider-neutral, explicit fields |
| Tracing default | Off without keys | Always on | No data leaves the machine unless configured |
| Latency metric | TTFT + retrieval + total | Total only | TTFT is what users feel when streaming |

---

## Part 5: Interview hooks

1. *"How do you make an LLM app feel fast?"* Stream tokens; measure time to first token separately from total; send sources first; keep retrieval fast (HNSW, small top-k). Our split: retrieval tens of milliseconds, the rest is generation.
2. *"How do you debug a bad answer in production?"* One trace per request with retrieval and generation as child spans: see which chunks were retrieved and their scores, the exact prompt, tokens and cost. Decide retrieval versus generation from the trace, not from guesses.
3. *"SSE or WebSockets for an LLM chat?"* SSE for one-way token streaming: plain HTTP, proxy-friendly. WebSockets when the client must send data mid-response (voice, collaborative editing).
4. *"What's sensitive in LLM traces?"* Full prompts include user questions and retrieved document text. Decide where traces live, how long, and mask fields when needed.

**Resume line:** "Added token streaming over SSE with time-to-first-token metrics, and per-request LLM tracing (Langfuse on OpenTelemetry) covering retrieval results, prompts, token usage and cost."

---

## Part 6: Done checklist

- [ ] `make lint test` and `make test-integration` pass
- [ ] `kb ask` streams; timings noted in the build log
- [ ] `curl -N` shows `sources`, `token`… and `done` events
- [ ] Langfuse traces visible; one with and one without a `generate` step
- [ ] Merged through a PR with CI green

**Next: [Phase 2b](phase-2b-web-ui.md).** A React UI that consumes `/ask/stream`: chat box, answer appearing live, clickable citations.
