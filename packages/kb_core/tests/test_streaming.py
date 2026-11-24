"""Streaming order, timing and tracing, with fakes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from kb_core.models import Chunk, DoneEvent, RetrievedChunk, SourcesEvent, TokenEvent
from kb_core.rag import NOT_FOUND, RagPipeline
from kb_core.settings import Settings
from kb_core.tracing import NoopTracer, ObservationType, build_tracer

from .conftest import WordHashEmbeddings, fake_model

HIT = RetrievedChunk(
    chunk=Chunk(
        "fw:00001", "fw", 1, "Deploy across multiple Availability Zones.", "Reliability", 42
    ),
    document_title="Framework",
    uri="file:///fw.pdf",
    similarity=0.81,
)


class RecordingTracer:
    """Remembers every observation, its parent and the fields recorded on it."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._stack: list[str] = []

    @contextmanager
    def observe(self, name: str, as_type: ObservationType = "span", **fields: Any) -> Iterator[Any]:
        record: dict[str, Any] = {
            "name": name,
            "type": as_type,
            "parent": self._stack[-1] if self._stack else None,
            **fields,
        }
        self.records.append(record)
        self._stack.append(name)

        class Obs:
            def update(self, **more: Any) -> None:
                record.update(more)

        try:
            yield Obs()
        finally:
            self._stack.pop()

    def flush(self) -> None:
        pass

    def get(self, name: str) -> dict[str, Any]:
        return next(r for r in self.records if r["name"] == name)


def _pipeline(hits: list[RetrievedChunk], reply: str, tracer: Any = None) -> RagPipeline:
    return RagPipeline(
        search=lambda v, k, m: hits,
        embeddings=WordHashEmbeddings(),
        chat_model=fake_model(reply),
        model_id="amazon.nova-micro-v1:0",
        k=4,
        min_similarity=0.4,
        tracer=tracer,
    )


def test_events_arrive_sources_then_tokens_then_done() -> None:
    events = list(_pipeline([HIT], "Use multiple Availability Zones [1].").stream("How?"))
    assert isinstance(events[0], SourcesEvent)
    tokens = [e.text for e in events if isinstance(e, TokenEvent)]
    assert len(tokens) > 1  # really streamed, not one blob
    assert "".join(tokens) == "Use multiple Availability Zones [1]."
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.answer.text == "Use multiple Availability Zones [1]."


def test_timings_are_recorded() -> None:
    answer = _pipeline([HIT], "Spread across zones [1].").answer("How?")
    assert answer.time_to_first_token_ms is not None
    assert 0 <= answer.retrieval_ms <= answer.time_to_first_token_ms <= answer.total_ms


def test_not_found_streams_no_tokens() -> None:
    events = list(_pipeline([], "unused").stream("Capital of France?"))
    assert [type(e) for e in events] == [SourcesEvent, DoneEvent]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.answer.text == NOT_FOUND
    assert done.answer.time_to_first_token_ms is None


def test_trace_has_retrieve_and_generate_under_one_root() -> None:
    tracer = RecordingTracer()
    _pipeline([HIT], "Spread across zones [1].", tracer).answer("How do I stay up?")

    root, retrieve, generate = (tracer.get(n) for n in ("rag.answer", "retrieve", "generate"))
    assert root["parent"] is None and root["type"] == "chain"
    assert retrieve["parent"] == "rag.answer" and retrieve["type"] == "retriever"
    assert generate["parent"] == "rag.answer" and generate["type"] == "generation"

    assert retrieve["output"][0] == {
        "chunk_id": "fw:00001",
        "section": "Reliability",
        "page": 42,
        "similarity": 0.81,
        "rerank_score": None,
    }
    assert generate["model"] == "amazon.nova-micro-v1:0"
    assert generate["usage_details"] == {"input": 1000, "output": 100}
    assert generate["cost_details"]["total"] > 0
    assert root["metadata"]["citations"] == [1]


def test_not_found_trace_has_no_generation() -> None:
    tracer = RecordingTracer()
    _pipeline([], "unused", tracer).answer("Capital of France?")
    assert [r["name"] for r in tracer.records] == ["rag.answer", "retrieve"]


def test_tracing_is_off_without_keys() -> None:
    assert isinstance(build_tracer(Settings(_env_file=None)), NoopTracer)
