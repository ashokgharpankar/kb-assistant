"""API entry point.

GET  /health      open: liveness, version, provider, auth mode
POST /ask         signed in: one JSON response when the answer is complete
POST /ask/stream  signed in: Server-Sent Events: sources, tokens as they're written, done

Endpoints receive what they need through FastAPI dependencies (Depends): the
pipeline, the signed-in user. Tests and the demo swap them with
app.dependency_overrides, without touching module globals.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from kb_core import __version__
from kb_core.factory import build_pipeline
from kb_core.models import Answer, DoneEvent, SourcesEvent, StreamEvent, TokenEvent
from kb_core.settings import get_settings

from .auth import CurrentUser, get_verifier

# Our own log lines (errors, early stops) next to uvicorn's. No-op if logging is
# already configured, for example by a production log setup.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
log = logging.getLogger("kb_api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Fail at startup, not on the first request: Cognito switched on but not
    # configured stops the server with a clear message.
    verifier = get_verifier()
    log.info("auth: %s", "cognito" if verifier else "DISABLED (local only)")
    yield


app = FastAPI(title="KB Assistant API", version=__version__, lifespan=lifespan)


class Health(BaseModel):
    status: str
    version: str
    env: str
    llm_provider: str
    auth: str


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


class Pipeline(Protocol):
    """What the endpoints need from a pipeline. RagPipeline fits; so do test fakes."""

    def stream(self, question: str) -> Iterator[StreamEvent]: ...

    def answer(self, question: str) -> Answer: ...


@lru_cache
def get_pipeline() -> Pipeline:
    return build_pipeline(get_settings())  # built once: model clients, DB pool


def provider_label() -> str:
    """What /health reports as the model provider (the demo overrides it)."""
    return get_settings().llm_provider


PipelineDep = Annotated[Pipeline, Depends(get_pipeline)]


@app.get("/health")
def health(provider: Annotated[str, Depends(provider_label)]) -> Health:
    s = get_settings()
    return Health(
        status="ok", version=__version__, env=s.env, llm_provider=provider, auth=s.auth_mode
    )


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
def ask(body: AskRequest, pipeline: PipelineDep, user: CurrentUser) -> AskResponse:
    log.info("ask user=%s", user.sub)
    try:
        answer = pipeline.answer(body.question)
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


def event_stream(pipeline: Pipeline, question: str) -> Iterator[str]:
    try:
        for event in pipeline.stream(question):
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
def ask_stream(
    body: AskRequest, request: Request, pipeline: PipelineDep, user: CurrentUser
) -> StreamingResponse:
    # The token is checked before the first byte is sent, so a bad token is a
    # plain 401, not an error event inside a 200 stream.
    log.info("ask/stream user=%s", user.sub)
    return StreamingResponse(
        stop_on_disconnect(request, event_stream(pipeline, body.question)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # stop reverse proxies (nginx, some ALB setups) buffering the stream
        },
    )
