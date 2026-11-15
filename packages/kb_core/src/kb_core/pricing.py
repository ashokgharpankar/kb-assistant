"""Token pricing and cost-per-call maths.

FinOps principle: you cannot manage what you do not measure. From day one every
model call in this project reports its cost, so "cost per query" is a number we
watch, not a surprise on the bill.

The prices below are on-demand list prices in USD per 1 million tokens for
us-east-1. They are config, not truth: AWS changes them. Check
https://aws.amazon.com/bedrock/pricing/ and update PRICES_AS_OF when you do.
"""

from dataclasses import dataclass
from decimal import Decimal

PRICES_AS_OF = "2026-11-14 (from memory, verify against the Bedrock pricing page)"

_PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal = Decimal(0)


PRICES: dict[str, ModelPrice] = {
    # Bedrock, Amazon first-party models (usable on the AWS Free plan)
    "amazon.nova-micro-v1:0": ModelPrice(Decimal("0.035"), Decimal("0.14")),
    "amazon.nova-lite-v1:0": ModelPrice(Decimal("0.06"), Decimal("0.24")),
    "amazon.titan-embed-text-v2:0": ModelPrice(Decimal("0.02")),
    # Local models cost nothing per token (you pay in laptop battery instead)
    "llama3.2": ModelPrice(Decimal(0)),
    "nomic-embed-text": ModelPrice(Decimal(0)),
}

_GEO_PREFIXES = ("us.", "eu.", "apac.", "jp.", "global.")


def normalise_model_id(model_id: str) -> str:
    """Strip a cross-region prefix: `us.amazon.nova-lite-v1:0` -> `amazon.nova-lite-v1:0`."""
    for prefix in _GEO_PREFIXES:
        if model_id.startswith(prefix):
            return model_id[len(prefix) :]
    return model_id


def cost_usd(model_id: str, input_tokens: int, output_tokens: int = 0) -> Decimal:
    """Cost of one call in USD. Raises KeyError for a model with no price on file,
    because silently returning 0 would hide spend."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts cannot be negative")
    price = PRICES[normalise_model_id(model_id)]
    return (
        Decimal(input_tokens) * price.input_per_million
        + Decimal(output_tokens) * price.output_per_million
    ) / _PER_MILLION
