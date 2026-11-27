# Incident 0017: Routing fixed one case and broke another; the escalation answered a question it should refuse

**Date:** 2026-11-27 · **Phase:** 8b · **Severity:** low (caught by the evaluation; routing was off by default)
**Status:** Decided: routing stays off; metric fixed; re-measure on Bedrock

## Summary

Cascade routing sends a question to the larger model when the small one refuses while retrieval
found strong evidence (best chunk ≥ 0.70). On the 37-case evaluation it escalated two questions.
One was the case it was built for (`sec-principles`), and qwen2.5:7b answered it correctly. The
other was `near-s3-replication`, a near-domain question: the documents discuss S3 replication but
don't give the setup steps it asks for. llama3.2's refusal was the right outcome. qwen2.5:7b
answered, and named a term no retrieved source contains ("CLI"). Pass rate: 97% before and after.

## Evidence

| Case | Top similarity | llama3.2 | After escalation to qwen2.5:7b |
|---|---|---|---|
| `sec-principles` (answerable) | 0.742 | refused (wrong) | four principles, cited p.396–397 (right) |
| `near-s3-replication` (near-domain) | **0.772** | refused (right) | answered, unknown term "CLI" (wrong) |

- `routing.escalations_answered` read **100%**: it counted the broken case as a success.
- In run C (qwen2.5:7b for everything) the same near-s3 question passed, without "CLI": the
  larger model is borderline on it, not consistently wrong.

## Root cause

- **The escalation signal has the same blind spot as the similarity floor** (incident 0006):
  similarity measures topic, not whether the answer is in the text. A near-domain question has
  strong topical evidence and no answer, so it looks exactly like "the model failed to read".
  Here the broken case scored *higher* than the fixed one, so no threshold separates them.
- **Larger models are more willing to answer.** Incident 0010 showed it for injections; here it's
  a question the documents only partly cover.
- **The metric measured the action, not the outcome.** "Answered" is success for an answerable
  question and failure for a near-domain one.

## Resolution

- Routing stays off by default (ADR 0019); the decision rule written before the runs wasn't met.
- `routing.escalations_answered` → `routing.escalations_passed` (each case's own check), with a
  test using exactly this pair.
- The grounding check did its job: the answer would have reached a user with a "not clearly
  supported" warning, not silently.

## What we learned

1. A cascade inherits every weakness of its trigger. "Refused with evidence" is a better trigger
   than "refused" (incident 0009), and still not good enough.
2. A bigger model fixes reading failures and creates willingness failures. Measure both.
3. Name metrics after outcomes, not actions: "escalations answered" rewarded the mistake.
4. Pass rate flat can hide one fix and one break. Read the case list.

## Interview version

"I added routing: if my small model refuses while the evidence is strong, ask a bigger model. It
fixed the case it was built for, and broke another. A question the documents only partly cover
had been correctly refused; the bigger model answered it and named something the sources don't
contain. Pass rate stayed flat, and my 'escalations answered' metric said 100%, because it
counted the break as a success. I renamed it to measure outcomes and kept routing off. The trigger
can't tell 'failed to read' from 'not covered': the broken case actually had the higher
similarity."

## Links

- `docs/phase-8b-routing-budget.md` (Results), ADR 0019, incidents 0006, 0009, 0010
- `eval/results/20261127T175217Z-llama3.2.json` (run B)
