"""Retrieval strategies: what reaches the model, in what order (Phase 4).

    vector   cosine similarity only (Phases 1-3)
    hybrid   vectors + Postgres full-text search, merged with reciprocal rank fusion
    +rerank  a cross-encoder re-reads each (question, chunk) pair and re-orders them

Why each exists, measured in Phase 3: questions like "What are the design principles
of the Security pillar?" retrieved general overviews of the pillar instead of the
short principles list. Keywords match "design principles" literally; a cross-encoder
judges "does this chunk answer the question?" instead of "is it on the same topic?".

The similarity floor is still applied per chunk on cosine similarity, after ranking.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from langchain_core.embeddings import Embeddings

from kb_core.models import RetrievedChunk

Mode = Literal["vector", "hybrid"]

DEFAULT_RERANK_MODEL = "ms-marco-MiniLM-L-12-v2"
RERANK_CACHE = Path.home() / ".cache" / "kb-assistant" / "flashrank"


class SearchStore(Protocol):
    def search(
        self, query_vector: Sequence[float], k: int, min_similarity: float = 0.0
    ) -> list[RetrievedChunk]: ...

    def hybrid_search(
        self, query_vector: Sequence[float], query_text: str, k: int, rrf_k: int = 60
    ) -> list[RetrievedChunk]: ...


class Reranker(Protocol):
    model_id: str

    def rerank(self, question: str, hits: Sequence[RetrievedChunk]) -> list[RetrievedChunk]: ...


class FlashRankReranker:
    """A small cross-encoder that runs locally on the CPU (ONNX), no API calls.

    Unlike an embedding model, which encodes question and chunk separately and compares
    vectors, a cross-encoder reads both together and outputs a relevance score. Slower
    per pair, so it only re-orders a short candidate list. The model (~30 MB) downloads
    once into ~/.cache/kb-assistant/flashrank.
    """

    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL, cache_dir: Path = RERANK_CACHE):
        self.model_id = f"flashrank/{model_name}"
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._ranker: Any = None

    def _load(self) -> Any:
        if self._ranker is None:
            from flashrank import Ranker  # type: ignore[import-untyped]  # lazy: ONNX load is slow

            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._ranker = Ranker(
                model_name=self._model_name, cache_dir=str(self._cache_dir), log_level="WARNING"
            )
        return self._ranker

    def rerank(self, question: str, hits: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
        if not hits:
            return []
        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": f"{h.chunk.section}\n\n{h.chunk.text}"} for i, h in enumerate(hits)
        ]
        scored = self._load().rerank(RerankRequest(query=question, passages=passages))
        return sorted(
            (
                dataclasses.replace(hits[int(s["id"])], rerank_score=float(s["score"]))
                for s in scored
            ),
            key=lambda h: h.rerank_score or 0.0,
            reverse=True,
        )


class Retriever:
    def __init__(
        self,
        store: SearchStore,
        embeddings: Embeddings,
        mode: Mode = "hybrid",
        reranker: Reranker | None = None,
        candidates: int = 20,
    ) -> None:
        self.store = store
        self.embeddings = embeddings
        self.mode = mode
        self.reranker = reranker
        self.candidates = candidates

    @property
    def description(self) -> str:
        return self.mode + (f"+rerank({self.reranker.model_id})" if self.reranker else "")

    def rank(self, question: str, n: int, min_similarity: float = 0.0) -> list[RetrievedChunk]:
        """The best `n` chunks for the question, dropping any below the cosine floor."""
        vector = self.embeddings.embed_query(question)
        pool = max(n, self.candidates) if (self.mode == "hybrid" or self.reranker) else n
        if self.mode == "hybrid":
            hits = self.store.hybrid_search(vector, question, pool)
        else:
            hits = self.store.search(vector, pool)
        if self.reranker:
            hits = self.reranker.rerank(question, hits)
        return [h for h in hits if h.similarity >= min_similarity][:n]
