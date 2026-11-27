"""Wire the pieces together from settings. The CLI and the API both use this."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from langchain_core.embeddings import Embeddings

from kb_core.agent import RetrievalAgent
from kb_core.models import Answer, StreamEvent
from kb_core.providers import chat_model_id, embedding_space, get_chat_model, get_embeddings
from kb_core.rag import RagPipeline
from kb_core.retrieval import FlashRankReranker, Reranker, Retriever
from kb_core.settings import Settings
from kb_core.store import PgVectorStore
from kb_core.tracing import Tracer, build_tracer


def build_store(settings: Settings) -> PgVectorStore:
    return PgVectorStore(settings.database_url, embedding_space(settings))


def build_reranker(settings: Settings) -> Reranker | None:
    return FlashRankReranker() if settings.reranker == "flashrank" else None


def build_retriever(settings: Settings, store: PgVectorStore, embeddings: Embeddings) -> Retriever:
    return Retriever(
        store,
        embeddings,
        mode=settings.retrieval_mode,
        reranker=build_reranker(settings),
        candidates=settings.retrieval_candidates,
    )


def build_pipeline(
    settings: Settings, store: PgVectorStore | None = None, tracer: Tracer | None = None
) -> RagPipeline:
    store = store or build_store(settings)
    embeddings = get_embeddings(settings)
    retriever = build_retriever(settings, store, embeddings)
    return RagPipeline(
        search=store.search,
        rank=retriever.rank,
        embeddings=embeddings,
        chat_model=get_chat_model(settings),
        model_id=chat_model_id(settings),
        k=settings.retrieval_k,
        min_similarity=settings.min_similarity,
        tracer=tracer or build_tracer(settings),
    )


class Answerer(Protocol):
    """What the CLI, the API and the evaluation need: RagPipeline and RetrievalAgent fit."""

    tracer: Tracer

    def answer(self, question: str) -> Answer: ...

    def stream(self, question: str) -> Iterator[StreamEvent]: ...


def build_agent(
    settings: Settings, store: PgVectorStore | None = None, tracer: Tracer | None = None
) -> RetrievalAgent:
    store = store or build_store(settings)
    retriever = build_retriever(settings, store, get_embeddings(settings))
    return RetrievalAgent(
        rank=retriever.rank,
        chat_model=get_chat_model(settings),
        model_id=chat_model_id(settings),
        k=settings.retrieval_k,
        min_similarity=settings.min_similarity,
        window=store.chunk_window,
        max_searches=settings.agent_max_searches,
        tracer=tracer or build_tracer(settings),
    )


def build_answerer(
    settings: Settings,
    store: PgVectorStore | None = None,
    tracer: Tracer | None = None,
    cache: bool | None = None,
) -> Answerer:
    """The pipeline or the agent (`KB_ANSWER_MODE`), with the answer cache (`KB_CACHE`,
    Phase 8a) and behind the guardrails (`KB_GUARDRAILS`, Phase 7b).

    Order matters: guardrails → cache → model. A blocked question never touches the
    cache, and a cached answer still gets the grounding check. `cache=False` overrides the
    setting (the evaluation measures the model, not the cache).
    """
    store = store or build_store(settings)
    inner: Answerer = (
        build_agent(settings, store, tracer)
        if settings.answer_mode == "agent"
        else build_pipeline(settings, store, tracer)
    )
    if settings.cache_enabled if cache is None else cache:
        inner = build_cache(settings, store, inner)
    if not settings.guardrails:
        return inner
    from kb_core.guarded import GuardedAnswerer  # avoids an import cycle (guarded -> factory types)

    return GuardedAnswerer(inner)


def build_cache(settings: Settings, store: PgVectorStore, inner: Answerer) -> Answerer:
    from kb_core.cache import CachedAnswerer, PgAnswerCache
    from kb_core.rag import PROMPT_VERSION

    cache = PgAnswerCache(
        store,
        semantic_threshold=settings.cache_semantic_threshold,
        ttl_hours=settings.cache_ttl_hours,
    )
    cache.ensure_schema()
    # Everything that changes an answer. The corpus is added per request (it can change
    # while the API runs); anything here changing starts a fresh namespace.
    config: dict[str, object] = {
        "model": chat_model_id(settings),
        "embeddings": store.space.table_name,
        "prompt": PROMPT_VERSION,
        "k": settings.retrieval_k,
        "floor": settings.min_similarity,
        "retrieval": settings.retrieval_mode,
        "reranker": settings.reranker,
        "answer_mode": settings.answer_mode,
    }
    return CachedAnswerer(inner, cache, get_embeddings(settings), config)
