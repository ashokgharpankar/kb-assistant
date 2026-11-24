"""Ingestion pipeline: load -> chunk -> embed -> store, skipping what has not changed."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.embeddings import Embeddings

from kb_core.chunking import chunk_document, content_fingerprint, embedding_text
from kb_core.loaders import DEFAULT_TOC_DEPTH, discover, document_id_for, load_file
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
    removed: list[str] = field(default_factory=list)

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
    prune: bool = False,
    toc_depth: int = DEFAULT_TOC_DEPTH,
    chunk_headers: bool = True,
) -> IngestReport:
    """Ingest every supported file under `root`.

    With `prune`, documents in the store whose file is no longer under `root`
    are deleted, so the index matches the folder.
    """
    if prune and not root.is_dir():
        # Pruning against a single file would delete every other document.
        raise ValueError("prune needs a folder: it deletes documents not found in that folder")
    report = IngestReport()
    seen: set[str] = set()
    for path in discover(root):
        seen.add(document_id_for(path))
        started = time.perf_counter()
        try:
            doc = load_file(path, toc_depth)
            fingerprint = content_fingerprint(doc, chunk_size, chunk_overlap, chunk_headers)
            if not force and store.fingerprint_of(doc.document_id) == fingerprint:
                result = DocumentResult(doc.document_id, "unchanged")
            else:
                chunks = chunk_document(doc, chunk_size, chunk_overlap)
                vectors = embed_in_batches(
                    embeddings, [embedding_text(c, chunk_headers) for c in chunks]
                )
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

    if prune:
        for document_id in store.document_ids():
            if document_id not in seen and store.delete_document(document_id):
                report.removed.append(document_id)
    return report
