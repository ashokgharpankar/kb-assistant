"""Pick the semantic-cache threshold from labelled question pairs (Phase 8a).

The semantic cache answers a new question with a stored answer when the two
questions' embeddings are at least `threshold` similar. Too low and a question
with a different meaning gets someone else's answer (a wrong answer served
confidently, the expensive mistake). Too high and the cache never hits.

Same method as the similarity floor (Phase 4): label pairs that should share an
answer ("same") and pairs that should not ("different", the near misses that
matter), embed both sides, and look for a gap between the two groups.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kb_core.cache import normalise_question
from kb_core.evaluation.metrics import FloorAnalysis, analyse_floor

EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class CachePair:
    a: str
    b: str
    same: bool
    note: str = ""


@dataclass(frozen=True)
class ScoredPair:
    pair: CachePair
    similarity: float


def load_pairs(path: Path) -> list[CachePair]:
    pairs = []
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        row = json.loads(line)
        if not isinstance(row.get("same"), bool):
            raise ValueError(f"{path}:{n}: 'same' must be true or false")
        pairs.append(CachePair(row["a"], row["b"], row["same"], row.get("note", "")))
    return pairs


def cosine(u: Sequence[float], v: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v, strict=True))
    norm = math.sqrt(sum(x * x for x in u)) * math.sqrt(sum(y * y for y in v))
    return dot / norm if norm else 0.0


def score_pairs(pairs: Sequence[CachePair], embed: EmbedFn) -> list[ScoredPair]:
    """Score every pair the way the cache does: an exact match after normalising is 1.0
    (no embedding needed), otherwise cosine over the embeddings of the raw questions."""
    texts = sorted({t for p in pairs for t in (p.a, p.b)})
    vectors = dict(zip(texts, embed(texts), strict=True))
    return [
        ScoredPair(
            p,
            1.0
            if normalise_question(p.a) == normalise_question(p.b)
            else cosine(vectors[p.a], vectors[p.b]),
        )
        for p in pairs
    ]


def analyse(scored: Sequence[ScoredPair]) -> FloorAnalysis:
    """`answerable_kept` reads as "same-meaning pairs that hit"; `off_topic_rejected`
    as "different-meaning pairs kept apart"."""
    return analyse_floor(
        [s.similarity for s in scored if s.pair.same],
        [s.similarity for s in scored if not s.pair.same],
        thresholds=[round(0.80 + i * 0.01, 2) for i in range(21)],  # 0.80 … 1.00
    )


def wrong_hits(scored: Sequence[ScoredPair], threshold: float) -> list[ScoredPair]:
    """Different-meaning pairs the threshold would serve from the cache: each one is a
    user getting an answer to a question they did not ask."""
    return [s for s in scored if not s.pair.same and s.similarity >= threshold]
