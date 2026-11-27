# ADR 0019: Cascade routing on refusal with strong evidence, and a daily spend cap that degrades in steps

**Status:** Accepted, 2026-11-27 (Phase 8b). Defaults: routing off and no cap. **Measured
the same day: routing stays off** (see Consequences); the spend cap is ready to switch on at
deploy.

## Context

- The small model (llama3.2 locally, Nova Micro on Bedrock) answers 36 of 37 evaluation cases.
  The one it fails, `sec-principles`, is a reading failure: the right section is in the top 4,
  next to another "Design principles" list, and the model refuses. qwen2.5:7b answers it from
  the same sources (Phase 5b), but at about 2× time to first token and 2× total p95 time on a
  laptop, and on Bedrock Nova Lite costs about 1.7× Nova Micro per token.
- Searching again doesn't help (incident 0009): the evidence was already there.
- Costs have two failure modes: a slow drift (more tokens per question) and a spike (traffic,
  abuse, a loop). AWS Budgets (Phase 0) sees both hours late and can only alert.

## Decision

### Routing: a cascade, not a classifier

- Ask the small model first. If its answer **is a refusal** (`is_refusal`: "not found" in any
  phrasing and no valid citation) **and the best retrieved chunk scores at least
  `KB_ROUTE_MIN_SIMILARITY`** (0.70), send the **same prompt with the same sources** to
  `KB_ROUTE_ESCALATION_MODEL`, once. Otherwise the small model's answer stands.
- The similarity condition is what incident 0009 lacked: weak evidence means the refusal is
  probably right (the Azure question scores 0.666), and a bigger model would refuse at a higher
  price. Injections never get here: the input screen blocks them first (Phase 7b).
- Streaming: while escalation is possible, tokens are held back only while the text could still
  be the exact "not found" sentence, so a typical refusal never reaches the screen and an
  answer streams as soon as it diverges (a few tokens). A hedged refusal that has already
  streamed is replaced: the stream sends `escalate` with `reset: true`.
- Both calls are paid for and counted: the answer records the first model's usage
  (`Answer.escalation`), the API returns the total, metrics count each model's tokens, and the
  evaluation prices the first call on `KB_PROJECTED_PRICE_MODEL` and the second on
  `KB_PROJECTED_PRICE_MODEL_LARGE`.

### Spend cap: three levels, checked before every model call

| Spent today (UTC) | Behaviour |
|---|---|
| < 80% of `KB_DAILY_BUDGET_USD` | normal: routing may escalate |
| 80–100% | **economy**: the small model only; answers marked, never cached |
| ≥ 100% | **over budget**: no model call, a clear "limit reached" message; exact cache hits still answer |

- The ledger is a Postgres table (`kb_spend`, one row per UTC day, atomic upsert), so every
  API instance agrees; the database decides the day.
- Order: guardrails → cache → spend cap → model. A cache hit is free, so it answers past the cap.
- `over_budget` is its own outcome: not an error (it's deliberate), not a refusal (the
  knowledge base wasn't asked), and it pages (`KbSpendCapReached`): a deliberate outage is
  still an outage.
- `KB_BUDGET_COST_BASIS=projected` counts local tokens at hosted prices, to rehearse the cap
  without a bill. `KB_DAILY_BUDGET_USD=0` is a kill switch.

## Why

| Option | Verdict |
|---|---|
| Always the large model | Simple, ~2× slower and ~1.7× the price for every question, to fix 1 in 37 |
| **Cascade on refusal with strong evidence** | **Chosen**: pays extra only where the small model failed, with a signal measured in incidents 0006/0009 |
| A router model or classifier up front ("is this question hard?") | Another model to train, run and evaluate; no labelled data for "hard"; misroutes cost both ways |
| Route by question type (lists, comparisons) | Brittle rules; `sec-principles` is a list question, so are 4 others the small model answers |
| Cascade on any refusal | Incident 0009: spends the big model on questions that should be refused |
| Hard cap only (stop at 100%) | Users go from full service to none; the soft level buys time and an alert first |
| Rely on AWS Budgets | Hours late, alerts only; it stays as the backstop |

## Consequences

- An escalated question pays for two calls and waits for both (the small one is short when it
  refuses). The evaluation reports `routing.escalation_rate` and
  `routing.escalations_passed` (not "answered": for a question the documents don't cover,
  answering is the failure).
- **Measured (llama3.2 → qwen2.5:7b, 37 cases):** 8% escalated (2 cases), 1 of 2 passed.
  `sec-principles` fixed; `near-s3-replication` broken (a correct refusal became an answer with a
  term no source contains; incident 0017). Pass rate unchanged at 97%, projected cost +15%, total
  p95 8.1 s → 21.5 s locally (Ollama swaps models on a 16 GB laptop). The signal can't tell
  "failed to read" from "relevant but not covered": the broken case scored higher (0.772) than the
  fixed one (0.742). Routing stays off; re-measure as Nova Micro → Nova Lite on Bedrock.
- Routing depends on refusal detection. Building it showed that incident 0009's hedged refusal
  ("…are not explicitly stated in the provided sources") still escaped `is_refusal`: fixed in
  this phase, with tests for real answers that use similar words. Some answers counted as
  answers before will now count as refusals: false refusals may rise slightly. That's the
  metric getting more honest, not the model getting worse.
- The check-then-add cap can overshoot by (requests in flight × cost of one answer). At
  ~$0.0001 per answer that's fractions of a cent; a reservation per request would be needed
  for a hard guarantee.
- The cap is per deployment, not per user. Per-user quotas (Cognito `sub`) are the next step if
  one user can exhaust the day.
- `prompt_layout=heading` (a visible "Section: …" line per source) is shipped as an experiment:
  the default changes only if the evaluation says so.
