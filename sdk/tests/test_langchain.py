"""Tests for LLMScopeCallbackHandler (LangChain integration)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry import trace as otel_trace


def make_test_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.fixture(autouse=True)
def setup_tracer(monkeypatch):
    """Set up in-memory tracer for each test."""
    from llmscope.config import _config
    provider, exporter = make_test_provider()
    otel_trace.set_tracer_provider(provider)
    _config["tracer"] = provider.get_tracer("llmscope-test")
    _config["judge_sample_rate"] = 0.0  # disable judge in tests
    yield exporter


def make_llm_result(text="Hello", input_tokens=10, output_tokens=20, model="gpt-4o-mini"):
    """Build a mock LLMResult."""
    try:
        from langchain_core.outputs import Generation, LLMResult
    except ImportError:
        pytest.skip("langchain-core not installed")

    gen = Generation(text=text)
    return LLMResult(
        generations=[[gen]],
        llm_output={
            "model_name": model,
            "token_usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            },
        },
    )


def test_chain_start_end_creates_span(setup_tracer):
    """on_chain_start + on_chain_end should emit a completed span."""
    try:
        from llmscope.integrations.langchain import LLMScopeCallbackHandler
    except ImportError:
        pytest.skip("langchain-core not installed")

    handler = LLMScopeCallbackHandler()
    run_id = uuid4()

    handler.on_chain_start(
        serialized={"id": ["my_chain"]},
        inputs={"input": "hello"},
        run_id=run_id,
    )
    handler.on_chain_end(outputs={"output": "world"}, run_id=run_id)

    spans = setup_tracer.get_finished_spans()
    assert any("chain.my_chain" in s.name for s in spans)


def test_llm_start_end_records_tokens(setup_tracer):
    """on_llm_start + on_llm_end should record token counts and cost."""
    try:
        from llmscope.integrations.langchain import LLMScopeCallbackHandler
    except ImportError:
        pytest.skip("langchain-core not installed")

    handler = LLMScopeCallbackHandler()
    run_id = uuid4()

    handler.on_llm_start(
        serialized={"id": ["gpt-4o-mini"]},
        prompts=["Tell me a joke"],
        run_id=run_id,
        invocation_params={"model_name": "gpt-4o-mini"},
    )
    handler.on_llm_end(response=make_llm_result(), run_id=run_id)

    spans = setup_tracer.get_finished_spans()
    llm_spans = [s for s in spans if "llm." in s.name]
    assert llm_spans, "Expected at least one llm.* span"
    span = llm_spans[0]
    assert span.attributes.get("gen_ai.usage.input_tokens") == 10
    assert span.attributes.get("gen_ai.usage.output_tokens") == 20
    assert span.attributes.get("llmscope.cost_usd") is not None


def test_chain_error_records_exception(setup_tracer):
    """on_chain_error should record the exception on the span."""
    try:
        from llmscope.integrations.langchain import LLMScopeCallbackHandler
    except ImportError:
        pytest.skip("langchain-core not installed")

    from opentelemetry.trace import StatusCode

    handler = LLMScopeCallbackHandler()
    run_id = uuid4()

    handler.on_chain_start(
        serialized={"id": ["bad_chain"]},
        inputs={},
        run_id=run_id,
    )
    handler.on_chain_error(error=ValueError("boom"), run_id=run_id)

    spans = setup_tracer.get_finished_spans()
    assert any(s.status.status_code == StatusCode.ERROR for s in spans)
