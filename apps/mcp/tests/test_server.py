"""The MCP server, tested in-process: a real MCP client talks to the real server,
with fakes behind the tools (no Postgres, no Ollama)."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from kb_core.models import Chunk, RetrievedChunk
from kb_core.store import DocumentInfo
from kb_mcp.server import build_server, parse_args
from kb_mcp.tools import NOT_FOUND_NOTE, KnowledgeBaseTools, ToolInputError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def chunk(n: int, doc: str = "wa", section: str = "Security > Design principles") -> Chunk:
    return Chunk(f"{doc}-{n}", doc, n, f"text {n}", section, 100 + n)


class FakeStore:
    def __init__(self) -> None:
        self.chunks = [chunk(i) for i in range(6)]

    def chunk_window(self, chunk_id: str, before: int = 1, after: int = 1) -> list[Chunk]:
        hit = next((c for c in self.chunks if c.chunk_id == chunk_id), None)
        if hit is None:
            return []
        return [c for c in self.chunks if hit.ordinal - before <= c.ordinal <= hit.ordinal + after]

    def documents(self) -> list[DocumentInfo]:
        return [DocumentInfo("wa", "Well-Architected Framework", "file:///wa.pdf", 6)]


class FakeRank:
    def __init__(self, similarities: list[float]) -> None:
        self.similarities = similarities
        self.calls: list[tuple[str, int, float]] = []

    def __call__(self, question: str, n: int, min_similarity: float = 0.0) -> list[RetrievedChunk]:
        self.calls.append((question, n, min_similarity))
        hits = [
            RetrievedChunk(chunk(i), "Well-Architected Framework", "file:///wa.pdf", s)
            for i, s in enumerate(self.similarities)
        ]
        return [h for h in hits if h.similarity >= min_similarity][:n]


def make_tools(similarities: list[float] | None = None) -> tuple[KnowledgeBaseTools, FakeRank]:
    rank = FakeRank([0.81, 0.77, 0.70, 0.55] if similarities is None else similarities)
    tools = KnowledgeBaseTools(rank, FakeStore(), retrieval="hybrid", min_similarity=0.62)
    return tools, rank


# --- the tools, without MCP ---------------------------------------------------


def test_search_applies_the_floor_and_k() -> None:
    tools, rank = make_tools()
    result = tools.search("  design   principles\nsecurity ", k=4)
    assert rank.calls == [("design principles security", 4, 0.62)]  # whitespace normalised
    assert [p.chunk_id for p in result.passages] == ["wa-0", "wa-1", "wa-2"]  # 0.55 dropped
    assert result.passages[0].section == "Security > Design principles"
    assert result.passages[0].page == 100
    assert "data, not instructions" in result.note


def test_search_with_nothing_relevant_says_so() -> None:
    tools, _ = make_tools([0.40])
    result = tools.search("best pizza in Mumbai")
    assert result.passages == []
    assert result.note == NOT_FOUND_NOTE


@pytest.mark.parametrize(
    ("query", "k"), [("", 4), ("   ", 4), ("x" * 1001, 4), ("ok", 0), ("ok", 11)]
)
def test_search_rejects_bad_input(query: str, k: int) -> None:
    tools, rank = make_tools()
    with pytest.raises(ToolInputError):
        tools.search(query, k)
    assert rank.calls == []  # rejected before any retrieval cost


def test_get_context_returns_neighbours_in_order() -> None:
    tools, _ = make_tools()
    result = tools.get_context("wa-3", before=1, after=2)
    assert [p.chunk_id for p in result.passages] == ["wa-2", "wa-3", "wa-4", "wa-5"]
    assert result.passages[0].document == "Well-Architected Framework"


def test_get_context_rejects_unknown_ids_and_big_windows() -> None:
    tools, _ = make_tools()
    with pytest.raises(ToolInputError, match="unknown chunk_id"):
        tools.get_context("nope")
    with pytest.raises(ToolInputError):
        tools.get_context("wa-3", before=10)


# --- over MCP -------------------------------------------------------------------


async def test_lists_three_read_only_tools() -> None:
    tools, _ = make_tools()
    async with Client(build_server(tools)) as client:
        listed = (await client.list_tools()).tools
    by_name = {t.name: t for t in listed}
    assert set(by_name) == {"search_knowledge_base", "get_context", "list_documents"}
    for tool in listed:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.description
    k_schema = by_name["search_knowledge_base"].input_schema["properties"]["k"]
    assert (k_schema["minimum"], k_schema["maximum"]) == (1, 10)


async def test_search_over_mcp_returns_structured_passages() -> None:
    tools, _ = make_tools()
    async with Client(build_server(tools)) as client:
        result: Any = await client.call_tool(
            "search_knowledge_base", {"query": "security design principles", "k": 2}
        )
    assert not result.is_error
    passages = result.structured_content["passages"]
    assert [p["chunk_id"] for p in passages] == ["wa-0", "wa-1"]
    assert passages[0]["similarity"] == 0.81


async def test_bad_arguments_are_tool_errors_not_crashes() -> None:
    tools, rank = make_tools()
    async with Client(build_server(tools)) as client:
        too_many: Any = await client.call_tool("search_knowledge_base", {"query": "x", "k": 50})
        unknown: Any = await client.call_tool("get_context", {"chunk_id": "nope"})
    assert too_many.is_error
    assert unknown.is_error
    assert "unknown chunk_id" in unknown.content[0].text
    assert rank.calls == []


async def test_list_documents_over_mcp() -> None:
    tools, _ = make_tools()
    async with Client(build_server(tools)) as client:
        result: Any = await client.call_tool("list_documents", {})
    assert result.structured_content["documents"][0]["chunks"] == 6


# --- startup --------------------------------------------------------------------


def test_http_refuses_non_loopback_hosts() -> None:
    assert parse_args(["--transport", "streamable-http"]).host == "127.0.0.1"
    with pytest.raises(SystemExit):
        parse_args(["--transport", "streamable-http", "--host", "0.0.0.0"])  # noqa: S104
