"""Split documents into chunks small enough to embed and to quote.

Strategy (see ADR 0004):
- Split *within* a section, never across sections, so a chunk is about one topic
  and carries one section title.
- Recursive splitting: try paragraph breaks first, then lines, then sentences,
  then words, so cuts land on natural boundaries.
- Overlap between neighbouring chunks, so a sentence cut at a boundary still
  appears whole in one of them.
- `add_start_index` gives each chunk's offset in its section, which maps back
  to the exact page for citations.
"""

from __future__ import annotations

import hashlib

from langchain_text_splitters import RecursiveCharacterTextSplitter

from kb_core.models import Chunk, SourceDocument

# Bump when the chunking logic changes, so every document is re-chunked.
CHUNKER_VERSION = "1"

_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def make_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
        keep_separator="end",
        add_start_index=True,
        strip_whitespace=True,
    )


def chunk_document(doc: SourceDocument, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    splitter = make_splitter(chunk_size, chunk_overlap)
    chunks: list[Chunk] = []
    for section in doc.sections:
        for piece in splitter.create_documents([section.text]):
            text = piece.page_content.strip()
            if len(text) < 40:  # headings or stray fragments: no value as evidence
                continue
            start = int(piece.metadata.get("start_index", 0))
            ordinal = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.document_id}:{ordinal:05d}",
                    document_id=doc.document_id,
                    ordinal=ordinal,
                    text=text,
                    section=section.title,
                    page=section.page_at(max(start, 0)),
                )
            )
    return chunks


def content_fingerprint(doc: SourceDocument, chunk_size: int, chunk_overlap: int) -> str:
    """Changes when the text OR the chunking settings change. Used to skip unchanged documents."""
    h = hashlib.sha256()
    h.update(f"chunker={CHUNKER_VERSION};size={chunk_size};overlap={chunk_overlap}\n".encode())
    for section in doc.sections:
        h.update(section.title.encode())
        h.update(b"\x00")
        h.update(section.text.encode())
    return h.hexdigest()
