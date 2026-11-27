"""Wrap any answerer (pipeline or agent) with the Phase 7b guardrails.

Before: screen the question; a blocked question gets "not found" with no retrieval and
no model call. After: re-check whether the answer is really a refusal, and score how well
it's grounded in the sources it cites. The wrapped answerer doesn't change, so the
pipeline and the agent get identical checks.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import TYPE_CHECKING

from kb_core.guardrails import check_grounding, is_refusal, screen_question
from kb_core.models import Answer, DoneEvent, SourcesEvent, StreamEvent
from kb_core.rag import NOT_FOUND
from kb_core.tracing import Tracer

if TYPE_CHECKING:
    from kb_core.factory import Answerer


class GuardedAnswerer:
    def __init__(self, inner: Answerer) -> None:
        self.inner = inner
        self.tracer: Tracer = inner.tracer

    def answer(self, question: str) -> Answer:
        for event in self.stream(question):
            if isinstance(event, DoneEvent):
                return event.answer
        raise RuntimeError("stream ended without a final answer")  # pragma: no cover

    def stream(self, question: str) -> Iterator[StreamEvent]:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")

        screen = screen_question(question)
        if screen.blocked:
            with self.tracer.observe("guardrail.input", input={"question": question}) as span:
                span.update(output={"blocked": True, "reason": screen.reason})
            yield SourcesEvent([])
            yield DoneEvent(
                Answer(
                    question=question,
                    text=NOT_FOUND,
                    answered_from_context=False,
                    searches=0,
                    blocked_by=screen.reason,
                )
            )
            return

        for event in self.inner.stream(question):
            if isinstance(event, DoneEvent):
                yield DoneEvent(self._check(event.answer))
            else:
                yield event

    def _check(self, answer: Answer) -> Answer:
        sources = len(answer.retrieved)
        answered = answer.answered_from_context and not is_refusal(answer.text, sources)
        grounding = check_grounding(answer.text, answer.retrieved) if answered and sources else None
        if grounding is not None:
            with self.tracer.observe("guardrail.grounding") as span:
                span.update(
                    output={
                        "score": grounding.score,
                        "unsupported": grounding.unsupported,
                        "unknown_terms": grounding.unknown_terms,
                    }
                )
        return replace(answer, answered_from_context=answered, grounding=grounding)
