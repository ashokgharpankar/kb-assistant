import json
from collections.abc import Iterator
from typing import Any

from fastapi.testclient import TestClient

from kb_api import main
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

HIT = RetrievedChunk(
    Chunk("f:1", "f", 1, "Use AZs.", "Reliability", 12), "Framework", "file:///f.pdf", 0.81234
)


class FakePipeline:
    def stream(self, question: str) -> Iterator[StreamEvent]:
        yield SourcesEvent([HIT])
        yield TokenEvent("Use multiple ")
        yield TokenEvent("Availability Zones [1].\nDone")
        yield DoneEvent(self.answer(question))

    def answer(self, question: str) -> Answer:
        return Answer(
            question=question,
            text="Use multiple Availability Zones [1].",
            citations=[Citation(1, "Framework", "Reliability", 12, "file:///f.pdf", 0.81234)],
            model="llama3.2",
            input_tokens=900,
            output_tokens=40,
        )


def use(pipeline: object) -> None:
    main.app.dependency_overrides[main.get_pipeline] = lambda: pipeline


def test_ask_returns_answer_with_citations() -> None:
    use(FakePipeline())
    response = TestClient(main.app).post("/ask", json={"question": "How do I stay available?"})
    assert response.status_code == 200
    body = response.json()
    assert body["citations"][0] == {
        "number": 1,
        "document_title": "Framework",
        "section": "Reliability",
        "page": 12,
        "similarity": 0.8123,
    }
    assert body["cost_usd"] == "0"


def test_ask_validates_input() -> None:
    use(FakePipeline())
    response = TestClient(main.app).post("/ask", json={"question": "x"})
    assert response.status_code == 422


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_stream_sends_sources_tokens_then_done() -> None:
    use(FakePipeline())
    with TestClient(main.app).stream("POST", "/ask/stream", json={"question": "How?"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = parse_sse(body)
    assert [name for name, _ in events] == ["sources", "token", "token", "done"]
    assert events[0][1] == [
        {
            "number": 1,
            "document_title": "Framework",
            "section": "Reliability",
            "page": 12,
            "similarity": 0.8123,
            "excerpt": "Use AZs.",
        }
    ]
    # a newline inside a token survives the SSE framing
    assert events[2][1] == {"text": "Availability Zones [1].\nDone"}
    assert events[3][1]["citations"][0]["number"] == 1


def test_stream_failure_becomes_an_error_event() -> None:
    class Broken:
        def stream(self, question: str) -> Iterator[StreamEvent]:
            yield SourcesEvent([])
            raise RuntimeError("ollama is down at 10.0.0.5")

    use(Broken())
    with TestClient(main.app).stream("POST", "/ask/stream", json={"question": "How?"}) as response:
        body = "".join(response.iter_text())
    events = parse_sse(body)
    assert events[-1] == ("error", {"detail": "answering is temporarily unavailable"})
    assert "10.0.0.5" not in body  # internals never reach the client


def test_excerpt_is_one_line_and_cut_at_a_word() -> None:
    assert main.excerpt("Use\n  multiple   AZs.") == "Use multiple AZs."
    long = "word " * 100
    cut = main.excerpt(long, limit=22)
    assert cut == "word word word word…"
    assert len(cut) <= 23


def test_generation_stops_when_the_client_disconnects() -> None:
    import asyncio

    produced: list[int] = []
    closed: list[bool] = []

    def events() -> Iterator[str]:
        try:
            for i in range(100):
                produced.append(i)
                yield f"token {i}"
        finally:
            closed.append(True)

    class Request:
        def __init__(self) -> None:
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks > 2  # the browser leaves after two events

    async def consume() -> list[str]:
        return [chunk async for chunk in main.stop_on_disconnect(Request(), events())]

    received = asyncio.run(consume())
    assert received == ["token 0", "token 1"]
    assert len(produced) < 100  # the model did not run to the end
    assert closed == [True]  # cleanup ran, so tracing spans close
