# ADR 0008: Streaming responses over Server-Sent Events

**Status:** Accepted, 2026-11-21

## Context

A full answer takes several seconds to generate. Users judge speed by when the
first words appear, not when the last one does. The UI (Phase 2b) needs answer
text as it is produced, plus the sources and final metadata.

## Decision

- `POST /ask/stream` returns `text/event-stream` with three event types, in order:
  `sources` (once), `token` (many), `done` (once, the same JSON as `POST /ask`),
  or `error`.
- Each `data:` line is JSON, so newlines inside tokens cannot break the framing.
- The pipeline is a generator (`RagPipeline.stream`); `answer()` simply consumes it,
  so there is one code path for both endpoints.
- Record **time to first token** (TTFT) alongside retrieval and total latency.
- `Cache-Control: no-cache` and `X-Accel-Buffering: no` so proxies don't buffer.

## Why

- SSE is one-way server-to-client over plain HTTP: no extra protocol, works through
  load balancers and CloudFront, easy to test with `curl -N`.
- POST (read with `fetch` and a stream reader in the browser) rather than GET
  `EventSource`, because questions don't belong in URLs or access logs.
- Sending sources first lets the UI show citations while the answer is still being written.

**Rejected:** WebSockets (two-way, more infrastructure, nothing to send back
mid-answer); long polling (slow, wasteful).

## Consequences

- Once streaming starts the HTTP status is already 200, so failures arrive as an
  `error` event and clients must handle it.
- Compute behind the API must allow long-lived responses: fine on Fargate behind
  an ALB; a constraint for Lambda (ADR 0014, planned).
- Target to monitor from Phase 7: p95 TTFT under 2 seconds.
