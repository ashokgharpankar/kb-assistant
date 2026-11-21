"""`kb` command line: the fastest way to exercise the pipeline.

kb init-db                      create tables and indexes
kb ingest data/raw              load, chunk, embed and store (skips unchanged files)
kb ask "What is the Reliability pillar?"
kb search "multi-AZ"            show raw retrieval results, no model call
kb stats
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from kb_core.factory import build_pipeline, build_store
from kb_core.ingest import DocumentResult, ingest_path
from kb_core.models import DoneEvent, TokenEvent
from kb_core.providers import embedding_space, get_embeddings
from kb_core.settings import get_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="KB Assistant command line.")


@app.command("init-db")
def init_db() -> None:
    """Create tables and indexes for the current embedding space."""
    store = build_store(get_settings())
    store.ensure_schema()
    typer.echo(f"ready: {store.space.table_name}")


@app.command()
def ingest(
    path: Annotated[
        Path | None, typer.Argument(help="File or folder. Default: KB_DATA_DIR")
    ] = None,
    force: Annotated[bool, typer.Option(help="Re-embed even if unchanged")] = False,
    prune: Annotated[
        bool, typer.Option(help="Delete stored documents whose file is no longer in the folder")
    ] = False,
) -> None:
    """Load, chunk, embed and store documents."""
    s = get_settings()
    root = path or Path(s.data_dir)
    if not root.exists():
        raise typer.BadParameter(f"{root} does not exist (run `make fetch-sources` first?)")
    if prune and not root.is_dir():
        raise typer.BadParameter("--prune needs a folder, not a single file")
    store = build_store(s)
    store.ensure_schema()
    typer.echo(
        f"provider={s.llm_provider} space={store.space.table_name} chunk={s.chunk_size}/{s.chunk_overlap}"
    )

    def show(r: DocumentResult) -> None:
        detail = r.error if r.status == "failed" else f"{r.chunks} chunks"
        typer.echo(f"  {r.status:<9} {r.document_id:<45} {detail}  ({r.seconds:.1f}s)")

    report = ingest_path(
        root, store, get_embeddings(s), s.chunk_size, s.chunk_overlap, force, show, prune
    )
    for document_id in report.removed:
        typer.echo(f"  removed   {document_id}")
    approx_tokens = report.characters // 4
    typer.echo(
        f"\n{report.ingested} ingested, {report.unchanged} unchanged, {report.failed} failed, "
        f"{len(report.removed)} removed; {report.chunks} chunks, ~{approx_tokens:,} tokens embedded"
    )
    if report.failed:
        raise typer.Exit(code=1)


@app.command()
def search(
    query: str,
    k: Annotated[int, typer.Option(help="Number of results")] = 5,
    min_similarity: Annotated[
        float | None, typer.Option(help="Floor to test. Default: KB_MIN_SIMILARITY")
    ] = None,
) -> None:
    """Retrieval only, no model call: the raw top-k with scores, marking what `ask` would drop."""
    s = get_settings()
    floor = s.min_similarity if min_similarity is None else min_similarity
    store = build_store(s)
    vector = get_embeddings(s).embed_query(query)
    hits = store.search(vector, k)
    for i, r in enumerate(hits, start=1):
        preview = r.chunk.text[:160].replace("\n", " ")
        mark = "" if r.similarity >= floor else "  [below floor: ask would drop this]"
        typer.echo(
            f"[{i}] {r.similarity:.3f}  {r.document_title} > {r.chunk.section} (p.{r.chunk.page}){mark}"
        )
        typer.echo(f"     {preview}...")
    kept = sum(r.similarity >= floor for r in hits)
    typer.echo(f"\nfloor={floor:.2f}: {kept} of {len(hits)} would reach the model")


@app.command()
def ask(
    question: str,
    show_context: Annotated[bool, typer.Option(help="Print the retrieved chunks too")] = False,
    stream: Annotated[bool, typer.Option(help="Print the answer as it is written")] = True,
) -> None:
    """Answer a question from the knowledge base, with citations."""
    s = get_settings()
    pipeline = build_pipeline(s)
    answer = None
    printed = False
    typer.echo("")
    try:
        for event in pipeline.stream(question):
            if isinstance(event, TokenEvent) and stream:
                typer.echo(event.text, nl=False)
                printed = True
            elif isinstance(event, DoneEvent):
                answer = event.answer
    finally:
        pipeline.tracer.flush()  # a CLI exits immediately: send buffered traces first
    if answer is None:  # pragma: no cover
        raise typer.Exit(code=1)

    # Streamed text is already on screen; otherwise (no stream, or "not found") print it now.
    typer.echo("\n" if printed else f"{answer.text}\n")
    for c in answer.citations:
        typer.echo(
            f"  [{c.number}] {c.document_title} > {c.section}, p.{c.page}  (similarity {c.similarity:.2f})"
        )
    ttft = f"{answer.time_to_first_token_ms:.0f}ms" if answer.time_to_first_token_ms else "-"
    typer.echo(
        f"\nmodel={answer.model} tokens={answer.input_tokens} in / {answer.output_tokens} out "
        f"cost=${answer.cost_usd:.6f} retrieved={len(answer.retrieved)} "
        f"retrieval={answer.retrieval_ms:.0f}ms first_token={ttft} total={answer.total_ms:.0f}ms"
    )
    if show_context:
        for i, r in enumerate(answer.retrieved, start=1):
            typer.echo(
                f"\n--- [{i}] {r.similarity:.3f} {r.chunk.section} p.{r.chunk.page}\n{r.chunk.text}"
            )


@app.command()
def remove(document_id: str) -> None:
    """Delete a document and all its chunks (every embedding space)."""
    store = build_store(get_settings())
    if store.delete_document(document_id):
        typer.echo(f"removed {document_id}")
    else:
        typer.echo(f"no document {document_id!r}; see `kb stats` or the kb_documents table")
        raise typer.Exit(code=1)


@app.command()
def stats() -> None:
    """Documents and chunks stored for the current embedding space."""
    s = get_settings()
    st = build_store(s).stats()
    space = embedding_space(s)
    typer.echo(
        f"space={st.table} ({space.dimensions} dims) documents={st.documents} chunks={st.chunks}"
    )


if __name__ == "__main__":
    app()
