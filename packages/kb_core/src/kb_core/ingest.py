"""Ingestion pipeline: load -> chunk -> embed -> store, skipping what has not changed."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.embeddings import Embeddings

from kb_core.chunking import chunk_document, content_fingerprint
from kb_core.loaders import discover, load_file
from kb_core.store import PgVectorStore

# Embedding calls are batched: one request per batch instead of one per chunk.
EMBED_BATCH = 32


@dataclass
class DocumentResult:
    document_id: str
    status: str  # "ingested" | "unchanged" | "failed"
    chunks: int = 0
    characters: int = 0
    seconds: float = 0.0
    error: str = ""


@dataclass
class IngestReport:
    results: list[DocumentResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(r.status == "ingested" for r in self.results)

    @property
    def unchanged(self) -> int:
        return sum(r.status == "unchanged" for r in self.results)

    @property
    def failed(self) -> int:
        return sum(r.status == "failed" for r in self.results)

    @property
    def chunks(self) -> int:
        return sum(r.chunks for r in self.results)

    @property
    def characters(self) -> int:
        return sum(r.characters for r in self.results)


def embed_in_batches(
    embeddings: Embeddings, texts: list[str], batch: int = EMBED_BATCH
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        vectors.extend(embeddings.embed_documents(texts[i : i + batch]))
    return vectors


def ingest_path(
    root: Path,
    store: PgVectorStore,
    embeddings: Embeddings,
    chunk_size: int,
    chunk_overlap: int,
    force: bool = False,
    on_progress: Callable[[DocumentResult], None] | None = None,
) -> IngestReport:
    report = IngestReport()
    for path in discover(root):
        started = time.perf_counter()
        try:
            doc = load_file(path)
            fingerprint = content_fingerprint(doc, chunk_size, chunk_overlap)
            if not force and store.fingerprint_of(doc.document_id) == fingerprint:
                result = DocumentResult(doc.document_id, "unchanged")
            else:
                chunks = chunk_document(doc, chunk_size, chunk_overlap)
                vectors = embed_in_batches(embeddings, [c.text for c in chunks])
                store.replace_document(doc, fingerprint, chunks, vectors)
                result = DocumentResult(
                    doc.document_id, "ingested", len(chunks), sum(len(c.text) for c in chunks)
                )
        except Exception as exc:  # one bad file must not stop the run
            result = DocumentResult(path.name, "failed", error=f"{type(exc).__name__}: {exc}")
        result.seconds = time.perf_counter() - started
        report.results.append(result)
        if on_progress:
            on_progress(result)
    return report
