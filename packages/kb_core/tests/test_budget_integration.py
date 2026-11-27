"""The spend ledger against real Postgres. Skipped unless KB_TEST_DATABASE_URL."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from kb_core.budget import PgSpendLedger
from kb_core.providers import EmbeddingSpace
from kb_core.store import PgVectorStore

from .conftest import DIMS


@pytest.fixture
def ledger(test_database_url: str) -> Iterator[PgSpendLedger]:
    store = PgVectorStore(test_database_url, EmbeddingSpace("test", uuid.uuid4().hex[:8], DIMS))
    store.ensure_schema()
    ledger = PgSpendLedger(store)
    ledger.ensure_schema()
    with store.connect() as conn:
        conn.execute("DELETE FROM kb_spend")
    yield ledger
    store.close()


def test_spend_adds_up_per_day(ledger: PgSpendLedger) -> None:
    assert ledger.spent_today() == 0
    ledger.add(Decimal("0.000049"))
    ledger.add(Decimal("0.000120"))
    assert ledger.spent_today() == Decimal("0.000169")


def test_concurrent_answers_lose_no_spend(ledger: PgSpendLedger) -> None:
    # Two API instances (or threads) adding at once: the upsert must not drop either.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: ledger.add(Decimal("0.001")), range(40)))
    assert ledger.spent_today() == Decimal("0.040")
