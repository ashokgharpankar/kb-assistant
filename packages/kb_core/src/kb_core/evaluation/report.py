"""Turn a run into a readable report, compare it with a baseline, apply the gate."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kb_core.evaluation.runner import EvalRun

Metrics = Mapping[str, float | None]

# Lower is better for these; higher is better for everything else that is gated or compared.
_LOWER_IS_BETTER_PREFIXES = ("cost.", "latency.")
_LOWER_IS_BETTER = {
    "answer.false_refusal_rate",
    "cases.errors",
    "answer.unknown_terms_share",
    "guardrail.answerable_blocked",
}
# Describe the data rather than its quality: shown, never treated as regressions.
_INFORMATIONAL = {"floor.recommended"}


def lower_is_better(name: str) -> bool:
    return name in _LOWER_IS_BETTER or name.startswith(_LOWER_IS_BETTER_PREFIXES)


@dataclass(frozen=True)
class Delta:
    name: str
    baseline: float | None
    current: float | None
    regressed: bool

    @property
    def change(self) -> float | None:
        if self.baseline is None or self.current is None:
            return None
        return self.current - self.baseline


def compare(
    current: Metrics,
    baseline: Metrics,
    tolerance: float = 0.05,
    cost_latency_tolerance: float = 0.25,
    gate_latency: bool = False,
) -> list[Delta]:
    """Quality scores may drop by `tolerance` (absolute) before it counts as a regression;
    cost and latency may grow by `cost_latency_tolerance` (relative), because they're noisy.

    Latency is reported but not treated as a regression unless `gate_latency`: on a
    laptop with a local model, timings move by 50% between identical runs (Phase 4).
    Gate it where timings are stable (CI against a hosted model, Phase 7).
    """
    deltas = []
    for name in sorted(set(current) | set(baseline)):
        base, cur = baseline.get(name), current.get(name)
        regressed = False
        skip = name in _INFORMATIONAL or (name.startswith("latency.") and not gate_latency)
        if base is not None and cur is not None and not skip:
            if name.startswith(_LOWER_IS_BETTER_PREFIXES):
                regressed = cur > base * (1 + cost_latency_tolerance) and cur - base > 1e-9
            elif lower_is_better(name):
                regressed = cur - base > tolerance
            else:
                regressed = base - cur > tolerance
        deltas.append(Delta(name, base, cur, regressed))
    return deltas


def load_gate(path: Path) -> dict[str, dict[str, float]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {"min": dict(data.get("min", {})), "max": dict(data.get("max", {}))}


def check_gate(
    metrics: Metrics,
    gate: Mapping[str, Mapping[str, float]],
    skip_unmeasured: bool = False,
) -> list[str]:
    """Each failure as a sentence. A gated metric that wasn't measured also fails, unless
    `skip_unmeasured` (a retrieval-only run can't measure answer metrics)."""
    failures = []
    for name, minimum in gate.get("min", {}).items():
        value = metrics.get(name)
        if value is None and skip_unmeasured:
            continue
        if value is None:
            failures.append(f"{name}: not measured (gate needs >= {minimum})")
        elif value < minimum:
            failures.append(f"{name} = {value:.3f}, below the minimum {minimum}")
    for name, maximum in gate.get("max", {}).items():
        value = metrics.get(name)
        if value is None and skip_unmeasured:
            continue
        if value is None:
            failures.append(f"{name}: not measured (gate needs <= {maximum})")
        elif value > maximum:
            failures.append(f"{name} = {value:.3f}, above the maximum {maximum}")
    return failures


def fmt(name: str, value: float | None) -> str:
    if value is None:
        return "–"
    if name.startswith("latency."):
        return f"{value:,.0f} ms"
    if name == "cost.total_usd":
        return f"${value:.6f}"
    if name.startswith("cost.tokens") or name == "cases.errors":
        return f"{value:,.0f}"
    if name == "cost.searches_per_question":
        return f"{value:.2f}"
    if name in ("floor.gap", "floor.recommended"):
        return f"{value:.3f}"
    return f"{value:.0%}"


DESCRIPTIONS = {
    "retrieval.hit_rate_at_k": "answerable questions with evidence in the top k",
    "retrieval.mrr": "how high the first relevant chunk ranks (1 = always first)",
    "floor.answerable_kept": "answerable questions that clear the floor",
    "floor.off_topic_rejected": "off-topic and injection questions the floor blocks",
    "floor.gap": "lowest answerable top score minus highest off-topic top score",
    "floor.recommended": "middle of that gap (only when the groups separate)",
    "answer.false_refusal_rate": "answerable questions answered 'not found'",
    "answer.fact_recall": "expected facts the answers mention",
    "answer.citation_validity": "citation markers that point to a real source",
    "answer.cited_share": "answers with at least one valid citation",
    "answer.correct_refusal_rate": "off-topic and injection questions refused",
    "answer.injection_resisted": "injection attempts refused without leaking",
    "answer.grounding_score": "answered claims backed by the sources they cite (lexical check)",
    "answer.unknown_terms_share": "answers naming a term no retrieved source contains",
    "guardrail.injections_blocked": "injection attempts stopped by the input screen",
    "guardrail.answerable_blocked": "real questions wrongly stopped by the input screen",
    "answer.groundedness": "judge score / 5 (only with --judge)",
    "cases.pass_rate": "cases that passed their kind's check",
    "cases.errors": "cases that crashed",
    "cost.total_usd": "model cost for the whole run",
    "cost.tokens_in": "input tokens",
    "cost.tokens_out": "output tokens",
    "cost.searches_per_question": "searches per question (1 for the pipeline; the agent may search again)",
    "latency.ttft_p50_ms": "time to first token, median",
    "latency.ttft_p95_ms": "time to first token, 95th percentile",
    "latency.total_p95_ms": "total answer time, 95th percentile",
}


def to_markdown(
    run: EvalRun,
    deltas: list[Delta] | None = None,
    gate_failures: list[str] | None = None,
) -> str:
    c = run.config
    k = int(c["k"])
    lines = [
        f"# Evaluation run {c.get('created', '')}",
        "",
        f"Model `{c.get('model')}` · embeddings `{c.get('embedding_space')}` · "
        f"retrieval `{c.get('retrieval', 'vector')}` · answer `{c.get('answer_mode', 'pipeline')}` · toc_depth={c.get('toc_depth', '–')} · "
        f"k={k} · floor={c['floor']} · {len(run.cases)} cases ({c.get('dataset')})",
        "",
    ]
    by_name = {d.name: d for d in deltas or []}
    header = "| Metric | Value | What it measures |"
    rule = "|---|---|---|"
    if deltas is not None:
        header = "| Metric | Value | Baseline | Change | What it measures |"
        rule = "|---|---|---|---|---|"
    lines += [header, rule]
    for name, value in run.metrics.items():
        row = f"| `{name}` | {fmt(name, value)} |"
        if deltas is not None:
            d = by_name.get(name)
            base = fmt(name, d.baseline) if d else "–"
            change = "–"
            if d and d.change is not None:
                change = f"{d.change:+.3f}" + (" ⚠️ regression" if d.regressed else "")
            row += f" {base} | {change} |"
        lines.append(f"{row} {DESCRIPTIONS.get(name, '')} |")

    if gate_failures is not None:
        lines += ["", "## Gate", ""]
        lines += (
            [f"- ❌ {f}" for f in gate_failures]
            if gate_failures
            else ["✅ All gate checks passed."]
        )

    lines += [
        "",
        "## Similarity floor",
        "",
        "| Floor | Answerable kept | Off-topic rejected |",
        "|---|---|---|",
    ]
    for p in run.floor_points:
        if 0.40 <= p["threshold"] <= 0.80:
            marker = " ← current" if abs(p["threshold"] - float(c["floor"])) < 0.005 else ""
            lines.append(
                f"| {p['threshold']:.2f}{marker} | {p['answerable_kept']:.0%} | "
                f"{p['off_topic_rejected']:.0%} |"
            )

    if c.get("retrieval_only"):
        # No answers: only retrieval can fail. Off-topic cases have nothing to judge.
        missed = [
            r
            for r in run.cases
            if r.error or (r.kind == "answerable" and (r.relevant_rank or k + 1) > k)
        ]
        lines += ["", f"## Retrieval misses ({len(missed)})", ""]
        for r in missed:
            why = r.error or f"evidence not in top {k} (rank {r.relevant_rank})"
            lines.append(f"- **{r.id}**: {why}. _{r.question}_")
        return "\n".join(lines) + "\n"

    failed = [r for r in run.cases if not r.passed(k)]
    lines += ["", f"## Cases that did not pass ({len(failed)})", ""]
    for r in failed:
        why = r.error or (
            "refused"
            if r.kind == "answerable" and r.refused
            else f"evidence not in top {k} (rank {r.relevant_rank})"
            if r.kind == "answerable"
            else f"leaked {r.leaked}"
            if r.leaked
            else f"named terms no source contains: {r.unknown_terms}"
            if r.kind == "near_domain"
            else "answered instead of refusing"
        )
        top = f"{r.top_similarity:.3f}" if r.top_similarity is not None else "–"
        lines.append(f"- **{r.id}** ({r.kind}, top {top}): {why}. _{r.question}_")
        if r.searches > 1:
            lines += [f"  - {step}" for step in r.steps]

    retried = [r for r in run.cases if r.searches > 1 and r.passed(k)]
    if retried:
        lines += ["", f"## Passed after searching again ({len(retried)})", ""]
        for r in retried:
            lines.append(f"- **{r.id}** ({r.searches} searches)")
            lines += [f"  - {step}" for step in r.steps]

    bad_citations = [
        r for r in run.cases if r.citations.get("non_numeric") or r.citations.get("out_of_range")
    ]
    if bad_citations:
        lines += ["", f"## Answers with unusable citations ({len(bad_citations)})", ""]
        for r in bad_citations:
            lines.append(
                f"- **{r.id}**: {r.citations.get('out_of_range', 0)} out of range, "
                f"{r.citations.get('non_numeric', 0)} non-numeric"
            )
    return "\n".join(lines) + "\n"
