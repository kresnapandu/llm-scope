"""
Core initialization and shutdown for llm-scope SDK.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from .config import _config

logger = logging.getLogger(__name__)

_patched_modules: list = []


def init(
    endpoint: str,
    service_name: str,
    sample_rate: float = 1.0,
    redact_prompts: bool = False,
    redact_completions: bool = False,
    model_prices: Optional[Dict[str, Dict[str, float]]] = None,
    judge_sample_rate: float = 0.1,
    judge_model: str = "gpt-4o-mini",
    always_sample_errors: bool = True,
) -> None:
    """
    Initialize the llm-scope SDK.

    Args:
        endpoint: OTLP gRPC endpoint (e.g. "http://localhost:4317").
        service_name: Name of the service being instrumented.
        sample_rate: Fraction of traces to capture (0.0–1.0).
        redact_prompts: If True, prompt text is not stored in spans.
        redact_completions: If True, completion text is not stored in spans.
        model_prices: Custom pricing dict {model: {input: float, output: float}}
                      in USD per 1M tokens. Falls back to built-in defaults.
        judge_sample_rate: Fraction of completions sent to hallucination judge.
        judge_model: Model to use for LLM-as-judge scoring.
        always_sample_errors: If True, always capture error spans regardless of sample_rate.
    """
    # Store config
    _config["endpoint"] = endpoint
    _config["service_name"] = service_name
    _config["sample_rate"] = sample_rate
    _config["redact_prompts"] = redact_prompts
    _config["redact_completions"] = redact_completions
    _config["model_prices"] = model_prices
    _config["judge_sample_rate"] = judge_sample_rate
    _config["judge_model"] = judge_model
    _config["judge_endpoint"] = f"{endpoint.rstrip('/').replace(':4317', ':8000')}/api/judge"
    _config["always_sample_errors"] = always_sample_errors

    # Setup OpenTelemetry
    resource = Resource.create({"service.name": service_name})
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _config["tracer_provider"] = provider
    _config["tracer"] = trace.get_tracer("llmscope", "0.1.0")

    logger.info(f"llm-scope initialized: service={service_name}, endpoint={endpoint}")

    # Monkey-patch LLM clients
    _patch_all()


def _patch_all() -> None:
    """Attempt to monkey-patch all installed LLM clients."""
    global _patched_modules

    try:
        import openai  # noqa: F401
        from .interceptors import openai_interceptor
        openai_interceptor.patch()
        _patched_modules.append(openai_interceptor)
        logger.debug("llm-scope: OpenAI patched")
    except ImportError:
        pass

    try:
        import anthropic  # noqa: F401
        from .interceptors import anthropic_interceptor
        anthropic_interceptor.patch()
        _patched_modules.append(anthropic_interceptor)
        logger.debug("llm-scope: Anthropic patched")
    except ImportError:
        pass


def shutdown() -> None:
    """
    Flush pending spans and shut down the tracer provider.
    Also restores all monkey-patched functions.
    """
    for module in _patched_modules:
        try:
            module.unpatch()
        except Exception as e:
            logger.warning(f"llm-scope: Error unpatching {module}: {e}")
    _patched_modules.clear()

    provider = _config.get("tracer_provider")
    if provider:
        try:
            provider.force_flush()
            provider.shutdown()
        except Exception as e:
            logger.warning(f"llm-scope: Error shutting down tracer provider: {e}")

    logger.info("llm-scope: shutdown complete")
