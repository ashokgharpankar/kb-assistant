"""CLI tests with fakes: no database, no model. Checks wiring and output format."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kb_core import cli
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
from kb_core.store import StoreStats
from kb_core.tracing import NoopTracer

from .conftest import WordHashEmbeddings

runner = CliRunner()

HIT = RetrievedChunk(
    chunk=Chunk(
        "fw:00001", "fw", 1, "Deploy across multiple Availability Zones.", "Reliability", 42
    ),
    document_title="Framework",
    uri="file:///fw.pdf",
    similarity=0.812,
)


class FakeStore:
    class space:  # noqa: N801  (mimics the EmbeddingSpace attribute)
        table_name = "kb_chunks_test_64"
        dimensions = 64

    def ensure_schema(self) -> None:
        pass

    def search(
        self, vector: list[float], k: int, min_similarity: float = 0.0
    ) -> list[RetrievedChunk]:
        return [HIT]

    def stats(self) -> StoreStats:
        return StoreStats(documents=3, chunks=120, table="kb_chunks_test_64")

    def delete_document(self, document_id: str) -> bool:
        return document_id == "fw"


class FakePipeline:
    tracer = NoopTracer()

    def stream(self, question: str) -> Iterator[StreamEvent]:
        yield SourcesEvent([HIT])
        for piece in ["Use multiple ", "AZs [1]."]:
            yield TokenEvent(piece)
        yield DoneEvent(self.answer(question))

    def answer(self, question: str) -> Answer:
        return Answer(
            question=question,
            text="Use multiple AZs [1].",
            citations=[Citation(1, "Framework", "Reliability", 42, "file:///fw.pdf", 0.812)],
            model="amazon.nova-micro-v1:0",
            input_tokens=1000,
            output_tokens=100,
            cost_usd=Decimal("0.000049"),
            retrieved=[HIT],
            retrieval_ms=12.0,
            time_to_first_token_ms=340.0,
            total_ms=900.0,
        )


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "build_store", lambda s: FakeStore())
    monkeypatch.setattr(cli, "build_pipeline", lambda s: FakePipeline())
    monkeypatch.setattr(cli, "get_embeddings", lambda s: WordHashEmbeddings())


def test_init_db_reports_the_table() -> None:
    result = runner.invoke(cli.app, ["init-db"])
    assert result.exit_code == 0
    assert "kb_chunks_test_64" in result.output


def test_search_prints_score_section_and_page() -> None:
    result = runner.invoke(cli.app, ["search", "availability zones"])
    assert result.exit_code == 0
    assert "0.812" in result.output and "Reliability (p.42)" in result.output
    assert "below floor" not in result.output
    assert "1 of 1 would reach the model" in result.output


def test_search_marks_results_below_the_floor() -> None:
    result = runner.invoke(cli.app, ["search", "pizza", "--min-similarity", "0.9"])
    assert "[below floor: ask would drop this]" in result.output
    assert "floor=0.90: 0 of 1 would reach the model" in result.output


def test_remove_reports_success_and_unknown_ids() -> None:
    assert runner.invoke(cli.app, ["remove", "fw"]).exit_code == 0
    missing = runner.invoke(cli.app, ["remove", "nope"])
    assert missing.exit_code == 1 and "no document 'nope'" in missing.output


def test_ask_prints_answer_citations_and_cost() -> None:
    result = runner.invoke(cli.app, ["ask", "How do I stay available?", "--show-context"])
    assert result.exit_code == 0
    assert "Use multiple AZs [1]." in result.output
    assert "[1] Framework > Reliability, p.42" in result.output
    assert "cost=$0.000049" in result.output
    assert "first_token=340ms" in result.output
    assert "Deploy across multiple Availability Zones." in result.output  # --show-context


def test_stats() -> None:
    result = runner.invoke(cli.app, ["stats"])
    assert result.exit_code == 0
    assert "documents=3 chunks=120" in result.output


def test_ingest_missing_path_is_a_clear_error(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", str(tmp_path / "nope")])
    assert result.exit_code == 2  # usage error, not a crash
    assert "Invalid value" in result.output


def test_ask_without_streaming_prints_the_whole_answer_once() -> None:
    result = runner.invoke(cli.app, ["ask", "How do I stay available?", "--no-stream"])
    assert result.exit_code == 0
    assert result.output.count("Use multiple AZs [1].") == 1


def test_prune_with_a_single_file_is_refused(tmp_path: Path) -> None:
    one = tmp_path / "one.md"
    one.write_text("# One")
    result = runner.invoke(cli.app, ["ingest", str(one), "--prune"])
    assert result.exit_code == 2
