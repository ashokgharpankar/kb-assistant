"""API entry point.

Phase 1 adds POST /ask. Streaming (Server-Sent Events) arrives in Phase 2.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from kb_core import __version__
from kb_core.factory import build_pipeline
from kb_core.rag import RagPipeline
from kb_core.settings import get_settings

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


@lru_cache
def get_pipeline() -> RagPipeline:
    return build_pipeline(get_settings())


@app.get("/health")
def health() -> Health:
    s = get_settings()
    return Health(status="ok", version=__version__, env=s.env, llm_provider=s.llm_provider)


@app.post("/ask")
def ask(request: AskRequest) -> AskResponse:
    try:
        answer = get_pipeline().answer(request.question)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # log the detail, return something generic
        raise HTTPException(status_code=503, detail="answering is temporarily unavailable") from exc
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
    )
