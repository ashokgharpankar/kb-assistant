"""The evaluation set: questions with what a good result must contain.

One JSON object per line (eval/dataset.jsonl). Four kinds:

answerable    the knowledge base covers it. `evidence`: phrases, any one of which
              marks a retrieved chunk as relevant. `facts`: each fact is a list of
              alternative phrasings; the answer should mention at least one per fact.
out_of_scope  nothing in the knowledge base answers it: expect "not found".
injection     tries to make the assistant ignore its rules: expect "not found", and
              none of `must_not_contain` in the answer.
near_domain   on the edge of the knowledge base (an AWS service detail it barely covers).
              Refusing is fine; answering is fine only if no `must_not_contain` term
              appears and the grounding check finds no term missing from the sources.

Labels are phrases rather than chunk IDs on purpose: chunk IDs change every time
chunking changes, phrases survive re-ingestion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Kind = Literal["answerable", "out_of_scope", "injection", "near_domain"]
KINDS: tuple[Kind, ...] = ("answerable", "out_of_scope", "injection", "near_domain")


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    kind: Kind
    evidence: tuple[str, ...] = ()
    facts: tuple[tuple[str, ...], ...] = ()
    must_not_contain: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def should_answer(self) -> bool:
        return self.kind == "answerable"


class DatasetError(ValueError):
    pass


def parse_case(raw: dict[str, object], where: str) -> EvalCase:
    def strings(key: str) -> tuple[str, ...]:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise DatasetError(f"{where}: '{key}' must be a list of non-empty strings")
        return tuple(value)

    case_id, question, kind = raw.get("id"), raw.get("question"), raw.get("kind")
    if not isinstance(case_id, str) or not case_id:
        raise DatasetError(f"{where}: 'id' is required")
    if not isinstance(question, str) or len(question.strip()) < 3:
        raise DatasetError(f"{where}: 'question' is required")
    if kind not in KINDS:
        raise DatasetError(f"{where}: 'kind' must be one of {', '.join(KINDS)}")

    facts_raw = raw.get("facts", [])
    if not isinstance(facts_raw, list):
        raise DatasetError(f"{where}: 'facts' must be a list")
    facts: list[tuple[str, ...]] = []
    for fact in facts_raw:
        alternatives = [fact] if isinstance(fact, str) else fact
        if not isinstance(alternatives, list) or not all(
            isinstance(a, str) and a for a in alternatives
        ):
            raise DatasetError(f"{where}: each fact is a phrase or a list of phrases")
        facts.append(tuple(alternatives))

    case = EvalCase(
        id=case_id,
        question=question.strip(),
        kind=kind,
        evidence=strings("evidence"),
        facts=tuple(facts),
        must_not_contain=strings("must_not_contain"),
        tags=strings("tags"),
    )
    if case.should_answer and not case.evidence:
        raise DatasetError(f"{where}: an answerable case needs 'evidence'")
    return case


def load_dataset(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        where = f"{path.name}:{number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where}: invalid JSON ({exc.msg})") from exc
        if not isinstance(raw, dict):
            raise DatasetError(f"{where}: each line must be a JSON object")
        case = parse_case(raw, where)
        if case.id in seen:
            raise DatasetError(f"{where}: duplicate id '{case.id}'")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise DatasetError(f"{path}: no cases")
    return cases
