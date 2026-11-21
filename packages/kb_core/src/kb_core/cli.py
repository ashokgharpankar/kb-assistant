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
) -> None:
    """Load, chunk, embed and store documents."""
    s = get_settings()
    root = path or Path(s.data_dir)
    if not root.exists():
        raise typer.BadParameter(f"{root} does not exist (run `make fetch-sources` first?)")
    store = build_store(s)
    store.ensure_schema()
    typer.echo(
        f"provider={s.llm_provider} space={store.space.table_name} chunk={s.chunk_size}/{s.chunk_overlap}"
    )

    def show(r: DocumentResult) -> None:
        detail = r.error if r.status == "failed" else f"{r.chunks} chunks"
        typer.echo(f"  {r.status:<9} {r.document_id:<45} {detail}  ({r.seconds:.1f}s)")

    report = ingest_path(root, store, get_embeddings(s), s.chunk_size, s.chunk_overlap, force, show)
    approx_tokens = report.characters // 4
    typer.echo(
        f"\n{report.ingested} ingested, {report.unchanged} unchanged, {report.failed} failed; "
        f"{report.chunks} chunks, ~{approx_tokens:,} tokens embedded"
    )
    if report.failed:
        raise typer.Exit(code=1)


@app.command()
def search(
    query: str,
    k: Annotated[int, typer.Option(help="Number of results")] = 5,
) -> None:
    """Retrieval only: see what the model would be given, with similarity scores."""
    s = get_settings()
    store = build_store(s)
    vector = get_embeddings(s).embed_query(query)
    for i, r in enumerate(store.search(vector, k), start=1):
        preview = r.chunk.text[:160].replace("\n", " ")
        typer.echo(
            f"[{i}] {r.similarity:.3f}  {r.document_title} > {r.chunk.section} (p.{r.chunk.page})"
        )
        typer.echo(f"     {preview}...")


@app.command()
def ask(
    question: str,
    show_context: Annotated[bool, typer.Option(help="Print the retrieved chunks too")] = False,
) -> None:
    """Answer a question from the knowledge base, with citations."""
    s = get_settings()
    answer = build_pipeline(s).answer(question)
    typer.echo(f"\n{answer.text}\n")
    for c in answer.citations:
        typer.echo(
            f"  [{c.number}] {c.document_title} > {c.section}, p.{c.page}  (similarity {c.similarity:.2f})"
        )
    typer.echo(
        f"\nmodel={answer.model} tokens={answer.input_tokens} in / {answer.output_tokens} out "
        f"cost=${answer.cost_usd:.6f} retrieved={len(answer.retrieved)}"
    )
    if show_context:
        for i, r in enumerate(answer.retrieved, start=1):
            typer.echo(
                f"\n--- [{i}] {r.similarity:.3f} {r.chunk.section} p.{r.chunk.page}\n{r.chunk.text}"
            )


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
