"""Phase 4: heading-path sections, Resources removal, chunk headers, retriever, reranker."""

from __future__ import annotations

import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from kb_core.chunking import (
    chunk_document,
    content_fingerprint,
    embedding_text,
    strip_resources,
)
from kb_core.loaders import build_sections
from kb_core.models import Chunk, RetrievedChunk, SourceDocument
from kb_core.retrieval import FlashRankReranker, Retriever

from .conftest import WordHashEmbeddings

# --- sections from the table of contents --------------------------------------------

PAGES = [
    "Security\nThe security pillar protects data.\nDesign principles\n"
    "Implement a strong identity foundation.\nMaintain traceability.",
    "Definitions\nSecurity has seven areas.\nIdentity and access management\nUse roles.",
    "Document revisions\nChanged things.",
]
TOC = [
    (1, "Security", 1),
    (2, "Design principles", 1),
    (2, "Definitions", 2),
    (3, "Identity and access management", 2),
    (1, "Document revisions", 3),
]


def test_sections_start_at_their_heading_even_on_a_shared_page() -> None:
    sections = build_sections(PAGES, TOC, "Doc", toc_depth=4)
    titles = [s.title for s in sections]
    assert titles == [
        "Security",
        "Security > Design principles",
        "Security > Definitions",
        "Security > Definitions > Identity and access management",
    ]  # "Document revisions" is skipped
    principles = sections[1]
    assert principles.text.startswith("Design principles\nImplement a strong identity")
    assert "protects data" not in principles.text
    assert principles.page_at(0) == 1


def test_depth_limits_how_far_down_sections_go() -> None:
    sections = build_sections(PAGES, TOC, "Doc", toc_depth=1)
    assert [s.title for s in sections] == ["Security"]
    assert "Use roles." in sections[0].text  # deeper headings stay inside the parent
    assert sections[0].page_at(len(sections[0].text) - 1) == 2


def test_a_heading_not_found_in_the_text_starts_at_its_page() -> None:
    sections = build_sections(PAGES, [(1, "Security", 1), (1, "Missing title", 2)], "Doc")
    assert sections[1].title == "Missing title"
    assert sections[1].text.startswith("Definitions")
    assert sections[1].page_at(0) == 2


def test_text_before_the_first_heading_gets_the_document_title() -> None:
    sections = build_sections(["Preface text.", "Security\nBody."], [(1, "Security", 2)], "Doc")
    assert [s.title for s in sections] == ["Doc", "Security"]


def test_headings_match_across_wrapped_lines_and_case() -> None:
    pages = ["Intro text.\nREL10-BP01 Deploy the workload\nto multiple locations\nBody."]
    toc = [(1, "Intro", 1), (2, "REL10-BP01 Deploy the workload to multiple locations", 1)]
    sections = build_sections(pages, toc, "Doc")
    assert sections[-1].text.startswith("REL10-BP01 Deploy the workload")


# --- chunking ---------------------------------------------------------------------------


def test_resources_blocks_are_removed_until_the_next_best_practice() -> None:
    text = (
        "Use multiple Availability Zones.\n"
        "Resources\n"
        "Related documents:\n"
        "• Fault isolation boundaries\n"
        "AWS re:Invent 2019: Introducing The Amazon Builders' Library (DOP328)\n"
        "Related videos:\n"
        "• Shuffle-sharding talk\n"
        "REL10-BP02 Select the appropriate locations\n"
        "Choose Regions near users."
    )
    cleaned = strip_resources(text)
    assert "Builders' Library" not in cleaned and "Related" not in cleaned
    assert cleaned.startswith("Use multiple Availability Zones.")
    assert cleaned.endswith(
        "REL10-BP02 Select the appropriate locations\nChoose Regions near users."
    )


def test_text_without_resources_is_untouched() -> None:
    text = "Implementation guidance\nUse resources wisely.\n• Tag everything."
    assert strip_resources(text) == text


def test_chunks_carry_the_heading_path_and_drop_link_only_pieces() -> None:
    sections = build_sections(PAGES, TOC, "Doc")
    doc = SourceDocument("d", "Doc", "file:///d.pdf", tuple(sections))
    chunks = chunk_document(doc, 200, 20)
    assert any(c.section == "Security > Design principles" for c in chunks)


def test_embedding_text_adds_the_heading_path_only_when_asked() -> None:
    chunk = Chunk("d:1", "d", 1, "Maintain traceability.", "Security > Design principles", 1)
    assert embedding_text(chunk, True) == "Security > Design principles\n\nMaintain traceability."
    assert embedding_text(chunk, False) == "Maintain traceability."


def test_turning_headers_on_or_off_changes_the_fingerprint() -> None:
    doc = SourceDocument("d", "Doc", "file:///d.pdf", tuple(build_sections(PAGES, TOC, "Doc")))
    assert content_fingerprint(doc, 1200, 200, True) != content_fingerprint(doc, 1200, 200, False)


# --- retriever --------------------------------------------------------------------------


def hit(name: str, similarity: float) -> RetrievedChunk:
    return RetrievedChunk(
        Chunk(name, "d", 1, f"text {name}", "S", 1), "Doc", "file:///d", similarity
    )


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, vector: Sequence[float], k: int, min_similarity: float = 0.0) -> list[Any]:
        self.calls.append(("vector", k))
        return [hit("v1", 0.80), hit("v2", 0.70), hit("v3", 0.50)][:k]

    def hybrid_search(
        self, vector: Sequence[float], text: str, k: int, rrf_k: int = 60
    ) -> list[Any]:
        self.calls.append(("hybrid", k))
        return [hit("h1", 0.75), hit("kw", 0.55), hit("h2", 0.70)][:k]


class ReverseReranker:
    model_id = "fake/reverse"

    def rerank(self, question: str, hits: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
        import dataclasses

        n = len(hits)
        return [dataclasses.replace(h, rerank_score=(i + 1) / n) for i, h in enumerate(hits)][::-1]


def test_vector_mode_asks_for_exactly_n() -> None:
    store = FakeStore()
    retriever = Retriever(store, WordHashEmbeddings(), mode="vector")
    assert [h.chunk.chunk_id for h in retriever.rank("q", 2)] == ["v1", "v2"]
    assert store.calls == [("vector", 2)]
    assert retriever.description == "vector"


def test_hybrid_mode_searches_a_candidate_pool_and_applies_the_floor_last() -> None:
    store = FakeStore()
    retriever = Retriever(store, WordHashEmbeddings(), mode="hybrid", candidates=20)
    ranked = retriever.rank("q", 2, min_similarity=0.6)
    assert [h.chunk.chunk_id for h in ranked] == ["h1", "h2"]  # "kw" (0.55) is below the floor
    assert store.calls == [("hybrid", 20)]


def test_the_reranker_reorders_the_pool() -> None:
    retriever = Retriever(FakeStore(), WordHashEmbeddings(), "vector", ReverseReranker(), 3)
    ranked = retriever.rank("q", 3)
    assert [h.chunk.chunk_id for h in ranked] == ["v3", "v2", "v1"]
    assert ranked[0].rerank_score == 1.0
    assert retriever.description == "vector+rerank(fake/reverse)"


def test_flashrank_reranker_sorts_by_score_and_keeps_the_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    class Ranker:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        def rerank(self, request: Any) -> list[dict[str, Any]]:
            seen["query"] = request.query
            seen["texts"] = [p["text"] for p in request.passages]
            return [{"id": 0, "score": 0.1}, {"id": 1, "score": 0.9}]

    class RerankRequest:
        def __init__(self, query: str, passages: list[dict[str, Any]]) -> None:
            self.query, self.passages = query, passages

    fake = types.ModuleType("flashrank")
    fake.Ranker = Ranker  # type: ignore[attr-defined]
    fake.RerankRequest = RerankRequest  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "flashrank", fake)

    reranker = FlashRankReranker("tiny-model", cache_dir=tmp_path / "cache")
    ranked = reranker.rerank("design principles?", [hit("a", 0.8), hit("b", 0.7)])

    assert [h.chunk.chunk_id for h in ranked] == ["b", "a"]
    assert [h.rerank_score for h in ranked] == [0.9, 0.1]
    assert seen["model_name"] == "tiny-model" and (tmp_path / "cache").is_dir()
    assert seen["texts"][0] == "S\n\ntext a"  # the heading path is part of what it reads
    assert reranker.rerank("q", []) == []
