"""Wire the pieces together from settings. The CLI and the API both use this."""

from __future__ import annotations

from kb_core.providers import chat_model_id, embedding_space, get_chat_model, get_embeddings
from kb_core.rag import RagPipeline
from kb_core.settings import Settings
from kb_core.store import PgVectorStore
from kb_core.tracing import Tracer, build_tracer


def build_store(settings: Settings) -> PgVectorStore:
    return PgVectorStore(settings.database_url, embedding_space(settings))


def build_pipeline(
    settings: Settings, store: PgVectorStore | None = None, tracer: Tracer | None = None
) -> RagPipeline:
    store = store or build_store(settings)
    return RagPipeline(
        search=store.search,
        embeddings=get_embeddings(settings),
        chat_model=get_chat_model(settings),
        model_id=chat_model_id(settings),
        k=settings.retrieval_k,
        min_similarity=settings.min_similarity,
        tracer=tracer or build_tracer(settings),
    )
