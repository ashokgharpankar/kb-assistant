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
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from kb_core.models import Chunk, SourceDocument

# Bump when the chunking or cleaning logic changes, so every document is re-chunked.
# 3: heading-path sections, "Resources" blocks removed, optional chunk headers.
CHUNKER_VERSION = "3"

# Words that mark a "Resources" block: lists of related documents and talks.
_REFERENCE_MARKERS = re.compile(
    r"related (documents|videos|examples|tools|best practices|services)\s*:|re:invent|aws summit",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*([•\-*–]|\d+\.)\s+")

# The start of a "Resources" block at the end of a best practice...
_RESOURCES_START = re.compile(
    r"^\s*(resources|related (documents|videos|examples|tools|best practices|services)\s*:)\s*$",
    re.IGNORECASE,
)
# ...and lines that end it: the next best practice ("REL10-BP02 ...") or a known
# subheading of the next one. Everything in between is a list of titles and links.
_RESOURCES_END = re.compile(
    r"^\s*([A-Z]{2,5}\d{2,3}-BP\d{2,3}\b|implementation guidance\b|implementation steps\b|"
    r"desired outcome\b|common anti-patterns\b|benefits of establishing\b|level of risk exposed\b)",
    re.IGNORECASE,
)


def strip_resources(text: str) -> str:
    """Remove "Resources" / "Related …:" blocks (link and talk-title lists) from a chunk.

    Investigation 0001 found ~10% of chunks were guidance followed by such a list;
    the whole-chunk filter below can't catch those, because they are mostly guidance.
    """
    kept: list[str] = []
    in_block = False
    for line in text.split("\n"):
        if _RESOURCES_START.match(line):
            in_block = True
            continue
        if in_block and _RESOURCES_END.match(line):
            in_block = False
        if not in_block:
            kept.append(line)
    return "\n".join(kept).strip()


def is_reference_list(text: str) -> bool:
    """True for chunks that are mostly a list of links and titles, not guidance.

    Such chunks score high in search (they are *about* the topic) but give the model
    nothing to say, and invite misleading citations: a talk title like
    "Shuffle-sharding: AWS re:Invent 2019" turned into "implement shuffle-sharding [3]".
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    bullets = sum(1 for line in lines if _BULLET.match(line))
    has_marker = bool(_REFERENCE_MARKERS.search(text))
    return has_marker and bullets / len(lines) >= 0.6


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
            # Trimming after splitting keeps start_index (and so the page) correct.
            text = strip_resources(piece.page_content)
            if len(text) < 40:  # headings or stray fragments: no value as evidence
                continue
            if is_reference_list(text):  # link lists: relevant-looking, no guidance
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


def embedding_text(chunk: Chunk, with_header: bool) -> str:
    """What gets embedded: the chunk, optionally under its heading path.

    "Security > Design principles" above a bullet list makes the list match a question
    about design principles; the bare list never says what it is (Phase 3 finding).
    The stored chunk text stays as is; only the vector changes.
    """
    return f"{chunk.section}\n\n{chunk.text}" if with_header else chunk.text


def content_fingerprint(
    doc: SourceDocument, chunk_size: int, chunk_overlap: int, chunk_headers: bool = True
) -> str:
    """Changes when the text OR the chunking settings change. Used to skip unchanged documents."""
    h = hashlib.sha256()
    h.update(
        f"chunker={CHUNKER_VERSION};size={chunk_size};overlap={chunk_overlap};"
        f"headers={chunk_headers}\n".encode()
    )
    for section in doc.sections:
        h.update(section.title.encode())
        h.update(b"\x00")
        h.update(section.text.encode())
    return h.hexdigest()
