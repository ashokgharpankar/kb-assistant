# Incident 0016: Cancelled streams sat outside the answer outcomes, and "it stops the model" was untested

**Date:** 2026-11-27 · **Phase:** 7a (found) / 8a (fixed) · **Severity:** low (no user impact; measurement and cost risk)
**Status:** Fixed: `outcome="cancelled"`, SLO excludes it, end-to-end cancellation test against a fake model server

## Summary

A reader commented on the observability write-up: when a user closes the tab mid-stream,
count it as its own outcome, not as an error, or it eats the error budget; and make sure the
disconnect actually cancels the upstream model call, or you keep paying for tokens nobody reads.

Checking the code: neither was broken, but both were weaker than the write-up implied.

## Evidence

- Disconnects went to a separate counter, `kb_stream_disconnects_total`, so they didn't
  spend the error budget. They were also missing from `kb_answers_total`: the outcomes didn't
  add up to all requests, and the error-ratio denominator silently left them out instead of
  excluding them on purpose.
- `stop_on_disconnect` closed our generator, and a test proved our loop stopped. But the test
  used a fake Python generator. Nothing proved that the **model client's HTTP stream** was
  closed, which is what actually stops generation on the model server.
- Removing the explicit `close()` call (a deliberate mutation) still passed that test. Against
  a model server, it doesn't: the parked generator keeps the HTTP stream open and the server
  keeps generating. The cleanup line was carrying the cost guarantee, and no test covered it.

## Root cause

The SLI design was right in intent (disconnects aren't faults) but recorded them beside the
outcome model, not inside it. And the cancellation test stopped one link short of the system
boundary: it tested our code, not the connection to the provider.

## Resolution

- New outcome `cancelled` in `kb_answers_total` (`metrics.record_cancelled`); the separate
  disconnect counter is gone. A disconnect after the final `done` event isn't counted: the
  answer was complete.
- Recording rules exclude it explicitly: error ratio `error / (all − cancelled)`, refusal ratio
  and the refusal alert's volume guard exclude `error|cancelled`. A promtool test: 9 answered,
  1 error and 40 cancelled per minute gives a 10% error ratio, not 2% (diluted) or 82% (counted
  as errors). The "Streams stopped by the user" panel reads the outcome.
- `apps/api/tests/test_cancellation.py`: the real pipeline and LangChain's `ChatOllama` against
  a fake Ollama server that streams `/api/chat` like Ollama and records how much it sent. The
  browser leaves after 10 events; the test asserts the server saw the disconnect, sent fewer
  than a quarter of the 400 tokens, never finished, and the outcome is `cancelled` with no
  error counted. A second test: a stream read to the end is `answered`, not `cancelled`.
- Mutation check: with `close()` removed, the new test fails ("server never saw the disconnect").
- `KB_TEST_OLLAMA_URL` runs the same flow against a real Ollama.

## What we learned

1. Every request should land in exactly one outcome, and the SLO says which outcomes it
   excludes. A counter beside the outcomes is an exclusion nobody wrote down.
2. Test cancellation to the system boundary: "our loop stopped" isn't "the provider stopped".
3. A test that still passes when you delete the line it's meant to protect isn't protecting it.
   Mutate the line once and watch the test fail.
4. The provider is the last link: closing the HTTP stream is all a client can do. Whether
   Ollama and Bedrock stop generating, and billing, is their side; check Bedrock's in 6c-3
   (`ConverseStream` with a large max tokens, close early, compare output tokens billed).
5. Public write-ups get reviewed. A reader found in one paragraph what my tests didn't.

## Interview version

"A reader of my blog pointed out that cancelled streams shouldn't spend the error budget, and
that closing the tab must actually stop the model. I checked: disconnects were already kept out
of errors, but in a side counter, so my outcomes didn't add up and the SLO excluded them by
accident. And my cancellation test used a fake generator. When I deleted the cleanup line, the
test still passed. I made `cancelled` a first-class outcome excluded explicitly from the SLO,
with a rule test, and wrote an end-to-end test with a fake model server. It proves the server
sees the disconnect and stops after a fraction of the tokens, and it fails if the cleanup line
is removed."

## Links

- `apps/api/src/kb_api/main.py` (`stop_on_disconnect`), `apps/api/src/kb_api/metrics.py`
- `apps/api/tests/test_cancellation.py`, `infra/observability/prometheus/tests/kb-assistant.test.yml`
- ADR 0016, `docs/phase-7a-observability.md`, `docs/phase-8a-cost-cache.md`
