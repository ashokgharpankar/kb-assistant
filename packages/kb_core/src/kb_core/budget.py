"""A daily spend cap that degrades in steps instead of failing (Phase 8b, ADR 0019).

AWS Budgets (Phase 0) reports spend hours late and can only alert; it can't stop the next
call. This cap is checked before every model call, against a ledger the app writes after
every answer:

    spent < soft (80%)  →  normal: routing may escalate to the larger model
    soft ≤ spent < cap  →  economy: the small model only, answers marked "economy"
    spent ≥ cap         →  no model call; "over budget" (exact cache hits still answer,
                           because the cache sits in front of this wrapper)

The check runs before the call and the cost is added after it, so concurrent requests can
overshoot the cap by at most (requests in flight × cost of one answer): cents, not dollars.
A hard guarantee would need a reservation per request; not worth it at this scale.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from kb_core.models import Answer, DoneEvent, SourcesEvent, StreamEvent, TokenEvent
from kb_core.pricing import cost_usd

if TYPE_CHECKING:
    import psycopg

    from kb_core.factory import Answerer
    from kb_core.settings import Settings

OVER_BUDGET = "The assistant has reached its usage limit for today. Please try again tomorrow."

CostFn = Callable[[Answer], Decimal]


class SpendLedger(Protocol):
    def spent_today(self) -> Decimal: ...

    def add(self, usd: Decimal) -> None: ...


class _Connects(Protocol):
    def connect(self) -> AbstractContextManager[psycopg.Connection]: ...


class PgSpendLedger:
    """One row per UTC day. The database decides the day, so every API instance agrees."""

    def __init__(self, store: _Connects) -> None:
        self.pg = store

    def ensure_schema(self) -> None:
        with self.pg.connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS kb_spend (
                       day date PRIMARY KEY,
                       usd numeric(14, 8) NOT NULL DEFAULT 0,
                       answers integer NOT NULL DEFAULT 0
                   )"""
            )

    def spent_today(self) -> Decimal:
        with self.pg.connect() as conn:
            row = conn.execute(
                "SELECT usd FROM kb_spend WHERE day = (now() AT TIME ZONE 'utc')::date"
            ).fetchone()
        return Decimal(row[0]) if row else Decimal(0)

    def add(self, usd: Decimal) -> None:
        with self.pg.connect() as conn:
            conn.execute(
                """INSERT INTO kb_spend (day, usd, answers)
                    VALUES ((now() AT TIME ZONE 'utc')::date, %s, 1)
                    ON CONFLICT (day) DO UPDATE
                    SET usd = kb_spend.usd + EXCLUDED.usd, answers = kb_spend.answers + 1""",
                (usd,),
            )


def cost_basis(settings: Settings) -> CostFn:
    """What an answer adds to the ledger: its real cost, or ("projected") its tokens priced
    on the hosted models, so the cap can be rehearsed on local models that cost $0."""
    if settings.budget_cost_basis == "actual":
        return lambda a: a.total_cost_usd
    small, large = settings.projected_price_model, settings.projected_price_model_large

    def projected(a: Answer) -> Decimal:
        if a.escalation is None:
            return cost_usd(small, a.input_tokens, a.output_tokens)
        return cost_usd(small, a.escalation.input_tokens, a.escalation.output_tokens) + cost_usd(
            large, a.input_tokens, a.output_tokens
        )

    return projected


class BudgetedAnswerer:
    def __init__(
        self,
        inner: Answerer,
        economy: Answerer,
        ledger: SpendLedger,
        daily_usd: Decimal,
        soft_ratio: float,
        cost_of: CostFn,
    ) -> None:
        self.inner, self.economy, self.ledger = inner, economy, ledger
        self.daily_usd = daily_usd
        self.soft_usd = daily_usd * Decimal(str(soft_ratio))
        self.cost_of = cost_of
        self.tracer = inner.tracer

    def level(self) -> str:
        spent = self.ledger.spent_today()
        if spent >= self.daily_usd:
            return "over_budget"
        return "economy" if spent >= self.soft_usd else "normal"

    def answer(self, question: str) -> Answer:
        for event in self.stream(question):
            if isinstance(event, DoneEvent):
                return event.answer
        raise RuntimeError("stream ended without a final answer")  # pragma: no cover

    def stream(self, question: str) -> Iterator[StreamEvent]:
        level = self.level()
        if level == "over_budget":
            with self.tracer.observe("budget.exhausted", input={"question": question}):
                pass
            yield SourcesEvent([])
            yield TokenEvent(OVER_BUDGET)
            yield DoneEvent(
                Answer(
                    question=question,
                    text=OVER_BUDGET,
                    answered_from_context=False,
                    searches=0,
                    blocked_by="budget",
                    degraded="over_budget",
                )
            )
            return

        answerer = self.economy if level == "economy" else self.inner
        for event in answerer.stream(question):
            if isinstance(event, DoneEvent):
                answer = event.answer
                spent = self.cost_of(answer)
                if spent:
                    self.ledger.add(spent)
                if level == "economy":
                    answer = replace(answer, degraded="economy")
                yield DoneEvent(answer)
            else:
                yield event
