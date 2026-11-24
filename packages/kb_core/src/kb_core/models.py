"""Domain types shared by every stage of the RAG pipeline.

Keeping these as plain, typed objects (not LangChain `Document`s) means the
pipeline's contract is ours. LangChain is used inside the stages, not as the
shape of the data passed between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Section:
    """A run of text under one heading, with the page each character came from."""

    title: str
    text: str
    # (offset_in_text, page_number): page_number applies from that offset onward.
    page_starts: tuple[tuple[int, int], ...]

    def page_at(self, offset: int) -> int:
        page = self.page_starts[0][1]
        for start, number in self.page_starts:
            if start > offset:
                break
            page = number
        return page


@dataclass(frozen=True)
class SourceDocument:
    """One loaded file, already split into sections."""

    document_id: str  # stable: derived from the file name, so re-ingest updates in place
    title: str
    uri: str
    sections: tuple[Section, ...]

    @property
    def full_text(self) -> str:
        return "\n\n".join(s.text for s in self.sections)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    section: str
    page: int


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    document_title: str
    uri: str
    similarity: float  # cosine similarity, 1.0 = identical direction
    fused_score: float | None = None  # hybrid search: reciprocal rank fusion score
    rerank_score: float | None = None  # reranker relevance, 0..1 (higher = more relevant)


@dataclass(frozen=True)
class Citation:
    number: int
    document_title: str
    section: str
    page: int
    uri: str
    similarity: float


@dataclass
class Answer:
    question: str
    text: str
    citations: list[Citation] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    answered_from_context: bool = True
    # Latency, in milliseconds. Time to first token is what a user feels when streaming.
    retrieval_ms: float = 0.0
    time_to_first_token_ms: float | None = None
    total_ms: float = 0.0


# --- streaming events ----------------------------------------------------------
# The pipeline yields these in order: Sources once, Token many times, Done once.


@dataclass(frozen=True)
class SourcesEvent:
    retrieved: list[RetrievedChunk]


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class DoneEvent:
    answer: Answer


StreamEvent = SourcesEvent | TokenEvent | DoneEvent
