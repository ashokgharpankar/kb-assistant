"""Wire the pieces together from settings. The CLI and the API both use this."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
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
    settings: Settings,
    store: PgVectorStore | None = None,
    tracer: Tracer | None = None,
    routing: bool = True,
) -> RagPipeline:
    """`routing=False` builds the small-model-only pipeline the spend cap falls back to."""
    store = store or build_store(settings)
    embeddings = get_embeddings(settings)
    retriever = build_retriever(settings, store, embeddings)
    big = settings.route_escalation_model if routing else None
    return RagPipeline(
        search=store.search,
        rank=retriever.rank,
        embeddings=embeddings,
        chat_model=get_chat_model(settings),
        model_id=chat_model_id(settings),
        k=settings.retrieval_k,
        min_similarity=settings.min_similarity,
        tracer=tracer or build_tracer(settings),
        prompt_layout=settings.prompt_layout,
        escalation=(get_chat_model(settings, big), big) if big else None,
        escalate_min_similarity=settings.route_min_similarity,
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
    """The pipeline or the agent (`KB_ANSWER_MODE`), with routing (Phase 8b), the spend
    cap (`KB_DAILY_BUDGET_USD`, 8b), the answer cache (`KB_CACHE`, 8a), behind the
    guardrails (`KB_GUARDRAILS`, 7b).

    Order matters: guardrails → cache → spend cap → model. A blocked question never
    touches the cache, a cached answer still gets the grounding check, and a cache hit is
    free, so it still answers when the budget is spent. `cache=False` overrides the
    setting (the evaluation measures the model, not the cache).
    """
    store = store or build_store(settings)
    inner: Answerer = (
        build_agent(settings, store, tracer)
        if settings.answer_mode == "agent"
        else build_pipeline(settings, store, tracer)
    )
    if settings.daily_budget_usd is not None:
        inner = build_budget(settings, settings.daily_budget_usd, store, inner, tracer)
    if settings.cache_enabled if cache is None else cache:
        inner = build_cache(settings, store, inner)
    if not settings.guardrails:
        return inner
    from kb_core.guarded import GuardedAnswerer  # avoids an import cycle (guarded -> factory types)

    return GuardedAnswerer(inner)


def build_cache(settings: Settings, store: PgVectorStore, inner: Answerer) -> Answerer:
    from kb_core.cache import CachedAnswerer, PgAnswerCache
    from kb_core.rag import prompt_version

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
        "prompt": prompt_version(settings.prompt_layout),
        "k": settings.retrieval_k,
        "floor": settings.min_similarity,
        "retrieval": settings.retrieval_mode,
        "reranker": settings.reranker,
        "answer_mode": settings.answer_mode,
        "route": [settings.route_escalation_model, settings.route_min_similarity],
    }
    return CachedAnswerer(inner, cache, get_embeddings(settings), config)


def build_budget(
    settings: Settings,
    daily_usd: Decimal,
    store: PgVectorStore,
    inner: Answerer,
    tracer: Tracer | None,
) -> Answerer:
    from kb_core.budget import BudgetedAnswerer, PgSpendLedger, cost_basis

    # Economy: the small model alone. The agent has no routing, so it is its own economy.
    economy: Answerer = (
        build_pipeline(settings, store, tracer, routing=False)
        if settings.answer_mode == "pipeline" and settings.route_escalation_model
        else inner
    )
    ledger = PgSpendLedger(store)
    ledger.ensure_schema()
    return BudgetedAnswerer(
        inner,
        economy,
        ledger,
        daily_usd=daily_usd,
        soft_ratio=settings.budget_soft_ratio,
        cost_of=cost_basis(settings),
    )
