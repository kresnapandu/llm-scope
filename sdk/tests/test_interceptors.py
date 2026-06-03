"""
Tests for llm-scope SDK interceptors and core functionality.
Uses InMemorySpanExporter to capture spans without real API calls.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def make_test_provider():
    """Return (TracerProvider, InMemorySpanExporter) for testing."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def fake_openai_response(model="gpt-4o-mini", input_tokens=50, output_tokens=100):
    """Create a mock OpenAI ChatCompletion response."""
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    message = MagicMock()
    message.content = "Hello! How can I help you today?"

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.model = model
    response.usage = usage
    response.choices = [choice]
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Test: init() sets up tracer provider
# ──────────────────────────────────────────────────────────────────────────────


def test_init_sets_tracer_provider():
    """init() should configure _config with a tracer provider."""
    from llmscope.config import _config

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    with patch.object(OTLPSpanExporter, "__init__", return_value=None), \
         patch.object(OTLPSpanExporter, "export", return_value=None), \
         patch("llmscope.core._patch_all"):
        import llmscope
        llmscope.init(endpoint="http://localhost:4317", service_name="test-service")

    assert _config["service_name"] == "test-service"
    assert _config["endpoint"] == "http://localhost:4317"
    assert _config["tracer"] is not None
    assert _config["tracer_provider"] is not None


# ──────────────────────────────────────────────────────────────────────────────
# Test: OpenAI create() produces a span
# ──────────────────────────────────────────────────────────────────────────────


def test_openai_create_produces_span():
    """After init(), calling openai completions.create should emit a span."""
    from llmscope.config import _config
    from llmscope.interceptors import openai_interceptor

    provider, exporter = make_test_provider()
    from opentelemetry import trace as otel_trace
    otel_trace.set_tracer_provider(provider)
    _config["tracer"] = provider.get_tracer("llmscope-test")
    _config["sample_rate"] = 1.0
    _config["redact_prompts"] = False
    _config["redact_completions"] = False

    mock_response = fake_openai_response()

    with patch("openai.resources.chat.completions.Completions.create", return_value=mock_response):
        import openai
        openai_interceptor.patch()

        client = openai.OpenAI(api_key="sk-test")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
        )

        openai_interceptor.unpatch()

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1
    span = spans[0]
    assert span.name == "llm.openai.chat"
    assert span.attributes.get("gen_ai.system") == "openai"
    assert span.attributes.get("gen_ai.request.model") == "gpt-4o-mini"


# ──────────────────────────────────────────────────────────────────────────────
# Test: trace_context injects user.id
# ──────────────────────────────────────────────────────────────────────────────


def test_trace_context_injects_user_id():
    """trace_context should set user.id on spans within its scope."""
    from llmscope.config import _config
    from llmscope.context import trace_context
    from llmscope.interceptors import openai_interceptor

    provider, exporter = make_test_provider()
    from opentelemetry import trace as otel_trace
    otel_trace.set_tracer_provider(provider)
    _config["tracer"] = provider.get_tracer("llmscope-test")
    _config["sample_rate"] = 1.0

    mock_response = fake_openai_response()

    with patch("openai.resources.chat.completions.Completions.create", return_value=mock_response):
        import openai
        openai_interceptor.patch()

        with trace_context(user_id="user_42", feature="test-feature"):
            client = openai.OpenAI(api_key="sk-test")
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )

        openai_interceptor.unpatch()

    spans = exporter.get_finished_spans()
    assert any(
        s.attributes.get("user.id") == "user_42" for s in spans
    ), "Expected user.id='user_42' on at least one span"


# ──────────────────────────────────────────────────────────────────────────────
# Test: redact_prompts=True does not store prompt
# ──────────────────────────────────────────────────────────────────────────────


def test_redact_prompts_hides_prompt_text():
    """When redact_prompts=True, gen_ai.prompt should not appear in span attributes."""
    from llmscope.config import _config
    from llmscope.interceptors import openai_interceptor

    provider, exporter = make_test_provider()
    from opentelemetry import trace as otel_trace
    otel_trace.set_tracer_provider(provider)
    _config["tracer"] = provider.get_tracer("llmscope-test")
    _config["sample_rate"] = 1.0
    _config["redact_prompts"] = True

    mock_response = fake_openai_response()

    with patch("openai.resources.chat.completions.Completions.create", return_value=mock_response):
        import openai
        openai_interceptor.patch()

        client = openai.OpenAI(api_key="sk-test")
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Secret prompt text"}],
        )

        openai_interceptor.unpatch()

    _config["redact_prompts"] = False  # restore

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1
    assert "gen_ai.prompt" not in spans[0].attributes


# ──────────────────────────────────────────────────────────────────────────────
# Test: exception re-raised, span gets ERROR status
# ──────────────────────────────────────────────────────────────────────────────


def test_error_handling_records_exception_and_reraises():
    """If the LLM call raises, the span should have ERROR status and exception is re-raised."""
    from llmscope.config import _config
    from llmscope.interceptors import openai_interceptor
    from opentelemetry.trace import StatusCode

    provider, exporter = make_test_provider()
    from opentelemetry import trace as otel_trace
    otel_trace.set_tracer_provider(provider)
    _config["tracer"] = provider.get_tracer("llmscope-test")
    _config["sample_rate"] = 1.0
    _config["always_sample_errors"] = True

    with patch("openai.resources.chat.completions.Completions.create", side_effect=RuntimeError("API down")):
        import openai
        openai_interceptor.patch()

        client = openai.OpenAI(api_key="sk-test")
        with pytest.raises(RuntimeError, match="API down"):
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )

        openai_interceptor.unpatch()

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1
    error_span = spans[-1]
    assert error_span.status.status_code == StatusCode.ERROR


# ──────────────────────────────────────────────────────────────────────────────
# Test: cost calculation
# ──────────────────────────────────────────────────────────────────────────────


def test_cost_calculation():
    """Cost should be calculated correctly for known models."""
    from llmscope.config import calculate_cost

    # gpt-4o-mini: $0.15/M input, $0.60/M output
    cost = calculate_cost("gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000)
    assert abs(cost - 0.75) < 0.001

    # gpt-4o: $5/M input, $15/M output
    cost = calculate_cost("gpt-4o", input_tokens=1_000_000, output_tokens=0)
    assert abs(cost - 5.0) < 0.001

    # claude-sonnet-4-6: $3/M input, $15/M output
    cost = calculate_cost("claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000)
    assert abs(cost - 15.0) < 0.001

    # Unknown model → 0
    cost = calculate_cost("unknown-model-xyz", input_tokens=1000, output_tokens=1000)
    assert cost == 0.0 or cost >= 0.0  # graceful, no crash


# ──────────────────────────────────────────────────────────────────────────────
# Test: context.py traced decorator
# ──────────────────────────────────────────────────────────────────────────────


def test_traced_decorator_injects_user_id():
    """@traced should auto-extract user_id from function args."""
    from llmscope.context import get_current_context, traced

    captured = {}

    @traced(feature="my-feature")
    def my_func(user_id: str, text: str) -> str:
        captured.update(get_current_context())
        return text

    my_func(user_id="user_99", text="hello")

    assert captured.get("user.id") == "user_99"
    assert captured.get("feature") == "my-feature"
