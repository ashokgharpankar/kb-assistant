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


@dataclass(frozen=True)
class Grounding:
    """How well an answer's sentences are backed by the sources they cite (Phase 7b)."""

    score: float | None  # supported claims / claims; None when there were no claims
    claims: int
    supported: int
    unsupported: list[str] = field(default_factory=list)  # sentences, for traces and eval
    unknown_terms: list[str] = field(default_factory=list)  # terms in no retrieved chunk


@dataclass(frozen=True)
class Escalation:
    """The first model's attempt when routing passed the question on (Phase 8b): what it
    cost, so the answer's total cost includes the call that didn't make it."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    reason: str  # "refused_with_evidence"


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
    # How the answer was reached: the pipeline always searches once; the agent (Phase 5b)
    # may search again and records each step.
    searches: int = 1
    steps: list[str] = field(default_factory=list)
    # Guardrails (Phase 7b): why the question was blocked before retrieval, if it was,
    # and the grounding check of the generated text.
    blocked_by: str | None = None
    grounding: Grounding | None = None
    # Answer cache (Phase 8a): "exact" or "semantic" when served from the cache, how
    # close the cached question was, and what the model call would have cost.
    cache: str | None = None
    cache_similarity: float | None = None
    cost_saved_usd: Decimal = Decimal(0)
    tokens_saved: int = 0
    # Routing (Phase 8b): set when a smaller model's attempt came first. `model` and the
    # token fields above describe the model that wrote this text.
    escalation: Escalation | None = None
    # Spend cap (Phase 8b): "economy" when the daily budget's soft limit turned routing
    # off for this answer. Degraded answers are never cached.
    degraded: str | None = None

    @property
    def total_cost_usd(self) -> Decimal:
        return self.cost_usd + (self.escalation.cost_usd if self.escalation else Decimal(0))

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + (self.escalation.input_tokens if self.escalation else 0)

    @property
    def total_output_tokens(self) -> int:
        return self.output_tokens + (self.escalation.output_tokens if self.escalation else 0)


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


@dataclass(frozen=True)
class EscalateEvent:
    """Routing passed the question to a larger model (Phase 8b). `reset` is True when the
    first model's text was already streamed: the client discards it and starts again."""

    from_model: str
    to_model: str
    reset: bool


StreamEvent = SourcesEvent | TokenEvent | EscalateEvent | DoneEvent
