"""Shared test doubles.

`WordHashEmbeddings` is a tiny, deterministic stand-in for a real embedding
model: texts that share words get similar vectors. Enough to test that
retrieval ranks the right chunk first, with no model download and no network.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

DIMS = 64
_WORD = re.compile(r"[a-z]{3,}")


class WordHashEmbeddings(Embeddings):
    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * DIMS
        for word in _WORD.findall(text.lower()):
            bucket = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16) % DIMS
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class StreamingFakeChatModel(GenericFakeChatModel):
    """Streams word by word, then reports token usage on a final empty chunk,
    the way Ollama and Bedrock do. (The stock fake drops usage when streaming.)"""

    usage: dict[str, int] = {}

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
        if self.usage:
            usage = {**self.usage, "total_tokens": sum(self.usage.values())}
            yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage))


def fake_model(
    reply: str, input_tokens: int = 1000, output_tokens: int = 100
) -> StreamingFakeChatModel:
    return StreamingFakeChatModel(
        messages=iter([AIMessage(content=reply)]),
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )


@pytest.fixture
def embeddings() -> WordHashEmbeddings:
    return WordHashEmbeddings()


PAGES = [
    "Overview of the framework. The framework helps you understand trade-offs.",
    "Reliability means a workload performs its intended function correctly and consistently. "
    "Deploy across multiple Availability Zones and automate recovery from failure.",
    "Cost optimization means delivering business value at the lowest price point. "
    "Use budgets, tagging and right sizing to control spend.",
]


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A 3-page PDF with a table of contents: Introduction (p1), Reliability (p2), Cost (p3)."""
    path = tmp_path / "Sample Framework.pdf"
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for text in PAGES:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)  # type: ignore[no-untyped-call]
        # A footer page number, which the loader should drop
        page.insert_text((300, 820), str(page.number + 1))
    doc.set_toc(
        [[1, "Introduction", 1], [1, "Reliability pillar", 2], [1, "Cost optimization pillar", 3]]
    )
    doc.set_metadata({"title": "Sample Framework"})
    doc.save(path)  # type: ignore[no-untyped-call]
    doc.close()  # type: ignore[no-untyped-call]
    return path


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("KB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("integration test: set KB_TEST_DATABASE_URL (make test-integration)")
    return url
