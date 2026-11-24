"""Run every case: retrieval scored separately from generation, then summarised."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from kb_core.evaluation.dataset import EvalCase
from kb_core.evaluation.judge import LLMJudge
from kb_core.evaluation.metrics import (
    CitationCheck,
    analyse_floor,
    check_citations,
    contains_any,
    fact_recall,
    first_relevant_rank,
    is_refusal,
    mean,
    percentile,
)
from kb_core.models import Answer, RetrievedChunk

RetrieveFn = Callable[[str, int], list[RetrievedChunk]]  # (question, depth) -> ranked, no floor
AnswerFn = Callable[[str], Answer]


@dataclass
class CaseResult:
    id: str
    kind: str
    question: str
    tags: list[str]
    top_similarity: float | None = None
    relevant_rank: int | None = None  # within the retrieval depth; answerable cases only
    retrieved: list[str] = field(default_factory=list)  # "0.746 Reliability p.765"
    answer: str = ""
    refused: bool = False
    citations: dict[str, int] = field(default_factory=dict)
    fact_recall: float | None = None
    leaked: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: str = "0"
    ttft_ms: float | None = None
    total_ms: float = 0.0
    judge_score: int | None = None
    judge_unsupported: list[str] = field(default_factory=list)
    error: str | None = None

    def passed(self, k: int) -> bool:
        if self.error:
            return False
        if self.kind == "answerable":
            return not self.refused and self.relevant_rank is not None and self.relevant_rank <= k
        return self.refused and not self.leaked


@dataclass
class EvalRun:
    config: dict[str, Any]
    metrics: dict[str, float | None]
    floor_points: list[dict[str, float]]
    cases: list[CaseResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "metrics": self.metrics,
            "floor_points": self.floor_points,
            "cases": [asdict(c) for c in self.cases],
        }


def run_case(
    case: EvalCase,
    retrieve: RetrieveFn,
    answer_fn: AnswerFn,
    depth: int,
    judge: LLMJudge | None,
) -> CaseResult:
    result = CaseResult(case.id, case.kind, case.question, list(case.tags))
    try:
        ranked = retrieve(case.question, depth)
        # The highest cosine similarity among the retrieved chunks. Not ranked[0]: with
        # hybrid search or a reranker, the first chunk isn't necessarily the most similar,
        # and the floor analysis is about similarity.
        result.top_similarity = max((r.similarity for r in ranked), default=None)
        result.retrieved = [
            f"{r.similarity:.3f} {r.chunk.section} p.{r.chunk.page}" for r in ranked[:5]
        ]
        if case.should_answer:
            result.relevant_rank = first_relevant_rank(
                [r.chunk.text for r in ranked], case.evidence
            )

        answer = answer_fn(case.question)
        result.answer = answer.text
        result.refused = is_refusal(answer.text, answer.answered_from_context)
        check = check_citations(answer.text, len(answer.retrieved))
        result.citations = {
            "valid": check.valid,
            "out_of_range": check.out_of_range,
            "non_numeric": check.non_numeric,
        }
        result.fact_recall = fact_recall(answer.text, case.facts) if case.should_answer else None
        result.leaked = [p for p in case.must_not_contain if contains_any(answer.text, [p])]
        result.input_tokens = answer.input_tokens
        result.output_tokens = answer.output_tokens
        result.cost_usd = str(answer.cost_usd)
        result.ttft_ms = answer.time_to_first_token_ms
        result.total_ms = answer.total_ms

        if judge and case.should_answer and not result.refused:
            verdict = judge.grade(case.question, answer.retrieved, answer.text)
            result.judge_score = verdict.score
            result.judge_unsupported = list(verdict.unsupported)
    except Exception as exc:  # one broken case must not stop the run
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def summarise(
    cases: Sequence[CaseResult], k: int, floor: float
) -> tuple[dict[str, float | None], list[dict[str, float]]]:
    ok = [c for c in cases if not c.error]
    answerable = [c for c in ok if c.kind == "answerable"]
    off_topic = [c for c in ok if c.kind != "answerable"]
    injections = [c for c in ok if c.kind == "injection"]
    answered = [c for c in answerable if not c.refused]

    def share(items: Sequence[CaseResult], test: Callable[[CaseResult], bool]) -> float | None:
        return sum(1 for c in items if test(c)) / len(items) if items else None

    ranks = [c.relevant_rank for c in answerable]
    checks = [CitationCheck(**c.citations) for c in answered]
    all_markers = sum(ch.total for ch in checks)
    floor_analysis = analyse_floor(
        [c.top_similarity for c in answerable if c.top_similarity is not None],
        [c.top_similarity for c in off_topic if c.top_similarity is not None],
    )
    ttfts = [c.ttft_ms for c in ok if c.ttft_ms is not None]
    totals = [c.total_ms for c in ok]

    metrics: dict[str, float | None] = {
        # retrieval: is the evidence in what the model is shown?
        "retrieval.hit_rate_at_k": share(answerable, lambda c: (c.relevant_rank or 99) <= k),
        "retrieval.mrr": mean([1 / r if r else 0.0 for r in ranks]) if ranks else None,
        # the similarity floor
        "floor.answerable_kept": share(answerable, lambda c: (c.top_similarity or 0.0) >= floor),
        "floor.off_topic_rejected": share(off_topic, lambda c: (c.top_similarity or 0.0) < floor),
        "floor.gap": floor_analysis.gap,
        "floor.recommended": floor_analysis.recommended,
        # generation
        "answer.false_refusal_rate": share(answerable, lambda c: c.refused),
        "answer.fact_recall": mean([c.fact_recall for c in answered]),
        "answer.citation_validity": (sum(ch.valid for ch in checks) / all_markers)
        if all_markers
        else None,
        "answer.cited_share": share(answered, lambda c: c.citations.get("valid", 0) > 0),
        "answer.correct_refusal_rate": share(off_topic, lambda c: c.refused),
        "answer.injection_resisted": share(injections, lambda c: c.refused and not c.leaked),
        "answer.groundedness": mean(
            [c.judge_score / 5 if c.judge_score else None for c in answered]
        ),
        # overall
        "cases.pass_rate": share(cases, lambda c: c.passed(k)),
        "cases.errors": float(len(cases) - len(ok)),
        # cost and latency
        "cost.total_usd": float(sum(Decimal(c.cost_usd) for c in ok)),
        "cost.tokens_in": float(sum(c.input_tokens for c in ok)),
        "cost.tokens_out": float(sum(c.output_tokens for c in ok)),
        "latency.ttft_p50_ms": percentile(ttfts, 50),
        "latency.ttft_p95_ms": percentile(ttfts, 95),
        "latency.total_p95_ms": percentile(totals, 95),
    }
    points = [
        {
            "threshold": p.threshold,
            "answerable_kept": p.answerable_kept,
            "off_topic_rejected": p.off_topic_rejected,
        }
        for p in floor_analysis.points
    ]
    return metrics, points


def run_eval(
    cases: Sequence[EvalCase],
    retrieve: RetrieveFn,
    answer_fn: AnswerFn,
    config: dict[str, Any],
    k: int,
    floor: float,
    depth: int = 10,
    judge: LLMJudge | None = None,
    on_case: Callable[[CaseResult], None] | None = None,
) -> EvalRun:
    results = []
    for case in cases:
        result = run_case(case, retrieve, answer_fn, depth, judge)
        if on_case:
            on_case(result)
        results.append(result)
    metrics, points = summarise(results, k, floor)
    return EvalRun(
        config={**config, "k": k, "floor": floor, "depth": depth},
        metrics=metrics,
        floor_points=points,
        cases=results,
    )
