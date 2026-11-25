"""Phase 5a smoke test: start the real MCP server over stdio and call each tool.

The same path Claude Desktop or Claude Code would use: launch `kb-mcp` as a
subprocess and speak MCP over its stdin/stdout. Needs Postgres (make up) and
Ollama running, and the knowledge base ingested.

Run:  make mcp-smoke  [Q="your question"]
"""

from __future__ import annotations

import shutil
import sys
from typing import Any

import anyio
from mcp import Client, StdioServerParameters


async def main(question: str) -> int:
    kb_mcp = shutil.which("kb-mcp")
    if kb_mcp is None:
        print("kb-mcp not found: run `uv sync` first", file=sys.stderr)
        return 1
    async with Client(StdioServerParameters(command=kb_mcp)) as client:
        tools = (await client.list_tools()).tools
        print("tools:", ", ".join(t.name for t in tools))

        docs: Any = await client.call_tool("list_documents", {})
        for d in docs.structured_content["documents"]:
            print(f"  {d['title']}  ({d['chunks']} chunks)")

        found: Any = await client.call_tool("search_knowledge_base", {"query": question, "k": 4})
        result = found.structured_content
        print(f"\nsearch ({result['retrieval']}): {question}")
        for p in result["passages"]:
            print(f"  {p['similarity']:.3f}  p.{p['page']:<5} {p['section']}")
        if not result["passages"]:
            print("  (nothing relevant)", result["note"])
            return 0

        ctx: Any = await client.call_tool(
            "get_context", {"chunk_id": result["passages"][0]["chunk_id"], "before": 1, "after": 1}
        )
        pages = [p["page"] for p in ctx.structured_content["passages"]]
        print(f"\nget_context around the top hit: {len(pages)} passages, pages {pages}")

        bad: Any = await client.call_tool("search_knowledge_base", {"query": "x", "k": 50})
        print("k=50 rejected as a tool error:", bad.is_error)
    return 0


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What are the design principles of the Security pillar?"
    sys.exit(anyio.run(main, q))
