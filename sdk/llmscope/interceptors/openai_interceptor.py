"""
OpenAI monkey-patch interceptor for llm-scope.
Wraps chat.completions.create (sync + async + streaming) to emit OTel spans.
"""

from __future__ import annotations

import random
import time
import logging
from typing import Any, AsyncGenerator, Generator, Optional

import wrapt
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from ..config import _config, calculate_cost
from ..context import get_current_context

logger = logging.getLogger(__name__)

_original_create = None
_original_async_create = None


def patch() -> None:
    """Monkey-patch OpenAI chat completions (sync + async)."""
    global _original_create, _original_async_create

    import openai.resources.chat.completions as _mod

    # Sync
    _original_create = _mod.Completions.create
    wrapt.wrap_function_wrapper(
        "openai.resources.chat.completions",
        "Completions.create",
        _wrap_create,
    )

    # Async
    _original_async_create = _mod.AsyncCompletions.create
    wrapt.wrap_function_wrapper(
        "openai.resources.chat.completions",
        "AsyncCompletions.create",
        _wrap_async_create,
    )


def unpatch() -> None:
    """Restore original OpenAI functions."""
    global _original_create, _original_async_create

    import openai.resources.chat.completions as _mod

    if _original_create is not None:
        _mod.Completions.create = _original_create
        _original_create = None

    if _original_async_create is not None:
        _mod.AsyncCompletions.create = _original_async_create
        _original_async_create = None


def _should_sample(is_error: bool = False) -> bool:
    """Determine whether to create a span for this call."""
    if is_error and _config.get("always_sample_errors", True):
        return True
    return random.random() <= _config.get("sample_rate", 1.0)


def _set_pre_call_attributes(span: trace.Span, kwargs: dict) -> None:
    """Set span attributes available before the LLM call."""
    model = kwargs.get("model", "unknown")
    span.set_attribute("gen_ai.system", "openai")
    span.set_attribute("gen_ai.request.model", model)

    temperature = kwargs.get("temperature")
    if temperature is not None:
        span.set_attribute("gen_ai.request.temperature", float(temperature))

    max_tokens = kwargs.get("max_tokens")
    if max_tokens is not None:
        span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))

    if not _config.get("redact_prompts", False):
        messages = kwargs.get("messages", [])
        span.set_attribute("gen_ai.prompt", str(messages)[:2000])

    # Inject current trace context tags
    for k, v in get_current_context().items():
        span.set_attribute(k, str(v))


def _set_post_call_attributes(span: trace.Span, response: Any, model: str, start_time: float) -> None:
    """Set span attributes from the LLM response."""
    latency_ms = int((time.time() - start_time) * 1000)
    span.set_attribute("llmscope.latency_ms", latency_ms)

    usage = getattr(response, "usage", None)
    input_tokens = 0
    output_tokens = 0

    if usage:
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)

    cost = calculate_cost(model, input_tokens, output_tokens)
    span.set_attribute("llmscope.cost_usd", cost)

    if not _config.get("redact_completions", False):
        choices = getattr(response, "choices", [])
        if choices:
            content = getattr(getattr(choices[0], "message", None), "content", "") or ""
            span.set_attribute("gen_ai.completion", content[:2000])


def _wrap_create(wrapped, instance, args, kwargs):
    """Sync wrapper for Completions.create."""
    if not _should_sample():
        return wrapped(*args, **kwargs)

    is_streaming = kwargs.get("stream", False)
    model = kwargs.get("model", "unknown")
    tracer = _config.get("tracer") or trace.get_tracer("llmscope")

    with tracer.start_as_current_span("llm.openai.chat") as span:
        _set_pre_call_attributes(span, kwargs)
        start_time = time.time()

        try:
            response = wrapped(*args, **kwargs)

            if is_streaming:
                return _wrap_stream(span, response, model, start_time)

            _set_post_call_attributes(span, response, model, start_time)
            span.set_status(Status(StatusCode.OK))
            return response

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise


async def _wrap_async_create(wrapped, instance, args, kwargs):
    """Async wrapper for AsyncCompletions.create."""
    if not _should_sample():
        return await wrapped(*args, **kwargs)

    is_streaming = kwargs.get("stream", False)
    model = kwargs.get("model", "unknown")
    tracer = _config.get("tracer") or trace.get_tracer("llmscope")

    with tracer.start_as_current_span("llm.openai.chat") as span:
        _set_pre_call_attributes(span, kwargs)
        start_time = time.time()

        try:
            response = await wrapped(*args, **kwargs)

            if is_streaming:
                return _wrap_async_stream(span, response, model, start_time)

            _set_post_call_attributes(span, response, model, start_time)
            span.set_status(Status(StatusCode.OK))
            return response

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise


def _wrap_stream(span: trace.Span, stream, model: str, start_time: float) -> Generator:
    """Wrap a sync streaming response to accumulate chunks and finalize span."""
    accumulated_content = ""
    input_tokens = 0
    output_tokens = 0

    try:
        for chunk in stream:
            choices = getattr(chunk, "choices", [])
            if choices:
                delta = getattr(choices[0], "delta", None)
                if delta:
                    content = getattr(delta, "content", "") or ""
                    accumulated_content += content

            # Some providers include usage in the final chunk
            usage = getattr(chunk, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0

            yield chunk

        # Estimate tokens if not provided
        if output_tokens == 0 and accumulated_content:
            try:
                import tiktoken
                enc = tiktoken.encoding_for_model(model)
                output_tokens = len(enc.encode(accumulated_content))
            except Exception:
                output_tokens = len(accumulated_content.split()) * 4 // 3

        _finalize_stream_span(span, model, input_tokens, output_tokens, accumulated_content, start_time)
        span.set_status(Status(StatusCode.OK))

    except Exception as e:
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)))
        raise
    finally:
        span.end()


async def _wrap_async_stream(span: trace.Span, stream, model: str, start_time: float) -> AsyncGenerator:
    """Wrap an async streaming response to accumulate chunks and finalize span."""
    accumulated_content = ""
    input_tokens = 0
    output_tokens = 0

    try:
        async for chunk in stream:
            choices = getattr(chunk, "choices", [])
            if choices:
                delta = getattr(choices[0], "delta", None)
                if delta:
                    content = getattr(delta, "content", "") or ""
                    accumulated_content += content

            usage = getattr(chunk, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0

            yield chunk

        if output_tokens == 0 and accumulated_content:
            try:
                import tiktoken
                enc = tiktoken.encoding_for_model(model)
                output_tokens = len(enc.encode(accumulated_content))
            except Exception:
                output_tokens = len(accumulated_content.split()) * 4 // 3

        _finalize_stream_span(span, model, input_tokens, output_tokens, accumulated_content, start_time)
        span.set_status(Status(StatusCode.OK))

    except Exception as e:
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)))
        raise
    finally:
        span.end()


def _finalize_stream_span(
    span: trace.Span,
    model: str,
    input_tokens: int,
    output_tokens: int,
    content: str,
    start_time: float,
) -> None:
    """Finalize attributes on a streaming span."""
    latency_ms = int((time.time() - start_time) * 1000)
    span.set_attribute("llmscope.latency_ms", latency_ms)
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    span.set_attribute("llmscope.cost_usd", calculate_cost(model, input_tokens, output_tokens))

    if not _config.get("redact_completions", False):
        span.set_attribute("gen_ai.completion", content[:2000])
