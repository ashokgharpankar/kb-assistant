# ADR 0016: Prometheus metrics and Grafana dashboards; traces stay in Langfuse

**Status:** Accepted, 2026-11-27 (Phase 7a).

## Context

Langfuse (Phase 2a) records a trace per request: the retrieved chunks, the prompt, the
answer, tokens and cost. That answers "why was this answer bad?". It doesn't answer "how
are all answers doing right now, and is it getting worse?", and it can't page anyone.
LLM apps need the usual service signals (rate, errors, latency) plus their own: time to
first token, refusals, tokens and cost per answer, and retrieval quality drift.

## Decision

- The API exposes **Prometheus metrics** at `/metrics` with `prometheus-client`, in its own
  registry. HTTP metrics are labelled by route template; answer metrics by endpoint, mode,
  outcome and model. No user, question or token text in any label.
- **Prometheus** scrapes it and evaluates recording rules and alerts kept in the repo, with
  `promtool` unit tests in CI. **Grafana** shows one provisioned dashboard (JSON in the repo).
  Both run locally in Docker next to the app containers.
- Alerts follow an **SLO**: 99% of answers without an error over 30 days, with multi-window
  burn-rate alerts (fast: 14.4×, slow: 6×), plus symptom alerts for time to first token,
  refusal ratio and model spend.
- `/metrics` isn't public: nginx only routes `/api/`, and in AWS the load balancer reaches
  only the web container.

## Why

| Option | Verdict |
|---|---|
| **Prometheus + Grafana, rules and dashboards as code** | **Chosen**: open standard, runs locally at $0, the same queries work on Amazon Managed Service for Prometheus later |
| Langfuse only | Rejected: per-request traces, no aggregation over time or alerting on rates |
| CloudWatch metrics now | Deferred: the app isn't in AWS yet (Bedrock blocked). Embedded Metric Format or the CloudWatch agent's Prometheus scraping are the AWS path |
| OpenTelemetry SDK for metrics | Deferred: more moving parts for one service. Prometheus exposition is also what an OTel collector scrapes, so this doesn't block a later move |
| Summaries instead of histograms | Rejected: summaries can't be aggregated across instances; histograms can, at the cost of approximate percentiles |

## Consequences

- Percentiles come from histogram buckets, so they're estimates (between bucket edges).
  The buckets are chosen to cover both a slow local model and a fast hosted one.
- Stream failures return HTTP 200 (the headers are already sent), so the error SLI counts
  answer outcomes, not status codes. HTTP 5xx is a separate panel.
- One process per container assumed. Several uvicorn workers would need
  prometheus-client's multiprocess mode.
- In AWS: Amazon Managed Service for Prometheus + Amazon Managed Grafana, or CloudWatch.
  Decided when the app is deployed (6c-3).
