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
    s.close()
    with psycopg.connect(s.dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {t}").format(t=s.table))
        conn.execute("DELETE FROM kb_ingest_state WHERE space = %s", (space.table_name,))
        conn.execute(
            "DELETE FROM kb_documents d WHERE NOT EXISTS "
            "(SELECT 1 FROM kb_ingest_state s WHERE s.document_id = d.document_id)"
        )


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


def test_delete_document_removes_its_chunks(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, 300, 50)
    assert store.document_ids() == ["sample-framework"]
    assert store.delete_document("sample-framework")
    assert store.stats().chunks == 0 and store.document_ids() == []
    assert not store.delete_document("sample-framework")  # second time: nothing to delete


def test_prune_removes_documents_whose_file_is_gone(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings, tmp_path: Path
) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "runbook.md").write_text(
        "# Runbook\n\nPromote the standby database and check health.\n"
    )
    keep = folder / sample_pdf.name
    keep.write_bytes(sample_pdf.read_bytes())
    ingest_path(folder, store, embeddings, 300, 50)
    assert sorted(store.document_ids()) == ["runbook", "sample-framework"]

    (folder / "runbook.md").unlink()
    without_prune = ingest_path(folder, store, embeddings, 300, 50)
    assert without_prune.removed == [] and "runbook" in store.document_ids()

    report = ingest_path(folder, store, embeddings, 300, 50, prune=True)
    assert report.removed == ["runbook"]
    assert store.document_ids() == ["sample-framework"]


def test_pooled_connections_are_reused(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, 300, 50)
    query = embeddings.embed_query("Availability Zones")
    with store.connect() as conn:
        first_pid = conn.info.backend_pid
    store.search(query, k=2)
    with store.connect() as conn:
        assert conn.info.backend_pid == first_pid  # same server connection, no reconnect


def test_prune_refuses_a_single_file(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    with pytest.raises(ValueError, match="prune needs a folder"):
        ingest_path(sample_pdf, store, embeddings, 300, 50, prune=True)
