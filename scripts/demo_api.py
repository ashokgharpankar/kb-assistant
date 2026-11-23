"""Run the real API with a scripted pipeline: no Ollama, Bedrock or database.

For UI work and demos:  make web-demo   (API on :8000, then `make web-dev`)

Sign-in is off by default here. To test the sign-in flow without Ollama, run
`KB_AUTH_MODE=cognito make web-demo` (Cognito values from .env).

The answer is streamed word by word with a short delay, so the UI behaves as it
does with a real model. Ask anything containing "weather" to see the not-found path.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import uvicorn

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
from kb_core.rag import NOT_FOUND

TITLE = "AWS Well-Architected Framework"
HITS = [
    RetrievedChunk(
        Chunk("demo:1", "demo", 1, text, "Framework > Reliability", page),
        TITLE,
        "file:///demo.pdf",
        similarity,
    )
    for text, page, similarity in [
        (
            "Design your workload to withstand component failures. Hardware faults, software "
            "defects, network partitions, and the loss of an Availability Zone may all occur in "
            "the normal course of operation.",
            765,
            0.746,
        ),
        (
            "A dampening period prevents the workload from failing back before the primary "
            "location is stable. Common anti-patterns: teams treat failure planning as an "
            "afterthought.",
            770,
            0.745,
        ),
        (
            "Apply the circuit breaker pattern to a dependency that is failing under load. After "
            "failures cross a threshold, stop calling the dependency for a while.",
            657,
            0.732,
        ),
    ]
]
ANSWER = (
    "To design for failure:\n\n"
    "* Expect **component failures** and keep serving customers when they happen [1].\n"
    "* Apply the circuit breaker pattern to dependencies that fail under load [3].\n"
    "* Use static stability to avoid bimodal behaviour [REL11-BP05].\n"
    "* Fail back only after a dampening period [7]."
)


class DemoPipeline:
    def stream(self, question: str) -> Iterator[StreamEvent]:
        started = time.perf_counter()
        time.sleep(0.4)  # "retrieval"
        if "weather" in question.lower():
            yield SourcesEvent([])
            yield DoneEvent(
                Answer(question=question, text=NOT_FOUND, model="demo", answered_from_context=False)
            )
            return
        yield SourcesEvent(HITS)
        time.sleep(0.6)  # time to first token
        ttft = (time.perf_counter() - started) * 1000
        for word in ANSWER.split(" "):
            time.sleep(0.04)
            yield TokenEvent(word + " ")
        yield DoneEvent(
            Answer(
                question=question,
                text=ANSWER,
                citations=[
                    Citation(n, TITLE, h.chunk.section, h.chunk.page, h.uri, h.similarity)
                    for n, h in ((1, HITS[0]), (3, HITS[2]))
                ],
                model="demo",
                input_tokens=1055,
                output_tokens=74,
                time_to_first_token_ms=ttft,
                total_ms=(time.perf_counter() - started) * 1000,
            )
        )

    def answer(self, question: str) -> Answer:
        for event in self.stream(question):
            if isinstance(event, DoneEvent):
                return event.answer
        raise RuntimeError("stream ended without an answer")


if __name__ == "__main__":
    # An environment variable beats .env, so this turns sign-in off for the demo
    # unless you exported KB_AUTH_MODE yourself.
    os.environ.setdefault("KB_AUTH_MODE", "disabled")
    # Swap the real dependencies for demo ones, the same way the tests do.
    main.app.dependency_overrides[main.get_pipeline] = DemoPipeline
    main.app.dependency_overrides[main.provider_label] = lambda: "demo"
    uvicorn.run(main.app, host="127.0.0.1", port=8000)
