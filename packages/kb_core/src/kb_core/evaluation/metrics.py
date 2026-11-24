"""Scoring functions. All deterministic: same inputs, same scores, no model calls."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from kb_core.rag import NOT_FOUND

_SPACE = re.compile(r"\s+")
_DASHES = re.compile(r"[‐-―−]")  # hyphens and dashes of every width
_NUMERIC_CITE = re.compile(r"\[(\d+)\]")
# Any other [..] that looks like a citation, e.g. [REL11-BP01] or [Source 2]
_OTHER_BRACKET = re.compile(r"\[(?!\d+\])([A-Za-z][^\[\]\n]{0,40})\]")


def normalize(text: str) -> str:
    """Lower-case, NFKC (ligatures -> letters), one kind of dash, single spaces."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _DASHES.sub("-", text).replace("’", "'")
    return _SPACE.sub(" ", text).strip()


def contains_any(text: str, phrases: Sequence[str]) -> bool:
    haystack = normalize(text)
    return any(normalize(p) in haystack for p in phrases)


def first_relevant_rank(chunk_texts: Sequence[str], evidence: Sequence[str]) -> int | None:
    """1-based rank of the first chunk containing any evidence phrase, or None."""
    for rank, text in enumerate(chunk_texts, start=1):
        if contains_any(text, evidence):
            return rank
    return None


@dataclass(frozen=True)
class CitationCheck:
    valid: int  # [n] where n is one of the sources the model was given
    out_of_range: int  # [n] with no such source
    non_numeric: int  # [REL11-BP01] and the like: looks like a citation, can't be checked

    @property
    def total(self) -> int:
        return self.valid + self.out_of_range + self.non_numeric

    @property
    def validity(self) -> float | None:
        return self.valid / self.total if self.total else None


def check_citations(answer: str, source_count: int) -> CitationCheck:
    numbers = [int(n) for n in _NUMERIC_CITE.findall(answer)]
    valid = sum(1 for n in numbers if 1 <= n <= source_count)
    return CitationCheck(
        valid=valid,
        out_of_range=len(numbers) - valid,
        non_numeric=len(_OTHER_BRACKET.findall(answer)),
    )


def fact_recall(answer: str, facts: Sequence[Sequence[str]]) -> float | None:
    """Share of expected facts the answer mentions (any phrasing). None if no facts."""
    if not facts:
        return None
    return sum(1 for alternatives in facts if contains_any(answer, alternatives)) / len(facts)


def is_refusal(answer_text: str, answered_from_context: bool) -> bool:
    return not answered_from_context or normalize(NOT_FOUND) in normalize(answer_text)


def mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Nearest-rank percentile; good enough for latency on small samples."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


# --- similarity floor -------------------------------------------------------------


@dataclass(frozen=True)
class FloorPoint:
    threshold: float
    answerable_kept: float  # share of answerable questions whose best chunk clears it
    off_topic_rejected: float  # share of out-of-scope/injection questions it blocks


@dataclass(frozen=True)
class FloorAnalysis:
    lowest_answerable: float | None
    highest_off_topic: float | None
    points: list[FloorPoint]

    @property
    def gap(self) -> float | None:
        if self.lowest_answerable is None or self.highest_off_topic is None:
            return None
        return self.lowest_answerable - self.highest_off_topic

    @property
    def recommended(self) -> float | None:
        """Middle of the gap when the two groups separate cleanly; otherwise None."""
        gap = self.gap
        if gap is None or gap <= 0 or self.highest_off_topic is None:
            return None
        return round(self.highest_off_topic + gap / 2, 3)


def analyse_floor(
    answerable_top: Sequence[float],
    off_topic_top: Sequence[float],
    thresholds: Sequence[float] | None = None,
) -> FloorAnalysis:
    """How each candidate floor would split answerable from off-topic questions.

    Uses each question's best retrieval score (top-1 similarity), because the
    pipeline answers if at least one chunk clears the floor.
    """
    thresholds = thresholds or [round(0.30 + i * 0.02, 2) for i in range(31)]  # 0.30 … 0.90
    points = [
        FloorPoint(
            threshold=t,
            answerable_kept=(sum(s >= t for s in answerable_top) / len(answerable_top))
            if answerable_top
            else 0.0,
            off_topic_rejected=(sum(s < t for s in off_topic_top) / len(off_topic_top))
            if off_topic_top
            else 0.0,
        )
        for t in thresholds
    ]
    return FloorAnalysis(
        lowest_answerable=min(answerable_top) if answerable_top else None,
        highest_off_topic=max(off_topic_top) if off_topic_top else None,
        points=points,
    )
