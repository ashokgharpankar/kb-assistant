"""Answer cache (Phase 8a): don't pay twice for the same question.

Two levels, checked in order:

1. **Exact**: the same question after normalising case, spaces and punctuation.
   Always safe; costs one indexed lookup.
2. **Semantic**: a previous question whose embedding is almost identical (cosine
   similarity >= `cache_semantic_threshold`). Catches rewordings ("How do I tag
   resources for cost?" / "How should I tag resources for cost allocation?"), but a
   threshold set too low returns a confident answer to a *different* question ("What
   is RTO?" vs "What is RPO?"). Treat the threshold like the similarity floor
   (incident 0006): measure it with `kb cache-check` before trusting it.

Entries live in a **namespace**: a hash of everything that changes the answer (chat
model, embedding space, prompt, k, floor, retrieval and answer mode, and the corpus
fingerprint). Re-ingesting a document or editing the prompt starts a fresh namespace,
so stale answers aren't served; old entries expire with the TTL.

Only answers that cost a model call are stored (answered or refused). Blocked and
below-floor questions are already free, and errors are never cached.

The cache is shared by all users. That's right here (one knowledge base, the same for
everyone); a multi-tenant system would add the tenant to the namespace.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol

from kb_core.models import (
    Answer,
    Chunk,
    Citation,
    DoneEvent,
    RetrievedChunk,
    SourcesEvent,
    StreamEvent,
    TokenEvent,
)
from kb_core.tracing import Tracer

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from psycopg import Connection

    from kb_core.factory import Answerer
    from kb_core.store import PgVectorStore

CacheKind = Literal["exact", "semantic"]
# The question's embedding, computed only if the exact lookup misses: an exact hit needs
# no vector, so it costs one indexed query and no embedding call.
VectorFn = Callable[[], Sequence[float]]

_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalise_question(question: str) -> str:
    """Case, spacing and punctuation don't change the question."""
    text = unicodedata.normalize("NFKC", question).lower()
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


@dataclass(frozen=True)
class CacheHit:
    answer: Answer
    kind: CacheKind
    similarity: float  # 1.0 for exact hits
    cached_question: str


class AnswerCache(Protocol):
    def lookup(self, namespace: str, question: str, vector: VectorFn) -> CacheHit | None: ...

    def store(
        self, namespace: str, question: str, vector: Sequence[float], answer: Answer
    ) -> None: ...

    def corpus_fingerprint(self) -> str: ...


# --- serialisation -----------------------------------------------------------------


def answer_to_json(answer: Answer) -> dict[str, Any]:
    data = asdict(answer)
    data["cost_usd"] = str(answer.cost_usd)
    data["cost_saved_usd"] = str(answer.cost_saved_usd)
    data["grounding"] = None  # recomputed by the guardrails on every answer
    return data


def answer_from_json(data: dict[str, Any]) -> Answer:
    retrieved = [
        RetrievedChunk(
            chunk=Chunk(**r["chunk"]),
            document_title=r["document_title"],
            uri=r["uri"],
            similarity=r["similarity"],
            fused_score=r.get("fused_score"),
            rerank_score=r.get("rerank_score"),
        )
        for r in data.get("retrieved", [])
    ]
    fields = {k: v for k, v in data.items() if k not in {"retrieved", "citations", "grounding"}}
    return Answer(
        **{
            **fields,
            "cost_usd": Decimal(data.get("cost_usd", "0")),
            "cost_saved_usd": Decimal(data.get("cost_saved_usd", "0")),
            "retrieved": retrieved,
            "citations": [Citation(**c) for c in data.get("citations", [])],
            "grounding": None,
        }
    )


# --- Postgres implementation ----------------------------------------------------------


class PgAnswerCache:
    """Answers in Postgres, next to the chunks: exact lookup by a unique key, semantic
    lookup with the same pgvector HNSW index type as retrieval."""

    def __init__(
        self,
        store: PgVectorStore,
        semantic_threshold: float | None,
        ttl_hours: int,
    ) -> None:
        self.pg = store
        self.semantic_threshold = semantic_threshold
        self.ttl_hours = ttl_hours
        self.table = f"kb_answer_cache_{store.space.dimensions}"
        self._fingerprint: tuple[float, str] | None = None

    def ensure_schema(self) -> None:
        from psycopg import sql

        t = sql.Identifier(self.table)
        with self.pg.connect() as conn:
            conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {t} (
                        id             bigserial PRIMARY KEY,
                        namespace      text NOT NULL,
                        question       text NOT NULL,
                        question_norm  text NOT NULL,
                        embedding      vector({dims}) NOT NULL,
                        answer         jsonb NOT NULL,
                        created_at     timestamptz NOT NULL DEFAULT now(),
                        hits           integer NOT NULL DEFAULT 0,
                        last_hit_at    timestamptz,
                        UNIQUE (namespace, question_norm)
                    )
                    """
                ).format(t=t, dims=sql.Literal(self.pg.space.dimensions))
            )
            conn.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {i} ON {t} USING hnsw (embedding vector_cosine_ops)"
                ).format(i=sql.Identifier(f"{self.table}_hnsw"), t=t)
            )

    def clear(self) -> int:
        from psycopg import sql

        with self.pg.connect() as conn:
            cur = conn.execute(sql.SQL("DELETE FROM {t}").format(t=sql.Identifier(self.table)))
            return cur.rowcount

    def corpus_fingerprint(self) -> str:
        """What's indexed right now, as one hash. Cached for 60 s: a lookup per request
        would be cheap, but not free."""
        now = time.monotonic()
        if self._fingerprint and now - self._fingerprint[0] < 60:
            return self._fingerprint[1]
        with self.pg.connect() as conn:
            row = conn.execute(
                "SELECT coalesce(md5(string_agg(document_id || ':' || fingerprint, ',' "
                "ORDER BY document_id)), 'empty') FROM kb_ingest_state WHERE space = %s",
                (self.pg.space.table_name,),
            ).fetchone()
        value = str(row[0]) if row else "empty"
        self._fingerprint = (now, value)
        return value

    def lookup(self, namespace: str, question: str, vector: VectorFn) -> CacheHit | None:
        from psycopg import sql

        t = sql.Identifier(self.table)
        fresh = sql.SQL("created_at > now() - make_interval(hours => {h})").format(
            h=sql.Literal(self.ttl_hours)
        )
        with self.pg.connect() as conn:
            row = conn.execute(
                sql.SQL(
                    "SELECT id, answer, question, 1.0 FROM {t} "
                    "WHERE namespace = %s AND question_norm = %s AND {fresh}"
                ).format(t=t, fresh=fresh),
                (namespace, normalise_question(question)),
            ).fetchone()
            kind: CacheKind = "exact"
            if row is None and self.semantic_threshold is not None:
                v = list(vector())
                row = conn.execute(
                    sql.SQL(
                        "SELECT id, answer, question, 1 - (embedding <=> %s::vector) AS sim "
                        "FROM {t} WHERE namespace = %s AND {fresh} "
                        "ORDER BY embedding <=> %s::vector LIMIT 1"
                    ).format(t=t, fresh=fresh),
                    (v, namespace, v),
                ).fetchone()
                kind = "semantic"
                if row is not None and float(row[3]) < self.semantic_threshold:
                    row = None
            if row is None:
                return None
            _touch(conn, self.table, int(row[0]))
        return CacheHit(answer_from_json(row[1]), kind, float(row[3]), str(row[2]))

    def store(self, namespace: str, question: str, vector: Sequence[float], answer: Answer) -> None:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        with self.pg.connect() as conn:
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {t} (namespace, question, question_norm, embedding, answer)
                    VALUES (%s, %s, %s, %s::vector, %s)
                    ON CONFLICT (namespace, question_norm) DO UPDATE
                    SET answer = EXCLUDED.answer, embedding = EXCLUDED.embedding,
                        question = EXCLUDED.question, created_at = now(), hits = 0
                    """
                ).format(t=sql.Identifier(self.table)),
                (
                    namespace,
                    question,
                    normalise_question(question),
                    list(vector),
                    Jsonb(answer_to_json(answer)),
                ),
            )


def _touch(conn: Connection, table: str, row_id: int) -> None:
    from psycopg import sql

    conn.execute(
        sql.SQL("UPDATE {t} SET hits = hits + 1, last_hit_at = now() WHERE id = %s").format(
            t=sql.Identifier(table)
        ),
        (row_id,),
    )


# --- the wrapper ---------------------------------------------------------------------


class CachedAnswerer:
    """Look up before answering; store after. Wraps the pipeline or the agent."""

    def __init__(
        self,
        inner: Answerer,
        cache: AnswerCache,
        embeddings: Embeddings,
        config: dict[str, object],
    ) -> None:
        self.inner = inner
        self.cache = cache
        self.embeddings = embeddings
        self.tracer: Tracer = inner.tracer
        # Everything that changes an answer, except the corpus (checked per request).
        self._config = json.dumps(config, sort_keys=True, default=str)

    def namespace(self) -> str:
        key = f"{self._config}|corpus={self.cache.corpus_fingerprint()}"
        return hashlib.sha256(key.encode()).hexdigest()[:24]

    def answer(self, question: str) -> Answer:
        for event in self.stream(question):
            if isinstance(event, DoneEvent):
                return event.answer
        raise RuntimeError("stream ended without a final answer")  # pragma: no cover

    def stream(self, question: str) -> Iterator[StreamEvent]:
        start = time.perf_counter()
        namespace = self.namespace()
        embedded: list[Sequence[float]] = []

        def vector() -> Sequence[float]:  # at most once, and only when it's needed
            if not embedded:
                embedded.append(self.embeddings.embed_query(question))
            return embedded[0]

        hit = self.cache.lookup(namespace, question, vector)
        if hit is not None:
            yield from self._replay(question, hit, start)
            return

        for event in self.inner.stream(question):
            if isinstance(event, DoneEvent):
                answer = event.answer
                if answer.model and (answer.input_tokens or answer.output_tokens):
                    self.cache.store(namespace, question, vector(), answer)
            yield event

    def _replay(self, question: str, hit: CacheHit, start: float) -> Iterator[StreamEvent]:
        cached = hit.answer
        with self.tracer.observe(
            "cache.hit", input={"kind": hit.kind, "similarity": round(hit.similarity, 4)}
        ) as span:
            span.update(output={"cached_question": hit.cached_question})
        yield SourcesEvent(cached.retrieved)
        elapsed = (time.perf_counter() - start) * 1000
        yield TokenEvent(cached.text)
        yield DoneEvent(
            replace(
                cached,
                question=question,
                # Nothing was generated: no tokens, no cost. What it would have cost is kept.
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal(0),
                cost_saved_usd=cached.cost_usd,
                tokens_saved=cached.input_tokens + cached.output_tokens,
                cache=hit.kind,
                cache_similarity=hit.similarity,
                retrieval_ms=elapsed,
                time_to_first_token_ms=elapsed,
                total_ms=(time.perf_counter() - start) * 1000,
                searches=0,
            )
        )
