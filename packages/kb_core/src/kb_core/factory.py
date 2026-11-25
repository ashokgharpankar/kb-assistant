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
    settings: Settings, store: PgVectorStore | None = None, tracer: Tracer | None = None
) -> Answerer:
    """The pipeline or the agent, by `KB_ANSWER_MODE`."""
    if settings.answer_mode == "agent":
        return build_agent(settings, store, tracer)
    return build_pipeline(settings, store, tracer)
