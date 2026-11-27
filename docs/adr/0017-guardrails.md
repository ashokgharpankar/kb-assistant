# ADR 0017: Guardrails in code around every answer; Bedrock Guardrails when available

**Status:** Accepted, 2026-11-27 (Phase 7b).

## Context

The assistant already refuses most injections and off-topic questions, but only because the
model follows its system prompt, and a stronger model followed an injection the weaker one
refused (incident 0010). Refusal detection matched one exact sentence, so a hedged
non-answer counted as an answer (incident 0009). Nothing checked whether an answer's
sentences were backed by the sources it cited, and in Phase 6b the model named an Azure
storage option ("LRS") in an answer about S3. Bedrock, and with it Bedrock Guardrails, is
still blocked (incident 0002).

## Decision

Wrap every answerer (pipeline and agent) with three deterministic checks in code:

1. **Input screen** before retrieval: patterns for instructions aimed at the assistant
   (override rules, mode switches, role changes, prompt extraction, "answer without sources",
   fake markup). Blocked questions get "not found" with no retrieval and no model call ($0).
   Patterns describe *instructions*, never single words: architecture questions use
   "system", "ignore" and "rules" all the time.
2. **Refusal detection** by meaning, not one sentence: "not found" in several phrasings
   *and* no valid citation. An answer that cites a retrieved source is an answer.
3. **Grounding check** after generation: each claim (sentence with 3+ content words) must cite
   a retrieved chunk and share at least half its content words with the chunks it cites. Terms
   (acronyms, product names) found in no retrieved chunk are listed. Results go to the API
   response (the UI warns), Prometheus, Langfuse and the evaluation.

`KB_GUARDRAILS=false` turns them off, to measure the model alone.

## Why

| Option | Cost per answer | Latency | Verdict |
|---|---|---|---|
| **Rules and lexical checks in code** | $0 | < 1 ms | **Chosen now**: run on every request, testable, explainable |
| LLM judge for grounding on every answer | One more model call (~doubles cost) | +1–3 s | Kept offline (`kb eval --judge`) |
| Bedrock Guardrails (prompt-attack filter, contextual grounding check, denied topics, PII) | Per text unit | ~100s of ms | **Next**, once Bedrock works: managed, broader, maintained by AWS |
| Prompt rules only | $0 | 0 | Rejected as the only layer: incident 0010 |
| Block on single words ("ignore", "system") | $0 | 0 | Rejected: false positives on real questions (tested) |

## Consequences

- The screen is a pattern list: rephrased attacks get past it. The system-prompt rule stays as
  the second layer, and the evaluation keeps measuring injection resistance end to end.
- Lexical grounding misses paraphrase (supported but differently worded) and can't judge
  meaning. It's a cheap signal for metrics and alerts; the LLM judge and Bedrock's contextual
  grounding check are the stronger tools.
- Answers are flagged, not withheld: the answer has already streamed when the check runs.
  Withholding needs buffering (worse time to first token) or Bedrock Guardrails on the stream.
- Hedged non-answers now count as refusals, so the false-refusal rate can rise: more honest,
  not worse.
