"""The Postgres answer cache against a real pgvector. Skipped unless KB_TEST_DATABASE_URL."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest
from psycopg import sql

from kb_core.cache import PgAnswerCache
from kb_core.models import Answer
from kb_core.providers import EmbeddingSpace
from kb_core.store import PgVectorStore

from .conftest import DIMS, WordHashEmbeddings


@pytest.fixture
def cache(test_database_url: str) -> Iterator[PgAnswerCache]:
    # A unique dimension count gives this run its own cache table.
    dims = DIMS + 1 + uuid.uuid4().int % 500
    space = EmbeddingSpace("test", f"m{uuid.uuid4().hex[:8]}", dims)
    store = PgVectorStore(test_database_url, space)
    store.ensure_schema()
    c = PgAnswerCache(store, semantic_threshold=0.9, ttl_hours=1)
    c.ensure_schema()
    yield c
    store.close()
    with psycopg.connect(store.dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {t}").format(t=sql.Identifier(c.table)))
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {t}").format(t=store.table))


def vec(text: str, dims: int) -> list[float]:
    v = WordHashEmbeddings().embed_query(text)
    return v + [0.0] * (dims - len(v))


def test_exact_semantic_and_namespace(cache: PgAnswerCache) -> None:
    dims = cache.pg.space.dimensions
    q = "How do I survive an availability zone failure?"
    answer = Answer(
        question=q, text="Use AZs.", model="m", input_tokens=10, cost_usd=Decimal("0.01")
    )
    cache.store("ns1", q, vec(q, dims), answer)

    exact = cache.lookup(
        "ns1", "how do i survive an availability zone failure", lambda: vec(q, dims)
    )
    assert exact is not None and exact.kind == "exact" and exact.answer.text == "Use AZs."
    assert exact.answer.cost_usd == Decimal("0.01")

    reworded = "How can I survive availability zone failure?"
    semantic = cache.lookup("ns1", reworded, lambda: vec(reworded, dims))
    assert semantic is not None and semantic.kind == "semantic" and semantic.similarity >= 0.9

    far = "What does the cost pillar say about tagging?"
    assert cache.lookup("ns1", far, lambda: vec(far, dims)) is None
    assert cache.lookup("ns2", q, lambda: vec(q, dims)) is None  # another namespace sees nothing


def test_clear_empties_the_table(cache: PgAnswerCache) -> None:
    dims = cache.pg.space.dimensions
    cache.store("ns", "q one here", vec("q one here", dims), Answer(question="q", text="a"))
    assert cache.clear() == 1
    assert cache.lookup("ns", "q one here", lambda: vec("q one here", dims)) is None


def test_fingerprint_is_stable_for_an_empty_corpus(cache: PgAnswerCache) -> None:
    assert cache.corpus_fingerprint() == cache.corpus_fingerprint() == "empty"
