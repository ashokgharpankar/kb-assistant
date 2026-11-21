"""Postgres + pgvector storage, with a schema we own.

Why not `langchain-postgres`? It works, but it fixes the schema (one JSONB
metadata column, its own table names). Owning the schema lets us:
- keep one table per embedding space (768-dim Ollama vectors never mix with
  512-dim Bedrock vectors),
- track what was ingested and skip unchanged documents,
- add a full-text column now that Phase 4's hybrid search will use.
See ADR 0005.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql

from kb_core.models import Chunk, RetrievedChunk, SourceDocument
from kb_core.providers import EmbeddingSpace


def _plain_dsn(url: str) -> str:
    # SQLAlchemy-style URLs ("postgresql+psycopg://") are common in settings; psycopg wants "postgresql://".
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass(frozen=True)
class StoreStats:
    documents: int
    chunks: int
    table: str


class PgVectorStore:
    def __init__(self, database_url: str, space: EmbeddingSpace) -> None:
        self.dsn = _plain_dsn(database_url)
        self.space = space
        self.table = sql.Identifier(space.table_name)
        self.index = sql.Identifier(f"{space.table_name}_hnsw"[:63])

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            register_vector(conn)
            yield conn

    # --- schema --------------------------------------------------------------

    def ensure_schema(self) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                    document_id  text PRIMARY KEY,
                    title        text NOT NULL,
                    uri          text NOT NULL,
                    updated_at   timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            # What has been embedded, per embedding space. Lets a re-run skip unchanged files.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_ingest_state (
                    space         text NOT NULL,
                    document_id   text NOT NULL REFERENCES kb_documents ON DELETE CASCADE,
                    fingerprint   text NOT NULL,
                    chunk_count   integer NOT NULL,
                    ingested_at   timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (space, document_id)
                )
                """
            )
            conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {table} (
                        chunk_id     text PRIMARY KEY,
                        document_id  text NOT NULL REFERENCES kb_documents ON DELETE CASCADE,
                        ordinal      integer NOT NULL,
                        section      text NOT NULL,
                        page         integer NOT NULL,
                        content      text NOT NULL,
                        embedding    vector({dims}) NOT NULL,
                        -- Not used until Phase 4 (hybrid search); cheap to keep from day one.
                        content_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
                    )
                    """
                ).format(table=self.table, dims=sql.Literal(self.space.dimensions))
            )
            # HNSW: approximate nearest-neighbour index. Cosine ops because we rank by cosine similarity.
            conn.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {index} ON {table} USING hnsw (embedding vector_cosine_ops)"
                ).format(index=self.index, table=self.table)
            )
            conn.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} (document_id)").format(
                    idx=sql.Identifier(f"{self.space.table_name}_doc"[:63]), table=self.table
                )
            )

    # --- ingestion -----------------------------------------------------------

    def fingerprint_of(self, document_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT fingerprint FROM kb_ingest_state WHERE space = %s AND document_id = %s",
                (self.space.table_name, document_id),
            ).fetchone()
        return row[0] if row else None

    def replace_document(
        self,
        doc: SourceDocument,
        fingerprint: str,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        """Swap a document's chunks atomically: readers see the old set or the new set, never half."""
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk is required")
        with self.connect() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO kb_documents (document_id, title, uri) VALUES (%s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE
                SET title = EXCLUDED.title, uri = EXCLUDED.uri, updated_at = now()
                """,
                (doc.document_id, doc.title, doc.uri),
            )
            conn.execute(
                sql.SQL("DELETE FROM {table} WHERE document_id = %s").format(table=self.table),
                (doc.document_id,),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    sql.SQL(
                        """
                        INSERT INTO {table} (chunk_id, document_id, ordinal, section, page, content, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(table=self.table),
                    [
                        (
                            c.chunk_id,
                            c.document_id,
                            c.ordinal,
                            c.section,
                            c.page,
                            c.text,
                            np.asarray(v, dtype=np.float32),
                        )
                        for c, v in zip(chunks, vectors, strict=True)
                    ],
                )
            conn.execute(
                """
                INSERT INTO kb_ingest_state (space, document_id, fingerprint, chunk_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (space, document_id) DO UPDATE
                SET fingerprint = EXCLUDED.fingerprint, chunk_count = EXCLUDED.chunk_count, ingested_at = now()
                """,
                (self.space.table_name, doc.document_id, fingerprint, len(chunks)),
            )

    # --- retrieval -----------------------------------------------------------

    def search(
        self, query_vector: Sequence[float], k: int, min_similarity: float = 0.0
    ) -> list[RetrievedChunk]:
        """Top-k chunks by cosine similarity. `<=>` is pgvector's cosine *distance* (1 - similarity)."""
        query = sql.SQL(
            """
            SELECT c.chunk_id, c.document_id, c.ordinal, c.section, c.page, c.content,
                   d.title, d.uri, 1 - (c.embedding <=> %(q)s) AS similarity
            FROM {table} c JOIN kb_documents d USING (document_id)
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s
            """
        ).format(table=self.table)
        with self.connect() as conn:
            rows = conn.execute(
                query, {"q": np.asarray(query_vector, dtype=np.float32), "k": k}
            ).fetchall()
        results = [
            RetrievedChunk(
                chunk=Chunk(
                    chunk_id=r[0],
                    document_id=r[1],
                    ordinal=r[2],
                    text=r[5],
                    section=r[3],
                    page=r[4],
                ),
                document_title=r[6],
                uri=r[7],
                similarity=float(r[8]),
            )
            for r in rows
        ]
        return [r for r in results if r.similarity >= min_similarity]

    def stats(self) -> StoreStats:
        with self.connect() as conn:
            docs = conn.execute(
                "SELECT count(*) FROM kb_ingest_state WHERE space = %s", (self.space.table_name,)
            ).fetchone()
            chunks = conn.execute(
                sql.SQL("SELECT count(*) FROM {table}").format(table=self.table)
            ).fetchone()
        return StoreStats(
            int(docs[0]) if docs else 0, int(chunks[0]) if chunks else 0, self.space.table_name
        )
