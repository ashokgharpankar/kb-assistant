"""`kb` command line: the fastest way to exercise the pipeline.

kb init-db                      create tables and indexes
kb ingest data/raw              load, chunk, embed and store (skips unchanged files)
kb ask "What is the Reliability pillar?"
kb search "multi-AZ"            show raw retrieval results, no model call
kb stats
kb eval                         score the pipeline against eval/dataset.jsonl
kb toc data/raw/x.pdf           show a PDF's table of contents (to pick KB_TOC_DEPTH)
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from kb_core.factory import build_answerer, build_retriever, build_store
from kb_core.ingest import DocumentResult, ingest_path
from kb_core.models import DoneEvent, RetrievedChunk, TokenEvent
from kb_core.providers import chat_model_id, embedding_space, get_chat_model, get_embeddings
from kb_core.settings import Settings, get_settings
from kb_core.tracing import NoopTracer

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
        f"provider={s.llm_provider} space={store.space.table_name} chunk={s.chunk_size}/{s.chunk_overlap} "
        f"toc_depth={s.toc_depth} headers={s.chunk_headers}"
    )

    def show(r: DocumentResult) -> None:
        detail = r.error if r.status == "failed" else f"{r.chunks} chunks"
        typer.echo(f"  {r.status:<9} {r.document_id:<45} {detail}  ({r.seconds:.1f}s)")

    report = ingest_path(
        root,
        store,
        get_embeddings(s),
        s.chunk_size,
        s.chunk_overlap,
        force,
        show,
        prune,
        toc_depth=s.toc_depth,
        chunk_headers=s.chunk_headers,
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
    retriever = build_retriever(s, store, get_embeddings(s))
    typer.echo(f"retrieval={retriever.description}\n")
    hits = retriever.rank(query, k, 0.0)
    for i, r in enumerate(hits, start=1):
        preview = r.chunk.text[:160].replace("\n", " ")
        mark = "" if r.similarity >= floor else "  [below floor: ask would drop this]"
        rerank = f" rerank={r.rerank_score:.3f}" if r.rerank_score is not None else ""
        typer.echo(
            f"[{i}] {r.similarity:.3f}{rerank}  {r.document_title} > {r.chunk.section} "
            f"(p.{r.chunk.page}){mark}"
        )
        typer.echo(f"     {preview}...")
    kept = sum(r.similarity >= floor for r in hits)
    typer.echo(f"\nfloor={floor:.2f}: {kept} of {len(hits)} would reach the model")


@app.command()
def ask(
    question: str,
    show_context: Annotated[bool, typer.Option(help="Print the retrieved chunks too")] = False,
    stream: Annotated[bool, typer.Option(help="Print the answer as it is written")] = True,
    mode: Annotated[
        str | None, typer.Option(help="pipeline or agent (default: KB_ANSWER_MODE)")
    ] = None,
    cache: Annotated[bool, typer.Option(help="Use the answer cache (KB_CACHE_ENABLED)")] = True,
) -> None:
    """Answer a question from the knowledge base, with citations."""
    s = _with_mode(get_settings(), mode)
    pipeline = build_answerer(s, cache=None if cache else False)
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
        + (
            f"cache_lookup={answer.retrieval_ms:.0f}ms "  # nothing was retrieved on a hit
            if answer.cache
            else f"retrieval={answer.retrieval_ms:.0f}ms "
        )
        + f"first_token={ttft} total={answer.total_ms:.0f}ms"
    )
    if answer.cache:
        typer.echo(
            f"from cache: {answer.cache} (similarity {answer.cache_similarity:.3f}), "
            f"saved {answer.tokens_saved} tokens / ${answer.cost_saved_usd:.6f}"
        )
    if answer.steps:
        typer.echo("\nagent steps:")
        for step in answer.steps:
            typer.echo(f"  - {step}")
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


@app.command("eval")
def evaluate(
    dataset: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Evaluation set (JSONL)")
    ] = Path("eval/dataset.jsonl"),
    k: Annotated[
        int | None,
        typer.Option(min=1, max=20, help="Chunks given to the model (default: settings)"),
    ] = None,
    min_similarity: Annotated[
        float | None, typer.Option(min=0.0, max=1.0, help="Similarity floor (default: settings)")
    ] = None,
    depth: Annotated[int, typer.Option(min=1, max=50, help="Ranks searched for evidence")] = 10,
    only: Annotated[list[str] | None, typer.Option(help="Run only these case IDs")] = None,
    judge: Annotated[bool, typer.Option(help="Also grade groundedness with an LLM judge")] = False,
    judge_model: Annotated[
        str | None, typer.Option(help="Judge model (default: the answering model)")
    ] = None,
    baseline: Annotated[Path, typer.Option(help="Compare with this earlier run")] = Path(
        "eval/baseline.json"
    ),
    gate: Annotated[Path, typer.Option(help="Minimum scores to pass")] = Path("eval/gate.toml"),
    save: Annotated[bool, typer.Option(help="Write results to eval/results/")] = True,
    update_baseline: Annotated[bool, typer.Option(help="Make this run the new baseline")] = False,
    gate_latency: Annotated[
        bool, typer.Option(help="Treat slower latency than the baseline as a regression")
    ] = False,
    mode: Annotated[
        str | None, typer.Option(help="pipeline or agent (default: KB_ANSWER_MODE)")
    ] = None,
    retrieval_only: Annotated[
        bool,
        typer.Option(
            help="Score retrieval, the floor and the input screen only: no model calls, "
            "deterministic (CI on every pull request)"
        ),
    ] = False,
) -> None:
    """Score retrieval, answers, refusals and the similarity floor on a fixed question set.

    Exits with code 1 if the gate fails or a score regressed against the baseline.
    """
    from kb_core.evaluation.dataset import load_dataset
    from kb_core.evaluation.judge import LLMJudge
    from kb_core.evaluation.report import check_gate, compare, load_gate, to_markdown
    from kb_core.evaluation.runner import CaseResult, run_eval

    if retrieval_only and (update_baseline or judge):
        raise typer.BadParameter("--retrieval-only can't update the baseline or use --judge")
    s = get_settings()
    updates: dict[str, object] = {}
    if k is not None:
        updates["retrieval_k"] = k
    if min_similarity is not None:
        updates["min_similarity"] = min_similarity
    s = _with_mode(s.model_copy(update=updates), mode)

    cases = load_dataset(dataset)
    if only:
        cases = [c for c in cases if c.id in set(only)]
        if not cases:
            raise typer.BadParameter("no case matches --only")

    store = build_store(s)
    # Evaluation runs are not user traffic: keep them out of the traces.
    # cache=False: the evaluation measures the model, not answers remembered from a
    # previous run (Phase 8a).
    answerer = (
        None if retrieval_only else build_answerer(s, store=store, tracer=NoopTracer(), cache=False)
    )
    # Scored with the same strategy the pipeline uses (hybrid, reranker), but deeper
    # and without the floor, so near misses show up.
    retriever = build_retriever(s, store, get_embeddings(s))

    def retrieve(question: str, n: int) -> list[RetrievedChunk]:
        return retriever.rank(question, n, 0.0)

    llm_judge = None
    if judge:
        judge_settings = s
        if judge_model:
            field = "ollama_chat_model" if s.llm_provider == "ollama" else "bedrock_chat_model"
            judge_settings = s.model_copy(update={field: judge_model})
        llm_judge = LLMJudge(get_chat_model(judge_settings), chat_model_id(judge_settings))

    def progress(result: CaseResult) -> None:
        if retrieval_only and result.kind != "answerable":
            mark = "-   "  # nothing to judge without an answer
        elif retrieval_only:
            found = result.relevant_rank is not None and result.relevant_rank <= s.retrieval_k
            mark = "ok  " if found and not result.error else "FAIL"
        else:
            mark = "ok  " if result.passed(s.retrieval_k) else "FAIL"
        top = f"{result.top_similarity:.3f}" if result.top_similarity is not None else "  -  "
        again = f"  ({result.searches} searches)" if result.searches > 1 else ""
        typer.echo(f"  {mark} {top}  {result.id}{again}")

    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    config = {
        "created": created,
        "model": chat_model_id(s),
        "embedding_space": embedding_space(s).table_name,
        "retrieval": retriever.description,
        "answer_mode": s.answer_mode,
        "guardrails": s.guardrails,
        "max_searches": s.agent_max_searches if s.answer_mode == "agent" else 1,
        "toc_depth": s.toc_depth,
        "chunk_headers": s.chunk_headers,
        "candidates": s.retrieval_candidates,
        "dataset": str(dataset),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest()[:12],
        "judge": llm_judge.model_id if llm_judge else None,
        "retrieval_only": retrieval_only,
    }
    typer.echo(
        f"Evaluating {len(cases)} cases with {config['model']} (k={s.retrieval_k}, "
        f"floor={s.min_similarity}, retrieval={retriever.description}, answer={s.answer_mode}, "
        f"guardrails={'on' if s.guardrails else 'off'}"
        f"{', retrieval only: no model calls' if retrieval_only else ''})\n"
    )
    run = run_eval(
        cases,
        retrieve,
        answerer.answer if answerer else None,
        config,
        s.retrieval_k,
        s.min_similarity,
        depth,
        llm_judge,
        on_case=progress,
        projected_model=s.projected_price_model,
    )
    store.close()

    deltas = None
    if baseline.exists():
        previous = json.loads(baseline.read_text(encoding="utf-8"))
        if previous.get("config", {}).get("dataset_sha256") != config["dataset_sha256"]:
            typer.echo("\nNote: the baseline used a different version of the dataset.")
        deltas = compare(run.metrics, previous["metrics"], gate_latency=gate_latency)
    gate_failures = (
        check_gate(run.metrics, load_gate(gate), skip_unmeasured=retrieval_only)
        if gate.exists()
        else None
    )

    report = to_markdown(run, deltas, gate_failures)
    typer.echo("\n" + report)

    if save:
        out = Path("eval/results")
        out.mkdir(parents=True, exist_ok=True)
        stem = f"{created.replace(':', '').replace('-', '')}-{config['model']}".replace("/", "_")
        if retrieval_only:
            stem += "-retrieval"
        (out / f"{stem}.json").write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
        (out / f"{stem}.md").write_text(report, encoding="utf-8")
        typer.echo(f"Saved eval/results/{stem}.json and .md")
    if update_baseline:
        baseline.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
        typer.echo(f"Baseline updated: {baseline}")

    # A run that becomes the new baseline is the reference from now on: report its changes,
    # but only the absolute gate can fail it (otherwise a dataset change could never be
    # re-baselined without a red exit code).
    regressions = [] if update_baseline else [d.name for d in deltas or [] if d.regressed]
    if gate_failures or regressions:
        if regressions:
            typer.echo(f"Regressed against the baseline: {', '.join(regressions)}")
        raise typer.Exit(code=1)


@app.command("cache-clear")
def cache_clear() -> None:
    """Delete every cached answer for the current embedding space."""
    from kb_core.cache import PgAnswerCache

    s = get_settings()
    store = build_store(s)
    cache = PgAnswerCache(store, s.cache_semantic_threshold, s.cache_ttl_hours)
    cache.ensure_schema()
    typer.echo(f"removed {cache.clear()} cached answers from {cache.table}")
    store.close()


@app.command("cache-check")
def cache_check(
    pairs_file: Annotated[Path, typer.Option("--pairs")] = Path("eval/cache_pairs.jsonl"),
    threshold: Annotated[
        float | None, typer.Option(help="Threshold to test (default: KB_CACHE_SEMANTIC_THRESHOLD)")
    ] = None,
) -> None:
    """Score labelled question pairs and recommend a semantic-cache threshold."""
    from kb_core.evaluation.cache_check import analyse, load_pairs, score_pairs, wrong_hits

    s = get_settings()
    chosen = threshold if threshold is not None else s.cache_semantic_threshold
    scored = score_pairs(load_pairs(pairs_file), get_embeddings(s).embed_documents)
    typer.echo(f"embeddings: {embedding_space(s)}\n")
    for sp in sorted(scored, key=lambda x: -x.similarity):
        label = "same" if sp.pair.same else "DIFF"
        typer.echo(f"  {sp.similarity:.3f}  {label}  {sp.pair.a!r} ~ {sp.pair.b!r}")
    analysis = analyse(scored)
    typer.echo(
        f"\nlowest same-meaning {analysis.lowest_answerable:.3f}, "
        f"highest different-meaning {analysis.highest_off_topic:.3f}, "
        f"gap {analysis.gap:+.3f}"
    )
    typer.echo(
        f"recommended threshold: {analysis.recommended}"
        if analysis.recommended is not None
        else "no clean separation: keep the exact cache only, or raise the threshold above "
        "the highest different-meaning pair"
    )
    if chosen is None:
        typer.echo("semantic cache is off (KB_CACHE_SEMANTIC_THRESHOLD unset)")
        return
    same = [sp for sp in scored if sp.pair.same]
    hits = sum(sp.similarity >= chosen for sp in same)
    bad = wrong_hits(scored, chosen)
    typer.echo(
        f"\nat {chosen:.2f}: {hits}/{len(same)} same-meaning pairs hit, {len(bad)} wrong hits"
    )
    for sp in bad:
        typer.echo(f"  WRONG {sp.similarity:.3f} {sp.pair.a!r} ~ {sp.pair.b!r}")
    if bad:
        raise typer.Exit(code=1)


@app.command()
def toc(
    pdf: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="A PDF file")],
    depth: Annotated[int, typer.Option(min=1, max=8, help="Deepest level to list")] = 4,
    match: Annotated[str | None, typer.Option(help="Only entries whose path contains this")] = None,
) -> None:
    """A PDF's table of contents as heading paths, with how many entries each level has."""
    from collections import Counter

    import pymupdf

    with pymupdf.open(pdf) as doc:  # type: ignore[no-untyped-call]
        entries = doc.get_toc()
    counts = Counter(level for level, _, _ in entries)
    typer.echo("entries per level: " + ", ".join(f"{k}: {counts[k]}" for k in sorted(counts)))
    stack: list[str] = []
    for level, title, page in entries:
        del stack[level - 1 :]
        stack.append(title.strip())
        path = " > ".join(stack)
        if level <= depth and (match is None or match.lower() in path.lower()):
            typer.echo(f"  L{level} p.{page:<5} {path}")


def _with_mode(settings: Settings, mode: str | None) -> Settings:
    if mode is None:
        return settings
    if mode not in ("pipeline", "agent"):
        raise typer.BadParameter("mode must be 'pipeline' or 'agent'")
    return settings.model_copy(update={"answer_mode": mode})
