# ADR 0020: Web UI: Vite + React, same-origin API, model output rendered as text

**Status:** Accepted, 2026-11-21

## Context

Phase 2b adds a browser UI for `POST /ask/stream` (ADR 0008). It must show the
answer as it is written, let the reader check every citation, and be cheap to host.
Two things make it more than a form: the answer is **untrusted text** (it is built
from retrieved documents, which can carry injected instructions, OWASP LLM01), and
from Phase 2c every request carries a Cognito token.

## Decision

1. **Vite + React + TypeScript (strict), static build.** No server-side rendering.
   In AWS the build is static files on S3 behind CloudFront (Phase 6).
2. **Same origin.** The UI calls `/api/...`. In development the Vite dev server
   forwards `/api` to FastAPI; in AWS, CloudFront routes `/api/*` to the API. The
   API therefore needs no CORS configuration.
3. **Streaming with `fetch` and our own SSE reader**, not `EventSource`.
   `EventSource` only does GET and cannot send an `Authorization` header.
   `AbortController` powers a Stop button, and the API stops generating when the
   connection closes (`stop_on_disconnect`), so abandoned answers stop costing tokens.
4. **Model output is never inserted as HTML.** A ~60-line parser turns the answer
   into paragraphs, lists, bold text and `[n]` citations, all rendered as React
   elements. No `dangerouslySetInnerHTML`, no Markdown-to-HTML library.
5. **Citations are checked in the UI.** `[n]` becomes a button only if source *n*
   was retrieved; any other number is shown struck through. Sources the answer
   did not cite are dimmed once the answer is complete.
6. **Tooling:** Vitest + Testing Library, oxlint, Prettier, `npm ci` from a lockfile,
   Dependabot for npm, `npm audit` in CI. Plain CSS with variables (light and dark).

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| Next.js | SSR and a Node server add hosting cost and moving parts; nothing here needs SEO or server rendering. |
| `EventSource` | GET only, no headers: fails the Cognito requirement in Phase 2c and puts questions in URLs. |
| `@microsoft/fetch-event-source` | Little maintenance activity; the part we need is small enough to own and test (including chunk splits, `\r\n` splits and split UTF-8 characters). |
| `react-markdown` | Safe by default, but citations would need a custom plugin, and we only need lists, paragraphs and bold. Revisit if answers need tables or code blocks. |
| CORS on the API | Same-origin removes a class of misconfiguration (for example `allow_origins=["*"]` with credentials). |
| Tailwind / a component library | Not needed for one screen; adds build config and dependencies. |
| Runtime schema validation (zod) | Deferred: both sides are in this repo and the shapes are covered by tests on each side. Worth adding if the API is consumed by other clients. |

## Consequences

- One more toolchain (Node 22) in CI and on developer machines.
- The SSE event shapes are a contract between `apps/api` and `apps/web`; both
  sides have tests for them, and unknown events are ignored by the UI so the API
  can add new ones.
- The struck-through citation makes model citation errors visible to users, which
  is honest but also visible in demos. Phase 3 measures citation accuracy.
- `scripts/demo_api.py` runs the real API with a scripted answer, so the UI can be
  developed and demoed without Ollama, Bedrock or a database.
