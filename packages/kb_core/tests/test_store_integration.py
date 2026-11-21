"""Runs against a real Postgres + pgvector. Skipped unless KB_TEST_DATABASE_URL is set.

Locally: `make up && make test-integration`. In CI: a pgvector service container.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from kb_core.ingest import ingest_path
from kb_core.providers import EmbeddingSpace
from kb_core.store import PgVectorStore

from .conftest import DIMS, WordHashEmbeddings


@pytest.fixture
def store(test_database_url: str) -> Iterator[PgVectorStore]:
    # A unique table per test run, so tests never see each other's data.
    space = EmbeddingSpace("test", f"m{uuid.uuid4().hex[:8]}", DIMS)
    s = PgVectorStore(test_database_url, space)
    s.ensure_schema()
    yield s
    with psycopg.connect(s.dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {t}").format(t=s.table))
        conn.execute("DELETE FROM kb_ingest_state WHERE space = %s", (space.table_name,))


def test_ingest_then_search_finds_the_right_section(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    report = ingest_path(sample_pdf, store, embeddings, chunk_size=300, chunk_overlap=50)
    assert (report.ingested, report.failed) == (1, 0)

    hits = store.search(embeddings.embed_query("multiple Availability Zones recovery"), k=3)
    assert hits[0].chunk.section == "Reliability pillar"
    assert hits[0].chunk.page == 2
    assert hits[0].document_title == "Sample Framework"
    assert hits == sorted(hits, key=lambda h: h.similarity, reverse=True)


def test_reingesting_unchanged_files_is_skipped(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, 300, 50)
    second = ingest_path(sample_pdf, store, embeddings, 300, 50)
    assert (second.ingested, second.unchanged) == (0, 1)
    forced = ingest_path(sample_pdf, store, embeddings, 300, 50, force=True)
    assert forced.ingested == 1
    assert store.stats().chunks == forced.chunks  # replaced, not duplicated


def test_changing_chunk_settings_triggers_reingest(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, 300, 50)
    assert ingest_path(sample_pdf, store, embeddings, 200, 20).ingested == 1


def test_similarity_floor_filters_weak_matches(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, 300, 50)
    query = embeddings.embed_query("quantum chromodynamics lattice gauge theory")
    assert store.search(query, k=3, min_similarity=0.5) == []
