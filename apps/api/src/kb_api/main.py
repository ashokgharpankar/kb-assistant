"""API entry point.

GET  /health      open: liveness, version, provider, auth mode
GET  /metrics     open on the API port only: Prometheus metrics (Phase 7a); not routed by nginx
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
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from kb_core import __version__
from kb_core.factory import build_answerer
from kb_core.models import (
    Answer,
    DoneEvent,
    EscalateEvent,
    SourcesEvent,
    StreamEvent,
    TokenEvent,
)
from kb_core.settings import get_settings

from . import metrics
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
    s = get_settings()
    metrics.BUILD_INFO.labels(
        version=__version__, env=s.env, provider=s.llm_provider, mode=s.answer_mode
    ).set(1)
    yield


app = FastAPI(title="KB Assistant API", version=__version__, lifespan=lifespan)
app.middleware("http")(metrics.http_metrics_middleware)


def answer_mode() -> str:
    return get_settings().answer_mode


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
    # Phase 7b grounding check: share of the answer's claims backed by the sources they
    # cite, the sentences that weren't, and names that appear in no retrieved source.
    grounding_score: float | None = None
    unsupported: list[str] = []
    unknown_terms: list[str] = []
    # Phase 8a answer cache: "exact" or "semantic" when served from the cache (no model
    # call), the similarity of the cached question, and what the model call would have cost.
    cache: str | None = None
    cache_similarity: float | None = None
    cost_saved_usd: str = "0"
    # Phase 8b: the model that tried first when routing escalated, and the spend-cap level
    # ("economy" or "over_budget") when it changed the answer. cost_usd is the total.
    escalated_from: str | None = None
    degraded: str | None = None


class Pipeline(Protocol):
    """What the endpoints need from a pipeline. RagPipeline and RetrievalAgent fit; so do test fakes."""

    def stream(self, question: str) -> Iterator[StreamEvent]: ...

    def answer(self, question: str) -> Answer: ...


@lru_cache
def get_pipeline() -> Pipeline:
    return build_answerer(get_settings())  # pipeline or agent (KB_ANSWER_MODE); built once


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


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)


def to_response(answer: Answer) -> AskResponse:
    g = answer.grounding
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
        input_tokens=answer.total_input_tokens,
        output_tokens=answer.total_output_tokens,
        cost_usd=str(answer.total_cost_usd),
        time_to_first_token_ms=answer.time_to_first_token_ms,
        total_ms=answer.total_ms,
        grounding_score=None if g is None or g.score is None else round(g.score, 3),
        unsupported=[] if g is None else list(g.unsupported),
        unknown_terms=[] if g is None else list(g.unknown_terms),
        cache=answer.cache,
        cache_similarity=None
        if answer.cache_similarity is None
        else round(answer.cache_similarity, 4),
        cost_saved_usd=str(answer.cost_saved_usd),
        escalated_from=None if answer.escalation is None else answer.escalation.model,
        degraded=answer.degraded,
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
        metrics.record_error("ask", answer_mode())
        raise HTTPException(status_code=503, detail="answering is temporarily unavailable") from exc
    metrics.record_answer(answer, "ask", answer_mode(), get_settings().cache_enabled)
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
            elif isinstance(event, EscalateEvent):
                # Routing (Phase 8b): a larger model answers next. With reset, the client
                # discards the text it has (the first model's refusal) and starts again.
                yield sse(
                    "escalate",
                    {
                        "from_model": event.from_model,
                        "to_model": event.to_model,
                        "reset": event.reset,
                    },
                )
            elif isinstance(event, DoneEvent):
                metrics.record_answer(
                    event.answer, "stream", answer_mode(), get_settings().cache_enabled
                )
                yield sse("done", to_response(event.answer).model_dump())
    except Exception:
        # Headers (200) are already sent once streaming starts, so errors travel as an event.
        # The HTTP status stays 200, so this counter is the only place the failure shows.
        log.exception("stream failed")
        metrics.record_error("stream", answer_mode())
        yield sse("error", {"detail": "answering is temporarily unavailable"})


class Disconnectable(Protocol):
    """The one thing stop_on_disconnect needs from a request (eases testing)."""

    async def is_disconnected(self) -> bool: ...


async def stop_on_disconnect(
    request: Disconnectable, events: Iterator[str], mode: str = "pipeline"
) -> AsyncIterator[str]:
    """Stop generating when the browser goes away (Stop button, closed tab).

    Without this, an abandoned answer keeps running to the end, and its output
    tokens are still paid for. The pipeline is synchronous, so each step runs in
    a worker thread; between steps we check the connection. Closing the generator
    closes the model client's HTTP stream (tested against a fake Ollama server).

    A cancelled stream is counted as outcome="cancelled", not error: the user
    changing their mind is not a fault and mustn't spend the error budget.
    """
    try:
        async for chunk in iterate_in_threadpool(events):
            if await request.is_disconnected():
                if not chunk.startswith("event: done"):  # finished answers aren't cancelled
                    log.info("client disconnected; generation stopped early")
                    metrics.record_cancelled("stream", mode)
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
        stop_on_disconnect(request, event_stream(pipeline, body.question), answer_mode()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # stop reverse proxies (nginx, some ALB setups) buffering the stream
        },
    )
