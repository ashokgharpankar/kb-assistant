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


# --- Phase 4: hybrid search -----------------------------------------------------------


def _load(store: PgVectorStore, embeddings: WordHashEmbeddings) -> None:
    from kb_core.models import Chunk, SourceDocument

    chunks = [
        Chunk(
            "h:1", "h", 0, "The security pillar protects data, systems and assets.", "Security", 1
        ),
        Chunk(
            "h:2",
            "h",
            1,
            "Implement a strong identity foundation. Maintain traceability.",
            "Security > Design principles",
            2,
        ),
        Chunk("h:3", "h", 2, "Spread the workload across Availability Zones.", "Reliability", 3),
    ]
    doc = SourceDocument("h", "Hybrid doc", "file:///h.pdf", ())
    store.replace_document(doc, "fp", chunks, [embeddings.embed_query(c.text) for c in chunks])


def test_hybrid_search_finds_a_chunk_by_its_heading_words(
    store: PgVectorStore, embeddings: WordHashEmbeddings
) -> None:
    _load(store, embeddings)
    question = "What are the design principles of the Security pillar?"
    vector = embeddings.embed_query(question)

    vector_only = [h.chunk.chunk_id for h in store.search(vector, k=3)]
    hybrid = store.hybrid_search(vector, question, k=3)
    ids = [h.chunk.chunk_id for h in hybrid]
    # "design principles" only appears in h:2's heading path (weighted 'A'): the keyword
    # side ranks it first, which lifts it in the fused order.
    assert ids.index("h:2") < vector_only.index("h:2")
    assert ids[-1] == "h:3"  # the unrelated Reliability chunk matches no keyword
    assert all(h.fused_score is not None for h in hybrid)
    assert hybrid == sorted(hybrid, key=lambda h: h.fused_score or 0.0, reverse=True)
    assert 0.0 <= hybrid[0].similarity <= 1.0  # cosine similarity still reported


def test_hybrid_search_works_when_no_keyword_matches(
    store: PgVectorStore, embeddings: WordHashEmbeddings
) -> None:
    _load(store, embeddings)
    vector = embeddings.embed_query("the of and")  # only stop words: an empty keyword query
    assert len(store.hybrid_search(vector, "the of and", k=2)) == 2  # vector side still ranks


def test_ensure_schema_upgrades_a_phase_1_table(test_database_url: str) -> None:
    space = EmbeddingSpace("test", f"old{uuid.uuid4().hex[:8]}", DIMS)
    s = PgVectorStore(test_database_url, space)
    with psycopg.connect(s.dsn, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kb_documents (document_id text PRIMARY KEY, "
            "title text NOT NULL, uri text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.execute(
            sql.SQL(
                "CREATE TABLE {t} (chunk_id text PRIMARY KEY, document_id text NOT NULL, "
                "ordinal integer NOT NULL, section text NOT NULL, page integer NOT NULL, "
                "content text NOT NULL, embedding vector({d}) NOT NULL, "
                "content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED)"
            ).format(t=s.table, d=sql.Literal(DIMS))
        )
    try:
        s.ensure_schema()
        with psycopg.connect(s.dsn) as conn:
            columns = {
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    (space.table_name,),
                )
            }
        assert "search_tsv" in columns and "content_tsv" not in columns
    finally:
        s.close()
        with psycopg.connect(s.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {t}").format(t=s.table))


def test_chunk_window_returns_neighbours_in_reading_order(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, chunk_size=300, chunk_overlap=50)
    hit = store.search(embeddings.embed_query("multiple Availability Zones recovery"), k=1)[0]
    window = store.chunk_window(hit.chunk.chunk_id, before=1, after=1)
    ordinals = [c.ordinal for c in window]
    assert hit.chunk.ordinal in ordinals
    assert ordinals == sorted(ordinals)
    assert {c.document_id for c in window} == {hit.chunk.document_id}
    assert len(window) <= 3
    assert store.chunk_window("no-such-chunk") == []


def test_documents_lists_titles_and_chunk_counts(
    store: PgVectorStore, sample_pdf: Path, embeddings: WordHashEmbeddings
) -> None:
    ingest_path(sample_pdf, store, embeddings, chunk_size=300, chunk_overlap=50)
    docs = store.documents()
    assert [d.title for d in docs] == ["Sample Framework"]
    assert docs[0].chunks == store.stats().chunks
