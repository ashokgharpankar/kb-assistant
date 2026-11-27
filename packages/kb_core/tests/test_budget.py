"""Phase 8b: the daily spend cap degrades in steps (normal → economy → over budget)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from kb_core.budget import OVER_BUDGET, BudgetedAnswerer, cost_basis
from kb_core.models import Answer, DoneEvent, Escalation, SourcesEvent, StreamEvent, TokenEvent
from kb_core.settings import Settings
from kb_core.tracing import NoopTracer, Tracer


class Ledger:
    def __init__(self, spent: str = "0") -> None:
        self.spent = Decimal(spent)

    def spent_today(self) -> Decimal:
        return self.spent

    def add(self, usd: Decimal) -> None:
        self.spent += usd


class Model:
    tracer: Tracer = NoopTracer()

    def __init__(self, name: str, cost: str = "0.01") -> None:
        self.name, self.cost, self.calls = name, Decimal(cost), 0

    def answer(self, question: str) -> Answer:  # pragma: no cover - stream is used
        raise NotImplementedError

    def stream(self, question: str) -> Iterator[StreamEvent]:
        self.calls += 1
        yield SourcesEvent([])
        yield TokenEvent("ok")
        yield DoneEvent(
            Answer(
                question=question, text="ok", model=self.name, output_tokens=10, cost_usd=self.cost
            )
        )


def capped(spent: str, daily: str = "1.00") -> tuple[BudgetedAnswerer, Model, Model, Ledger]:
    full, economy, ledger = Model("full"), Model("economy"), Ledger(spent)
    answerer = BudgetedAnswerer(
        full, economy, ledger, Decimal(daily), 0.8, cost_of=lambda a: a.total_cost_usd
    )
    return answerer, full, economy, ledger


def test_under_the_soft_limit_routing_stays_on_and_spend_is_recorded() -> None:
    answerer, full, economy, ledger = capped("0.50")
    answer = answerer.answer("q")
    assert answer.model == "full" and answer.degraded is None
    assert (full.calls, economy.calls) == (1, 0)
    assert ledger.spent == Decimal("0.51")


def test_at_the_soft_limit_the_small_model_answers_alone() -> None:
    answerer, full, economy, _ = capped("0.80")
    answer = answerer.answer("q")
    assert answer.model == "economy" and answer.degraded == "economy"
    assert (full.calls, economy.calls) == (0, 1)


def test_at_the_cap_no_model_is_called() -> None:
    answerer, full, economy, ledger = capped("1.00")
    answer = answerer.answer("q")
    assert answer.text == OVER_BUDGET and answer.blocked_by == "budget"
    assert answer.degraded == "over_budget" and not answer.answered_from_context
    assert (full.calls, economy.calls) == (0, 0)
    assert ledger.spent == Decimal("1.00")  # nothing added


def test_a_zero_budget_is_a_kill_switch() -> None:
    answerer, full, _, _ = capped("0", daily="0")
    assert answerer.answer("q").blocked_by == "budget" and full.calls == 0


def test_free_answers_add_nothing() -> None:
    class Recording(Ledger):
        calls: list[Decimal] = []

        def add(self, usd: Decimal) -> None:
            self.calls.append(usd)

    ledger = Recording()
    full, economy = Model("full", cost="0"), Model("economy")
    BudgetedAnswerer(full, economy, ledger, Decimal(1), 0.8, lambda a: a.total_cost_usd).answer("q")
    assert ledger.calls == []


def test_projected_basis_prices_local_tokens_on_the_hosted_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_BUDGET_COST_BASIS", "projected")
    cost = cost_basis(Settings(_env_file=None))
    plain = Answer(question="q", text="a", model="llama3.2", input_tokens=1000, output_tokens=100)
    assert cost(plain) == Decimal("0.000049")  # Nova Micro: 1000 x 0.035 + 100 x 0.14 per M
    escalated = Answer(
        question="q",
        text="a",
        model="qwen2.5:7b",
        input_tokens=1000,
        output_tokens=100,
        escalation=Escalation("llama3.2", 1000, 10, Decimal(0), "refused_with_evidence"),
    )
    # first call on Micro (1000/10) + escalation on Lite (1000/100)
    assert cost(escalated) == Decimal("0.0000364") + Decimal("0.000084")


def test_actual_basis_includes_the_first_models_attempt() -> None:
    a = Answer(
        question="q",
        text="a",
        cost_usd=Decimal("0.002"),
        escalation=Escalation("m", 1, 1, Decimal("0.001"), "refused_with_evidence"),
    )
    assert cost_basis(Settings(_env_file=None))(a) == Decimal("0.003")
