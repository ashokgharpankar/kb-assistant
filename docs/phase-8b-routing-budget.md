# Phase 8b: Model routing and a daily spend cap

**Time:** 1.5–2 hours, most of it waiting for evaluations. **Cost:** $0 (local models).

**Goal:** pay for the bigger model only when the small one fails, and make sure no day's bill
can run away, without turning a budget problem into a broken product.

**You finish with:**

- **Cascade routing:** when the small model refuses although the evidence is strong, the same
  prompt goes to a larger model once. Off by default; one setting turns it on.
- **A prompt-layout experiment:** each source's section as a visible line, for the small model.
- **A daily spend cap** in three steps: normal → economy (small model only) → over budget (no
  model call, cache still answers). A Postgres ledger, alerts, and a way to rehearse it locally.
- Evaluation: both calls of an escalated question counted and priced on their own models;
  `routing.escalation_rate`, `routing.escalations_passed`.
- ADR 0019.

---

## Part 1: Concepts

### 1. Why route at all

Phase 5b measured it: qwen2.5:7b passed every case, including `sec-principles`, which llama3.2
refuses with the right section in its top 4. But it took about 2× as long, and on Bedrock the
step up (Nova Micro → Nova Lite) costs about 1.7× per token. Paying that on every question to fix
one in 37 is the wrong trade. Routing pays it only where needed.

### 2. Three ways to route

| Pattern | How it decides | Cost of a wrong decision |
|---|---|---|
| **Classifier first** | a model or rules guess "hard" before answering | hard questions get the small model; easy ones pay for the big one |
| **Cascade** | the small model answers; a check decides whether to escalate | an escalation pays for two calls |
| **Ensemble / judge** | several models answer; a judge picks | every question pays for several |

A cascade needs one thing: a **reliable signal that the small answer failed**. We have one,
measured in earlier phases: a refusal (by meaning, without citations) while retrieval found
strong evidence. Both halves matter:

- *Refusal alone* isn't enough. Incident 0009: the agent retried off-topic and injection
  questions, which refused anyway, at a higher price.
- *Strong evidence* separates "the model failed to read it" from "it isn't there". The Azure
  question tops out at 0.666; `sec-principles` at 0.742. The bar is `KB_ROUTE_MIN_SIMILARITY`
  (0.70), in the gap the floor analysis showed.

### 3. Streaming and a cascade

Streaming starts before you know whether the answer is a refusal. Two tricks keep the UI honest:

- **Hold back a possible refusal.** While escalation is possible, tokens are held only while the
  text could still be the exact "not found" sentence. A real answer diverges within a word or
  two and streams normally; a plain refusal never reaches the screen.
- **Reset when needed.** A hedged refusal ("the sources don't explicitly list…") streams before
  it's recognised; the server then sends `escalate` with `reset: true`, and the UI replaces the
  text with "Checking with a larger model…" and the new answer.

### 4. Spend caps that degrade, not break

The monthly AWS budget is a backstop: it's hours late and can only email. The app needs its own
cap, checked **before** each model call, with steps:

```
spent today:   0% ────────── 80% ────────── 100%
               normal        economy        over budget
               (may route)   (small only)   (no model; cache hits still answer)
```

The soft step buys time: users still get answers, an alert fires (`KbSpendEconomyMode`), and
someone can look before the hard step. The hard step pages (`KbSpendCapReached`).

Details worth saying in an interview:

- **Where the ledger lives:** Postgres, one row per UTC day, `INSERT … ON CONFLICT DO UPDATE`, so
  several API instances share one number (tested with 40 concurrent writes).
- **Check-then-add can overshoot** by the requests in flight. At ~$0.0001 per answer that's
  fractions of a cent; a hard guarantee would need a reservation per request.
- **Order:** guardrails → cache → cap → model. A cache hit costs nothing, so it still answers.
- **Economy answers are never cached**: they mustn't outlive the budget day that caused them.
- **Per deployment, not per user**: a per-user quota (Cognito `sub`) is the next step if one
  user can spend the day.

### 5. The refusal detector, again

Writing the routing tests exposed that incident 0009's hedged refusal, *"…are not explicitly
stated in the provided sources"*, still escaped `is_refusal` (no pattern for an adverb, for
"stated"/"listed", or for "provided sources"). Routing would never have escalated the very case it
exists for. The patterns are wider now, with tests for real answers using similar words. Expect
`answer.false_refusal_rate` to move up a little in the next evaluation: the metric got more
honest.

---

## Part 2: Build

Apply the zip, then:

```bash
uv sync
uv run mypy && make lint && make test && make obs-check
ollama pull qwen2.5:7b          # if it isn't there from Phase 5b
```

### Step 1: the experiments (about 1.5 hours, mostly waiting)

```bash
make eval-8b
```

Three evaluations against the current baseline (llama3.2, attributes layout, no routing):

- **A. `KB_PROMPT_LAYOUT=heading`:** does a visible "Section: Security > Design principles" line
  fix `sec-principles` for free?
- **B. `KB_ROUTE_ESCALATION_MODEL=qwen2.5:7b`:** routing. Read the case list: which cases say
  "(escalated from llama3.2)", and did they pass?
- **C. `KB_OLLAMA_CHAT_MODEL=qwen2.5:7b`:** the big model for everything, the upper bound.

Each run is saved to `eval/results/`. Fill in this table from the reports:

| Run | Pass | False refusals | Fact recall | Escalation rate | Escalations answered | Projected $/question | TTFT p50 | Total p95 |
|---|---|---|---|---|---|---|---|---|
| Baseline (llama3.2) | 97% | 4% | 73% | – | – | $0.000041 | 2.0 s | 7.1 s |
| A. headings | | | | – | – | | | |
| B. routing → qwen2.5:7b | | | | | | | | |
| C. qwen2.5:7b only | | | | – | – | | | |

**Decision rule** (write it down before you look):

- If **A** fixes `sec-principles` with no other change, keep the heading layout and leave routing
  off: same result for $0.
- Turn routing on if **B** reaches C's pass rate at well under C's cost and latency, with an
  escalation rate under ~10% and most escalations answered.
- If escalations mostly end in refusals, raise `KB_ROUTE_MIN_SIMILARITY` or leave routing off.

### Step 2: see an escalation

```bash
KB_ROUTE_ESCALATION_MODEL=qwen2.5:7b uv run kb ask "What are the design principles of the Security pillar?" --no-cache
```

Expect `[llama3.2 refused; asking qwen2.5:7b]`, the answer, and a line with both calls' tokens.

### Step 3: rehearse the spend cap

Put this in `.env` (local models cost $0, so count projected cost against a tiny budget):

```bash
KB_DAILY_BUDGET_USD=0.0003
KB_BUDGET_COST_BASIS=projected
```

Then ask different questions (`--no-cache`, or the cache answers for free):

```bash
uv run kb ask "What is a game day?" --no-cache
make budget-today
```

At about $0.00005 per answered question, the 6th answer comes back as **economy** (`spend cap:
economy`) and the 7th as **over budget** (the "limit reached" message, no model call). Then:

```bash
make app-up obs-up
```

Ask in the UI: the message, `KbSpendCapReached` in Prometheus' Alerts page, and the "Routing and
spend cap" dashboard row. **Remove both lines from `.env` afterwards** (the ledger keeps today's
total; it resets at 00:00 UTC).

---

## Part 3: Verify

- [ ] `make test` and `make obs-check` pass (11 rule tests).
- [ ] The experiment table is filled in and the decision written below it.
- [ ] An escalation shows in the CLI, and in the UI as "Larger model (llama3.2 couldn't answer)".
- [ ] The cap reached economy, then over budget; the UI showed the limit message, not "nothing found".
- [ ] `.env` is back to no cap.

## Results

Measured 27 Nov 2026, 37 cases, same retrieval in every run (hit rate 100%, MRR 81%).

| Run | Pass | False refusals | Fact recall | Escalation rate | Escalations passed | Projected $/question | TTFT p50 | Total p95 |
|---|---|---|---|---|---|---|---|---|
| Baseline (llama3.2) | 97% | 4% | 72% | – | – | $0.000041 | 2.1 s | 8.1 s |
| A. headings | 97% | 4% | 72% | – | – | $0.000043 (+8% input tokens) | 2.3 s | 8.1 s |
| B. routing → qwen2.5:7b | 97% | **0%** | 73% | 8% (2 cases) | **1 of 2** | $0.000047 (+15%) | 2.4 s | **21.5 s** |
| C. qwen2.5:7b only | **100%** | 0% | **80%** | – | – | $0.000079 (1.9×)* | 4.9 s | 22.5 s |

\* C priced on Nova Lite. The report said $0.000046: with routing off, the first version priced the
big model's tokens as Nova Micro. Fixed: `make eval-8b` sets the price for C, and every report now
says which model it was priced as.

**What happened in each run**

- **A, headings:** `sec-principles` still refused. +2,632 input tokens for no gain; citation
  validity rose (79% → 89%) and grounding fell (42%, below its measured noise), so the model
  wrote differently, not better. **Rejected.**
- **B, routing:** two escalations. `sec-principles` was escalated and **fixed** (the CLI showed
  qwen2.5:7b listing the four principles, citing p.396–397). `near-s3-replication` was escalated
  and **broken**: llama3.2's refusal was the right outcome (the documents mention replication but
  not the steps), and qwen2.5:7b answered, naming a term no source contains ("CLI"). Pass rate
  stayed at 97%: one failure traded for another. See incident 0017.
- **B's latency tail** is mostly local: on a 16 GB laptop Ollama unloads one model to load the
  other, so an escalated question waited for llama3.2's refusal *and* a model load (first token
  at 25 s in the CLI). The median didn't move (2.4 s). On Bedrock there's no model swap.
- **C, the big model for everything:** the quality ceiling (100% pass, 80% fact recall, 100%
  citation validity), at 1.9× the cost per question and 2.4× the time to first token.

**Decision** (against the rule written before the runs):

- Headings: off (didn't fix the case, cost more).
- Routing: **off**. It didn't reach C's pass rate, and the signal turned out to be weaker than
  expected: "refused with strong evidence" also describes a near-domain question, where the
  documents are relevant but don't hold the answer. Similarity can't separate the two:
  `near-s3-replication` (0.772) scores *higher* than `sec-principles` (0.742).
- Default stays llama3.2 locally. The production decision is Nova Micro vs Nova Lite on Bedrock:
  re-run B and C there in 6c-3, where there's no model swap and the latency picture changes.

**Changed after the runs:** `routing.escalations_answered` became `routing.escalations_passed`.
"Answered" counted the near-s3 escalation as a success.

---

---

## Interview framing

**"How do you decide which model answers?"** A cascade: the cheap model first, the larger one only
when the cheap one refuses although retrieval found strong evidence. Both conditions come from
measurements: a refusal alone also happens for questions that should be refused, and the evidence
bar sits in the similarity gap the evaluation showed. Every escalation pays for two calls, so the
evaluation reports the escalation rate and how many escalations actually answered.

**"How do you stop a runaway bill?"** A spend cap in the app, checked before every model call, with
a soft step (small model only, ticket) and a hard step (no model call, page), shared across
instances through a Postgres ledger. Cache hits still answer. AWS Budgets is the backstop, because
it's hours late and can only alert.

**"What surprised you?"** Building routing exposed a refusal pattern that a phase-5 incident had
named and that was still missed: the router would never have escalated the case it was built for.
Tests on the signal, not just on the router, caught it.
