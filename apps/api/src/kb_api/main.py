"""API entry point.

POST /ask         one JSON response when the answer is complete
POST /ask/stream  Server-Sent Events: sources, then tokens as they're written, then done
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from functools import lru_cache
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from kb_core import __version__
from kb_core.factory import build_pipeline
from kb_core.models import Answer, DoneEvent, SourcesEvent, TokenEvent
from kb_core.rag import RagPipeline
from kb_core.settings import get_settings

# Our own log lines (errors, early stops) next to uvicorn's. No-op if logging is
# already configured, for example by a production log setup.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
log = logging.getLogger("kb_api")

app = FastAPI(title="KB Assistant API", version=__version__)


class Health(BaseModel):
    status: str
    version: str
    env: str
    llm_provider: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class CitationOut(BaseModel):
    number: int
    document_title: str
    section: str
    page: int
    similarity: float


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    answered_from_context: bool
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: str  # string so no precision is lost in JSON
    time_to_first_token_ms: float | None = None
    total_ms: float = 0.0


@lru_cache
def get_pipeline() -> RagPipeline:
    return build_pipeline(get_settings())


def provider_label() -> str:
    """What /health reports as the model provider (the demo script overrides it)."""
    return get_settings().llm_provider


@app.get("/health")
def health() -> Health:
    s = get_settings()
    return Health(status="ok", version=__version__, env=s.env, llm_provider=provider_label())


def to_response(answer: Answer) -> AskResponse:
    return AskResponse(
        answer=answer.text,
        citations=[
            CitationOut(
                number=c.number,
                document_title=c.document_title,
                section=c.section,
                page=c.page,
                similarity=round(c.similarity, 4),
            )
            for c in answer.citations
        ],
        answered_from_context=answer.answered_from_context,
        model=answer.model,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        cost_usd=str(answer.cost_usd),
        time_to_first_token_ms=answer.time_to_first_token_ms,
        total_ms=answer.total_ms,
    )


@app.post("/ask")
def ask(request: AskRequest) -> AskResponse:
    try:
        answer = get_pipeline().answer(request.question)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("ask failed")  # full detail in our logs, generic message to the client
        raise HTTPException(status_code=503, detail="answering is temporarily unavailable") from exc
    return to_response(answer)


EXCERPT_CHARS = 300


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """A short, single-line preview of a chunk for the UI's source list."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def sse(event: str, data: Any) -> str:
    """One Server-Sent Event. JSON-encoding the data keeps newlines inside tokens safe."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def event_stream(question: str) -> Iterator[str]:
    try:
        for event in get_pipeline().stream(question):
            if isinstance(event, SourcesEvent):
                yield sse(
                    "sources",
                    [
                        {
                            "number": i,
                            "document_title": r.document_title,
                            "section": r.chunk.section,
                            "page": r.chunk.page,
                            "similarity": round(r.similarity, 4),
                            "excerpt": excerpt(r.chunk.text),
                        }
                        for i, r in enumerate(event.retrieved, start=1)
                    ],
                )
            elif isinstance(event, TokenEvent):
                yield sse("token", {"text": event.text})
            elif isinstance(event, DoneEvent):
                yield sse("done", to_response(event.answer).model_dump())
    except Exception:
        # Headers (200) are already sent once streaming starts, so errors travel as an event.
        log.exception("stream failed")
        yield sse("error", {"detail": "answering is temporarily unavailable"})


class Disconnectable(Protocol):
    """The one thing stop_on_disconnect needs from a request (eases testing)."""

    async def is_disconnected(self) -> bool: ...


async def stop_on_disconnect(request: Disconnectable, events: Iterator[str]) -> AsyncIterator[str]:
    """Stop generating when the browser goes away (Stop button, closed tab).

    Without this, an abandoned answer keeps running to the end, and its output
    tokens are still paid for. The pipeline is synchronous, so each step runs in
    a worker thread; between steps we check the connection.
    """
    try:
        async for chunk in iterate_in_threadpool(events):
            if await request.is_disconnected():
                log.info("client disconnected; generation stopped early")
                break
            yield chunk
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            try:
                close()  # ends the model stream and closes the tracing spans
            except ValueError:
                # Cancelled while a step was still running in its thread; that step
                # finishes on its own and the generator is cleaned up afterwards.
                log.debug("stream close skipped: step still running")


@app.post("/ask/stream")
def ask_stream(body: AskRequest, request: Request) -> StreamingResponse:
    return StreamingResponse(
        stop_on_disconnect(request, event_stream(body.question)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # stop reverse proxies (nginx, some ALB setups) buffering the stream
        },
    )
