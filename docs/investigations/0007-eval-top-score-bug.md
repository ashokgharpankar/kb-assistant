# Incident 0007: The evaluation misreported top scores under hybrid search; latency false alarms

**Date:** 2026-11-24 · **Phase:** 4 · **Severity:** medium (misleading metrics), caught before use
**Status:** Fixed; ADR 0010 amended; corrected the same day (see "Correction")

## Summary

Two problems in the evaluation tooling, found while comparing Phase 4 runs:

1. Under hybrid search, `kb eval` reported each question's "top score" from the **first**
   retrieved chunk, which isn't the most similar one any more. The floor analysis worked on the
   wrong numbers.
2. Median time to first token was flagged as a regression twice, from normal laptop timing noise.

## 1. The top-score bug

| | Run A (vector) | Run B (hybrid), before the fix | Run B, after the fix |
|---|---|---|---|
| `rel-principles` top score | 0.806 | 0.734 | 0.770 |
| Gap between the groups | | −0.009 | +0.007 |
| `floor.off_topic_rejected` | 40% | 50% | 50% |

Every top score dropped when only the ranking had changed, which is what gave it away.

**Cause:** the evaluation assumed "first result = best match". True for vector search; false for
hybrid search and reranking, where the order comes from fused ranks or relevance scores.
The pipeline itself was never affected: it applies the floor to every chunk.

**Fix:** top score = the **highest** similarity among the retrieved chunks; a test uses a fused
order whose first chunk isn't the most similar.

### Correction

The first version of this report blamed the bug for the rise in `off_topic_rejected` (40% → 50%)
and predicted the fix would bring it back to ~40%. The re-run showed **50% after the fix too**.
The bug changed the top scores and the gap, not the rejected share at the 0.62 floor. The 50% is
real: hybrid search retrieves a different set of chunks, and for some off-topic questions the
most similar chunk in that set scores lower than vector search's best one would.

The lesson applies to the write-up as much as the code: a predicted effect is a hypothesis
until the re-run confirms it.

## 2. Latency false alarms

Median time to first token: 1.19 s (baseline) → 1.72 s (run A) → 1.93 s (run B), while the
95th percentile stayed flat (2.57 → 2.25 → 2.55 s) and total time improved. Input tokens rose
only ~50 per question. The baseline was a fast run; local timings vary with what else the laptop
is doing.

**Fix:** latency is reported but only counts as a regression with `kb eval --gate-latency`,
meant for CI against a hosted model (Phase 7). A gate that raises false alarms teaches people
to ignore it.

## What we learned

1. When the system under test changes, re-check the evaluation's assumptions about it.
2. Distrust changes you didn't cause, in either direction.
3. Confirm a fix's predicted effect by re-running; don't write it down first.
4. Only gate on metrics that are stable where the gate runs.

## Interview version

"After switching to hybrid search, every top similarity score in my evaluation dropped, though
only the ranking had changed. The evaluation took the first result as the best match, true for
vector search but not after fusion. I fixed the metric, added a test and amended the evaluation
decision. I'd also predicted the fix would change another number; the re-run showed it didn't,
so I corrected the write-up. A predicted effect is a hypothesis until you re-run."

## Links

Phase 4 guide ("Problems found while measuring") · ADR 0010 (amendments) ·
`packages/kb_core/src/kb_core/evaluation/runner.py`, `report.py`
