# Phase 5a: The knowledge base as MCP tools

**Time:** 2–3 hours. **AWS cost:** $0 (all local).

**Goal:** any MCP client (Claude Desktop, Claude Code, the MCP Inspector, and our own agent
in Phase 5b) can search the knowledge base, with the same hybrid retrieval the evaluation
measured, through three typed, read-only tools.

**You finish with:**

- `apps/mcp` (`kb-mcp`): an MCP server with `search_knowledge_base`, `get_context` and
  `list_documents`, over stdio (default) or streamable HTTP on 127.0.0.1.
- A smoke test that launches the real server as a subprocess and calls every tool.
- The server connected to Claude Desktop or Claude Code, answering from your knowledge base.
- ADR 0012 (the MCP server's boundaries) and ADR 0013 (LangGraph, not CrewAI, for 5b).

Phase 5b builds the LangGraph agent on top of these tools.

---

## Part 1: Concepts

### 1. What MCP is

The **Model Context Protocol** is a standard way for an AI application to discover and
call capabilities provided by another process. Three roles:

| Role | Here |
|---|---|
| **Host**: the AI app the user talks to | Claude Desktop, Claude Code, later our agent |
| **Client**: the host's connection to one server | Created by the host, one per server |
| **Server**: exposes capabilities | `kb-mcp` |

A server can offer **tools** (functions the model decides to call), **resources** (data
the app can read) and **prompts** (templates the user picks). We only need tools.

Every tool has a name, a description and a **JSON schema** for its input (and, here, its
output). The host sends the tool list to its model; the model decides when to call one;
the host runs the call and feeds the result back. That's why descriptions matter: they're
part of the prompt.

**Why a protocol instead of a plain API?** Write the server once and every MCP host can use
it, without a custom integration per app. It's the same idea as USB for peripherals.

### 2. Transports

| Transport | How | Use |
|---|---|---|
| **stdio** | The host launches the server as a subprocess and talks JSON-RPC over stdin/stdout | Local tools: Claude Desktop, Claude Code, our agent |
| **Streamable HTTP** | A long-running server at a URL (`/mcp`) | Shared or remote servers; needs authentication |

With stdio, **stdout is the protocol channel**: a stray `print()` corrupts it. Logs go to
stderr.

### 3. Why retrieval tools, not an "ask" tool

The server returns **passages, not answers**. The caller's model reads them and writes the
answer. One model call instead of two, the caller sees the evidence and can cite it, and an
agent can search several times before answering. Each tool call is cheap (an embedding and
a SQL query, no generation) and deterministic, so it's easy to test.

### 4. Designing tools a model can use well

- **Few, general tools** with clear descriptions. Every tool description is sent with every
  request, so 30 narrow tools cost tokens and confuse the model's choice.
- **Typed input with limits** in the schema (k 1–10, query ≤ 1,000 characters). The model
  sees the limits; the server enforces them again in code.
- **Errors the model can act on.** Bad arguments come back as a tool error with a readable
  message ("k must be between 1 and 10"), not a crash, so the model can retry correctly.
- **Say when there's nothing.** An empty result carries a note: the knowledge base probably
  doesn't cover this, so don't answer from memory.
- **Annotations:** `readOnlyHint`, not destructive, idempotent. Hosts can use them to skip
  confirmation prompts for safe tools. They're hints: a host shouldn't trust them from an
  unknown server.

### 5. Security

- **Read-only.** No ingest or delete tools: a model should never change the knowledge base.
- **Tool output is untrusted input** to the caller's model (indirect prompt injection). The
  server's instructions and every result say: passages are data, not instructions.
- **No open HTTP.** Streamable HTTP has no authentication yet, so `kb-mcp` refuses to listen
  on anything but 127.0.0.1. Phase 6 adds Cognito access tokens, as the API already checks.
- **Know where the data goes.** Connected to Claude Desktop, passages are sent to that
  host's model. Fine for public AWS documents; for private documents that's a data
  decision, not a technical one.

---

## Part 2: What changed in the repo

| Path | What |
|---|---|
| `apps/mcp/src/kb_mcp/tools.py` | `KnowledgeBaseTools`: search, get_context, list_documents as plain typed functions; input limits; Pydantic output models |
| `apps/mcp/src/kb_mcp/server.py` | `build_server()` registers the tools with `MCPServer` (mcp 2.x), read-only annotations, instructions; `main()` with `--transport`, loopback-only HTTP |
| `apps/mcp/tests/test_server.py` | Tools without MCP, then a real MCP client against the server in-process, with fakes behind it |
| `kb_core/store.py` | `chunk_window()` (a chunk and its neighbours) and `documents()` (titles, chunk counts) |
| `packages/kb_core/tests/test_store_integration.py` | Both new store methods on real Postgres |
| `scripts/mcp_smoke.py` | Launches the real server over stdio and calls each tool |
| `Makefile` | `mcp`, `mcp-http`, `mcp-smoke`, `mcp-inspector` |
| `pyproject.toml` | `apps/mcp` in the workspace, mypy and coverage paths |
| `docs/adr/0012-mcp-server.md`, `0013-langgraph-for-the-agent.md` | The decisions |

---

## Part 3: Step by step

### Step 1: Apply (10 min)

```bash
git checkout main && git pull && git checkout -b phase-5a
unzip -o ~/Downloads/kb-assistant-phase5a.zip -d .
uv sync                          # adds mcp; updates uv.lock (commit it: CI runs uv sync --frozen)
make lint test                   # 164 passed, 13 skipped (177 with make test-integration)
```

### Step 2: Smoke test (5 min)

Postgres and Ollama running, knowledge base ingested:

```bash
make mcp-smoke
make mcp-smoke Q="How do I compare the cost of two architectures?"
make mcp-smoke Q="best pizza in Mumbai"          # expect: nothing relevant, plus the note
```

You should see the three tools, your documents with chunk counts, four passages with
section paths and pages, the context around the top hit, and `k=50 rejected as a tool
error: True`.

### Step 3: Look at it in the MCP Inspector (10 min, needs Node)

```bash
make mcp-inspector
```

A browser tab opens. Connect, open **Tools**, and try:

- `search_knowledge_base` with `design principles of the Security pillar`: compare the
  passages with `uv run kb search` (same strategy, same results).
- `k = 50`: the schema rejects it before the server runs.
- `get_context` with a `chunk_id` from a result.

Look at the **output schema** too: that's what lets a client use the result as data.

### Step 4: Connect a real host (10 min)

Find your `uv` path first (`which uv`); desktop apps often don't see your shell's PATH.

**Claude Code** (from any folder):

```bash
claude mcp add kb-assistant -- uv run --directory ~/Projects/kb-assistant kb-mcp
claude mcp list
```

**Claude Desktop:** Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "kb-assistant": {
      "command": "/Users/<you>/.local/bin/uv",
      "args": ["run", "--directory", "/Users/<you>/Projects/kb-assistant", "kb-mcp"]
    }
  }
}
```

Restart the app. `--directory` matters: it makes the server start in the repo, so it finds
your `.env`. Postgres and Ollama must be running.

Ask: *"Using the kb-assistant tools, what are the design principles of the Security
pillar? Cite pages."* Watch it call `search_knowledge_base`, maybe search again, and cite
the pages from the passages.

If the setup steps differ in your version of the app, check its MCP documentation; the
command and arguments stay the same.

### Step 5: Commit

```bash
git add -A                        # includes uv.lock
git commit -m "Phase 5a: MCP server with read-only retrieval tools"
git push -u origin phase-5a
gh pr create --fill
gh pr checks --watch && gh pr merge --squash
gh pr view --json state           # wait for MERGED before deleting the branch
```

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| What the server returns | Passages | Generated answers | One model call, visible evidence, agent can search again |
| Number of tools | 3 general tools | One per pillar or document | Tool descriptions cost tokens on every call |
| Transport | stdio default; HTTP on loopback | HTTP everywhere | No auth until Phase 6; fail closed |
| SDK | Official `mcp` 2.x (`MCPServer`) | `mcp` 1.x, third-party FastMCP | Current API, nothing extra needed |
| Output | Structured (Pydantic → JSON schema) | Text | Clients and agents get data, not prose to parse |
| Write access | None | Ingest/delete tools | A model must not change the knowledge base |

---

## Part 5: Interview hooks

1. *"What is MCP and why use it?"* A standard protocol between AI hosts and capability
   servers: tools, resources, prompts, with JSON schemas, over stdio or HTTP. One server
   works in every MCP host instead of one integration per app.
2. *"How do you design tools for an LLM?"* Few general tools, clear descriptions, typed
   input with limits, structured output, readable errors the model can correct, and an
   explicit "nothing found" so it doesn't answer from memory.
3. *"What are the security risks of MCP?"* Tool output is untrusted input to the model
   (indirect prompt injection); tools that write or act widen the blast radius; remote
   servers need authentication; data leaves to the host's model. Mine is read-only,
   labels its output, and refuses to listen beyond localhost until tokens are checked.
4. *"Why does your MCP server return passages, not answers?"* The caller already has a
   model. Returning answers means two models in a row, double cost, and evidence the
   caller can't see or cite.
5. *"LangGraph or CrewAI?"* LangGraph for one agent with an explicit, bounded loop I can
   test node by node; CrewAI for teams of role-based agents. My problem is the first.

---

## Part 6: Done checklist

- [ ] `make lint test` and `make test-integration` pass
- [ ] `make mcp-smoke` shows the tools, documents, passages and the rejected `k=50`
- [ ] Inspector: search, a schema rejection and `get_context` tried
- [ ] Connected to Claude Code or Claude Desktop, an answer with page citations
- [ ] Merged, with `uv.lock` committed

**Next:** Phase 5b, the LangGraph agent: plan → search → enough evidence? → search again or
answer, measured against the one-pass pipeline with `make eval`.
