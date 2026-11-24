"""Wire the pieces together from settings. The CLI and the API both use this."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

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
