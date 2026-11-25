# ADR 0012: An MCP server for retrieval only

**Status:** Accepted, 2026-11-25 (Phase 5a)

## Context

Phase 5 turns the assistant from a fixed pipeline (embed → retrieve → generate) into
something an agent can use: search, read around a hit, search again, then answer. Two
kinds of caller need the knowledge base:

- our own agent (Phase 5b, LangGraph), and
- other MCP clients: Claude Desktop, Claude Code, the MCP Inspector, other teams' agents.

The Model Context Protocol (MCP) standardises how a client discovers and calls tools,
with typed input and output schemas, over stdio or HTTP. Writing one server serves every
client; writing one integration per client doesn't scale.

## Decision

1. **A separate app, `apps/mcp` (`kb-mcp`)**, built on the official Python SDK (`mcp` 2.x,
   `MCPServer`). It reuses `kb_core`'s `Retriever`, so MCP callers get exactly the
   strategy the evaluation measured (hybrid, floor 0.62).
2. **Three read-only tools**, all annotated `readOnlyHint`, `idempotentHint`, not
   destructive, closed world:
   - `search_knowledge_base(query, k=4)`: passages with document, heading path, page,
     similarity and `chunk_id`; an empty list plus a note when nothing clears the floor.
   - `get_context(chunk_id, before=1, after=1)`: the passage and its neighbours.
   - `list_documents()`.
3. **Retrieval, not answers.** No `ask` tool: the caller's model writes the answer.
4. **Structured output.** Each tool returns a Pydantic model, so clients get an output
   schema and JSON, not prose to parse.
5. **Limits enforced twice**: in the JSON schema (query ≤ 1,000 characters, k 1–10, window
   ≤ 3) and in the tool code. Bad input is a tool error the model can read and correct,
   rejected before any embedding cost.
6. **Transports:** stdio by default (the client launches the server); streamable HTTP
   only on 127.0.0.1 until Phase 6 adds Cognito token checks. The server refuses any
   other address rather than run open.
7. **Untrusted text is labelled.** Server instructions and every search result say that
   passages are data, not instructions.

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| An `ask` tool that returns a generated answer | Two models in a row (the caller's and ours): double cost and latency, and the caller can't see or cite the evidence. Can be added later for clients without a strong model. |
| Expose the FastAPI `/ask` endpoint as the "tool" | Not discoverable, no schemas, streaming SSE that agent frameworks don't expect. |
| One tool per pillar or document | Tool lists cost tokens on every call and confuse tool choice; one search tool with good descriptions scales. |
| Write tools (ingest, delete) over MCP | A model should not be able to change the knowledge base. Ingestion stays a CLI/pipeline job. |
| `mcp` 1.x (`FastMCP`) | 2.x is current; the rename and API changes would be a migration later. |
| Third-party FastMCP 2 | More features (auth providers, proxies) we don't need yet; the official SDK is enough. |

## Consequences

- A new workspace member and dependency (`mcp`); `uv.lock` changes.
- `PgVectorStore` gains `chunk_window()` and `documents()`, both read-only.
- MCP calls are not traced in Langfuse yet; the agent (5b) traces its own tool calls.
- No authentication on HTTP: local use only until Phase 6.
- Tool output is prompt input for the caller's model: an indirect prompt-injection path.
  Mitigated by labelling and read-only tools (worst case: a wrong answer, not an action);
  guardrails come in Phase 7.
