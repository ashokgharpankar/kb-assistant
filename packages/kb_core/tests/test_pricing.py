"""Property-style tests: we assert rules that must always hold, not single examples."""

from decimal import Decimal

import pytest

from kb_core.pricing import PRICES, cost_usd, normalise_model_id


@pytest.mark.parametrize("model_id", sorted(PRICES))
def test_zero_tokens_cost_nothing(model_id: str) -> None:
    assert cost_usd(model_id, 0, 0) == Decimal(0)


@pytest.mark.parametrize("model_id", sorted(PRICES))
def test_cost_is_linear_in_tokens(model_id: str) -> None:
    # Doubling the tokens must exactly double the cost.
    assert cost_usd(model_id, 2_000, 400) == 2 * cost_usd(model_id, 1_000, 200)


@pytest.mark.parametrize("model_id", sorted(PRICES))
def test_cost_is_never_negative(model_id: str) -> None:
    assert cost_usd(model_id, 123, 456) >= 0


def test_one_million_input_tokens_costs_the_list_price() -> None:
    assert cost_usd("amazon.nova-micro-v1:0", 1_000_000) == Decimal("0.035")


def test_inference_profile_prefix_uses_the_same_price() -> None:
    assert normalise_model_id("us.amazon.nova-lite-v1:0") == "amazon.nova-lite-v1:0"
    assert cost_usd("us.amazon.nova-lite-v1:0", 1_000, 1_000) == cost_usd(
        "amazon.nova-lite-v1:0", 1_000, 1_000
    )


def test_unknown_model_fails_loudly() -> None:
    with pytest.raises(KeyError):
        cost_usd("some.unpriced-model", 10)


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValueError):
        cost_usd("amazon.nova-micro-v1:0", -1)
