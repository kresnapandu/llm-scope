"""
Module-level config dict shared across all interceptors.
Separated to avoid circular imports.
"""

from typing import Any, Dict, Optional

_config: Dict[str, Any] = {
    "endpoint": None,
    "service_name": "unknown",
    "sample_rate": 1.0,
    "redact_prompts": False,
    "redact_completions": False,
    "model_prices": None,
    "judge_sample_rate": 0.1,
    "judge_model": "gpt-4o-mini",
    "judge_endpoint": "http://localhost:8000/api/judge",
    "always_sample_errors": True,
    "tracer_provider": None,
    "tracer": None,
}

# Default model prices (USD per 1M tokens)
DEFAULT_MODEL_PRICES: Dict[str, Dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 5.00, "output": 15.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given model and token counts."""
    prices = _config.get("model_prices") or DEFAULT_MODEL_PRICES
    model_price = prices.get(model)
    if not model_price:
        # Try prefix match for unknown model variants
        for key, price in DEFAULT_MODEL_PRICES.items():
            if model.startswith(key) or key.startswith(model.split("-")[0]):
                model_price = price
                break
    if not model_price:
        return 0.0
    return (input_tokens * model_price["input"] + output_tokens * model_price["output"]) / 1_000_000
