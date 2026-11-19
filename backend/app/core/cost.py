"""Model price table and cost calculation. One place to update prices (SPEC §12).

Prices are USD per million tokens.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_m: float
    output_per_m: float
    cache_read_per_m: float


PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(input_per_m=2.00, output_per_m=10.00, cache_read_per_m=0.10),
    "claude-opus-5-5": ModelPrice(input_per_m=4.00, output_per_m=20.00, cache_read_per_m=0.20),
}

_PER = 1_000_000


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Return the USD cost of one call.

    `input_tokens` is uncached input only (as reported by the Anthropic API's
    `usage.input_tokens`); cache reads are billed separately at the cache-read rate.
    Raises KeyError for an unknown model so a missing price is never silently $0.
    """
    if min(input_tokens, output_tokens, cache_read_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    try:
        price = PRICES[model]
    except KeyError:
        raise KeyError(f"no price for model {model!r}; add it to app.core.cost.PRICES") from None
    return (
        input_tokens * price.input_per_m
        + output_tokens * price.output_per_m
        + cache_read_tokens * price.cache_read_per_m
    ) / _PER
