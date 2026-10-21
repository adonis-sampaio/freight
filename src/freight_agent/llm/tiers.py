"""Model tiering and price table.

Three tiers, picked by the call site:

* ``fast``      - `gpt-6-luna`. Classification, extraction, drafting. The default.
* ``balanced``  - `gpt-6.1-sol`. Escalated or ambiguous decisions.
* ``frontier``  - `gpt-6-astra`. Rare, hard reasoning. Budget-guarded.

The prices below are the published OpenAI rates per million tokens
(input / cached input / output) as of October 2026. They are used for cost
accounting and for the per-load budget guard, not for billing.
"""

from __future__ import annotations

from enum import StrEnum


class ModelTier(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    FRONTIER = "frontier"


# model -> (input, cached_input, output) USD per 1M tokens
PRICING: dict[str, tuple[float, float, float]] = {
    "gpt-6-astra": (10.00, 1.00, 50.00),
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6-sol": (2.00, 0.20, 10.00),
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-6.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}

EMBEDDING_PRICING_PER_MTOK = 0.02


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Cost of one call in USD. Unknown models cost 0 and are flagged separately."""
    pricing = PRICING.get(model)
    if pricing is None:
        return 0.0
    input_price, cached_price, output_price = pricing
    fresh_input = max(0, input_tokens - cached_tokens)
    return (
        fresh_input * input_price
        + cached_tokens * cached_price
        + output_tokens * output_price
    ) / 1_000_000


def tier_models(settings) -> dict[ModelTier, str]:
    return {
        ModelTier.FAST: settings.llm_tier_fast_model,
        ModelTier.BALANCED: settings.llm_tier_balanced_model,
        ModelTier.FRONTIER: settings.llm_tier_frontier_model,
    }
