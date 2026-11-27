"""A cancelled stream really stops the model call, end to end (incident 0016).

`test_ask.py` proves our generator stops when the browser leaves. This proves the
next link: the real model client (LangChain's ChatOllama over HTTP) closes its
connection, so the model server sees the disconnect and stops sending tokens.

The model server is a fake Ollama: it streams `/api/chat` the way Ollama does,
one token every few milliseconds, and records how many tokens it managed to
send before the client went away. No model, no network, runs in CI.

What this can't prove is what a real provider does once the connection closes:
Ollama, and Bedrock's ConverseStream, have to stop generating (and billing) on
their side. `KB_TEST_OLLAMA_URL` runs the same flow against a real Ollama.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_core.embeddings import Embeddings
from langchain_ollama import ChatOllama

from kb_api import main, metrics
from kb_core.models import Chunk, RetrievedChunk
from kb_core.rag import RagPipeline

HIT = RetrievedChunk(
    Chunk("f:1", "f", 1, "Deploy across multiple Availability Zones.", "Reliability", 12),
    "Reliability Pillar",
    "file:///f",
    0.81,
)
TOKENS = 400  # what a full answer would be
DELAY_S = 0.005


class FakeOllama(BaseHTTPRequestHandler):
    sent = 0
    finished = False
    client_gone = threading.Event()

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        length = int(self.headers.get("Content-Length", 0))
        json.loads(self.rfile.read(length) or b"{}")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for i in range(TOKENS):
                line = {
                    "model": "llama3.2",
                    "created_at": "2026-11-27T00:00:00Z",
                    "message": {"role": "assistant", "content": f"word{i} "},
                    "done": False,
                }
                self.wfile.write((json.dumps(line) + "\n").encode())
                self.wfile.flush()
                type(self).sent += 1
                time.sleep(DELAY_S)
            final = {
                "model": "llama3.2",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 900,
                "eval_count": TOKENS,
            }
            self.wfile.write((json.dumps(final) + "\n").encode())
            type(self).finished = True
        except (BrokenPipeError, ConnectionResetError):
            type(self).client_gone.set()  # what Ollama sees: the request was cancelled


@pytest.fixture
def ollama_url() -> Iterator[str]:
    real = os.environ.get("KB_TEST_OLLAMA_URL")
    if real:
        yield real
        return
    FakeOllama.sent, FakeOllama.finished = 0, False
    FakeOllama.client_gone.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


class LeavesAfter:
    """A browser that reads `events` stream events, then closes the tab."""

    def __init__(self, events: int) -> None:
        self.events, self.checks = events, 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self.events


def pipeline(url: str) -> RagPipeline:
    return RagPipeline(
        search=lambda v, k, m: [HIT],
        embeddings=_NoEmbeddings(),
        chat_model=ChatOllama(model="llama3.2", base_url=url, num_predict=TOKENS),
        model_id="llama3.2",
        k=4,
        min_similarity=0.4,
    )


class _NoEmbeddings(Embeddings):
    def embed_query(self, text: str) -> list[float]:
        return [1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]


def value(name: str, **labels: str) -> float:
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


def run(url: str, leave_after: int) -> list[str]:
    events = main.event_stream(pipeline(url), "How do I survive a zone failure?")

    async def consume() -> list[str]:
        return [c async for c in main.stop_on_disconnect(LeavesAfter(leave_after), events)]

    return asyncio.run(consume())


def test_closing_the_tab_closes_the_model_stream(ollama_url: str) -> None:
    before = {
        o: value("kb_answers_total", endpoint="stream", mode="pipeline", outcome=o)
        for o in ("cancelled", "error", "answered")
    }
    received = run(ollama_url, leave_after=10)  # sources + 9 tokens, then the tab closes

    assert len(received) == 10
    assert not any(c.startswith("event: done") for c in received)

    if "KB_TEST_OLLAMA_URL" not in os.environ:
        # The model server saw the client leave and stopped well short of a full answer.
        assert FakeOllama.client_gone.wait(timeout=5), "server never saw the disconnect"
        assert not FakeOllama.finished
        assert FakeOllama.sent < TOKENS / 4, f"server sent {FakeOllama.sent} of {TOKENS} tokens"

    after = {
        o: value("kb_answers_total", endpoint="stream", mode="pipeline", outcome=o) for o in before
    }
    assert after["cancelled"] == before["cancelled"] + 1
    assert after["error"] == before["error"]  # not a fault, no error budget spent
    assert after["answered"] == before["answered"]


@pytest.mark.skipif("KB_TEST_OLLAMA_URL" in os.environ, reason="fake server only")
def test_an_answer_read_to_the_end_is_answered_not_cancelled(ollama_url: str) -> None:
    before = value("kb_answers_total", endpoint="stream", mode="pipeline", outcome="cancelled")
    received = run(ollama_url, leave_after=10_000)
    assert received[-1].startswith("event: done")
    assert FakeOllama.finished and not FakeOllama.client_gone.is_set()
    assert (
        value("kb_answers_total", endpoint="stream", mode="pipeline", outcome="cancelled") == before
    )
