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
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg_pool import ConnectionPool

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
    def __init__(self, database_url: str, space: EmbeddingSpace, pool_size: int = 5) -> None:
        self.dsn = _plain_dsn(database_url)
        self.space = space
        self.table = sql.Identifier(space.table_name)
        self.index = sql.Identifier(f"{space.table_name}_hnsw"[:63])
        self.pool_size = pool_size
        self._pool: ConnectionPool | None = None

    def _configure(self, conn: psycopg.Connection) -> None:
        register_vector(conn)

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Borrow a pooled connection.

        Opening a new connection per query cost ~30-40 ms (TCP, auth, registering
        the vector type); a pooled one is ready immediately. The pool opens lazily,
        so the vector extension exists by the time the first connection is configured.
        """
        if self._pool is None:
            self._pool = ConnectionPool(
                self.dsn,
                min_size=1,
                max_size=self.pool_size,
                configure=self._configure,
                open=True,
            )
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

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
                        embedding    vector({dims}) NOT NULL
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
            # Full-text search for hybrid retrieval (Phase 4). The heading path is weighted
            # above the body ('A' > 'B'), so "design principles" in a heading counts more.
            # Postgres keeps the column up to date itself (a stored generated column).
            conn.execute(
                sql.SQL(
                    """
                    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_tsv tsvector
                    GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', section), 'A') ||
                        setweight(to_tsvector('english', content), 'B')
                    ) STORED
                    """
                ).format(table=self.table)
            )
            conn.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {idx} ON {table} USING gin (search_tsv)"
                ).format(idx=sql.Identifier(f"{self.space.table_name}_fts"[:63]), table=self.table)
            )
            # Phase 1's placeholder column (content only, never used).
            conn.execute(
                sql.SQL("ALTER TABLE {table} DROP COLUMN IF EXISTS content_tsv").format(
                    table=self.table
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

    _COLUMNS = """c.chunk_id, c.document_id, c.ordinal, c.section, c.page, c.content,
                   d.title, d.uri, 1 - (c.embedding <=> %(q)s) AS similarity"""

    @staticmethod
    def _row_to_hit(r: Sequence[Any], fused: float | None = None) -> RetrievedChunk:
        return RetrievedChunk(
            chunk=Chunk(
                chunk_id=r[0], document_id=r[1], ordinal=r[2], text=r[5], section=r[3], page=r[4]
            ),
            document_title=r[6],
            uri=r[7],
            similarity=float(r[8]),
            fused_score=fused,
        )

    def search(
        self, query_vector: Sequence[float], k: int, min_similarity: float = 0.0
    ) -> list[RetrievedChunk]:
        """Top-k chunks by cosine similarity. `<=>` is pgvector's cosine *distance* (1 - similarity)."""
        query = sql.SQL(
            """
            SELECT {columns}
            FROM {table} c JOIN kb_documents d USING (document_id)
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s
            """
        ).format(columns=sql.SQL(self._COLUMNS), table=self.table)
        with self.connect() as conn:
            rows = conn.execute(
                query, {"q": np.asarray(query_vector, dtype=np.float32), "k": k}
            ).fetchall()
        results = [self._row_to_hit(r) for r in rows]
        return [r for r in results if r.similarity >= min_similarity]

    def hybrid_search(
        self, query_vector: Sequence[float], query_text: str, k: int, rrf_k: int = 60
    ) -> list[RetrievedChunk]:
        """Vector search and keyword search, merged with reciprocal rank fusion (RRF).

        Each list ranks up to k chunks; a chunk's fused score is the sum of 1/(rrf_k + rank)
        over the lists it appears in. RRF needs no score calibration: cosine similarities
        and full-text ranks live on different scales, ranks don't. rrf_k = 60 is the value
        from the original paper and the usual default.

        Keyword matching ORs the question's words (after stemming and stop-word removal),
        so a chunk doesn't need every word; ts_rank_cd rewards chunks that have more of
        them close together, and the heading path counts more than body text.
        """
        query = sql.SQL(
            """
            WITH terms AS (
                SELECT to_tsquery('english', coalesce(string_agg(quote_literal(lexeme), ' | '), ''))
                       AS tsq
                FROM unnest(to_tsvector('english', %(text)s))
            ),
            vec AS (
                SELECT chunk_id, row_number() OVER (ORDER BY embedding <=> %(q)s) AS rank
                FROM {table} ORDER BY embedding <=> %(q)s LIMIT %(k)s
            ),
            kw AS (
                SELECT c.chunk_id,
                       row_number() OVER (ORDER BY ts_rank_cd(c.search_tsv, t.tsq) DESC) AS rank
                FROM {table} c, terms t
                WHERE c.search_tsv @@ t.tsq
                ORDER BY ts_rank_cd(c.search_tsv, t.tsq) DESC LIMIT %(k)s
            ),
            fused AS (
                SELECT chunk_id, sum(1.0 / (%(rrf_k)s + rank)) AS score
                FROM (SELECT * FROM vec UNION ALL SELECT * FROM kw) ranked
                GROUP BY chunk_id
            )
            SELECT {columns}, f.score
            FROM fused f JOIN {table} c USING (chunk_id) JOIN kb_documents d USING (document_id)
            ORDER BY f.score DESC, similarity DESC
            LIMIT %(k)s
            """
        ).format(columns=sql.SQL(self._COLUMNS), table=self.table)
        params = {
            "q": np.asarray(query_vector, dtype=np.float32),
            "text": query_text,
            "k": k,
            "rrf_k": rrf_k,
        }
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_hit(r, float(r[9])) for r in rows]

    def document_ids(self) -> list[str]:
        """Documents ingested into this embedding space."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT document_id FROM kb_ingest_state WHERE space = %s ORDER BY 1",
                (self.space.table_name,),
            ).fetchall()
        return [r[0] for r in rows]

    def delete_document(self, document_id: str) -> bool:
        """Remove a document everywhere: its chunks in every space go with it (ON DELETE CASCADE)."""
        with self.connect() as conn:
            deleted = conn.execute(
                "DELETE FROM kb_documents WHERE document_id = %s", (document_id,)
            ).rowcount
        return deleted > 0

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
