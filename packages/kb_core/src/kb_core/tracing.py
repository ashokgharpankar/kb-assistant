"""LLM observability: one Langfuse trace per question.

Trace shape (what you'll see in the Langfuse UI):

    rag.answer            (chain)       question -> answer, cost, tokens, TTFT
    ├── retrieve          (retriever)   question -> chunk ids, sections, pages, similarity
    └── generate          (generation)  prompt -> answer, model, token usage, cost

Tracing is optional. With no Langfuse keys configured, a no-op tracer is used
and nothing leaves the machine. The pipeline code is identical either way.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Literal, Protocol

from kb_core.settings import Settings

ObservationType = Literal["span", "chain", "retriever", "generation", "agent"]


class Observation(Protocol):
    def update(self, **fields: Any) -> Any: ...


class Tracer(Protocol):
    def observe(
        self, name: str, as_type: ObservationType = "span", **fields: Any
    ) -> AbstractContextManager[Observation]: ...

    def flush(self) -> None: ...


class _NoopObservation:
    def update(self, **fields: Any) -> None:
        return None


class NoopTracer:
    """Used when tracing is off. Costs nothing, records nothing."""

    @contextmanager
    def observe(
        self, name: str, as_type: ObservationType = "span", **fields: Any
    ) -> Iterator[Observation]:
        yield _NoopObservation()

    def flush(self) -> None:
        return None


class LangfuseTracer:
    def __init__(self, public_key: str, secret_key: str, host: str, environment: str) -> None:
        from langfuse import Langfuse

        self.client = Langfuse(
            public_key=public_key, secret_key=secret_key, host=host, environment=environment
        )

    def observe(
        self, name: str, as_type: ObservationType = "span", **fields: Any
    ) -> AbstractContextManager[Observation]:
        # Nested calls become child observations of the current one automatically.
        cm: AbstractContextManager[Observation] = self.client.start_as_current_observation(
            name=name, as_type=as_type, **fields
        )
        return cm

    def flush(self) -> None:
        # Short-lived processes (the CLI) must flush, or buffered traces are lost on exit.
        self.client.flush()


def build_tracer(settings: Settings) -> Tracer:
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        return LangfuseTracer(
            settings.langfuse_public_key,
            settings.langfuse_secret_key,
            settings.langfuse_host,
            settings.env,
        )
    return NoopTracer()
