"""
Anthropic monkey-patch interceptor for llm-scope.
Wraps messages.create (sync + async + streaming) to emit OTel spans.
"""

from __future__ import annotations

import random
import time
import logging
from typing import Any, AsyncGenerator, Generator

import wrapt
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from ..config import _config, calculate_cost
from ..context import get_current_context

logger = logging.getLogger(__name__)

_original_create = None
_original_async_create = None


def patch() -> None:
    """Monkey-patch Anthropic messages (sync + async)."""
    global _original_create, _original_async_create

    import anthropic.resources.messages as _mod

    _original_create = _mod.Messages.create
    wrapt.wrap_function_wrapper(
        "anthropic.resources.messages",
        "Messages.create",
        _wrap_create,
    )

    _original_async_create = _mod.AsyncMessages.create
    wrapt.wrap_function_wrapper(
        "anthropic.resources.messages",
        "AsyncMessages.create",
        _wrap_async_create,
    )


def unpatch() -> None:
    """Restore original Anthropic functions."""
    global _original_create, _original_async_create

    import anthropic.resources.messages as _mod

    if _original_create is not None:
        _mod.Messages.create = _original_create
        _original_create = None

    if _original_async_create is not None:
        _mod.AsyncMessages.create = _original_async_create
        _original_async_create = None


def _should_sample(is_error: bool = False) -> bool:
    if is_error and _config.get("always_sample_errors", True):
        return True
    return random.random() <= _config.get("sample_rate", 1.0)


def _set_pre_call_attributes(span: trace.Span, kwargs: dict) -> None:
    model = kwargs.get("model", "unknown")
    span.set_attribute("gen_ai.system", "anthropic")
    span.set_attribute("gen_ai.request.model", model)

    max_tokens = kwargs.get("max_tokens")
    if max_tokens is not None:
        span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))

    temperature = kwargs.get("temperature")
    if temperature is not None:
        span.set_attribute("gen_ai.request.temperature", float(temperature))

    if not _config.get("redact_prompts", False):
        messages = kwargs.get("messages", [])
        system = kwargs.get("system", "")
        prompt_repr = f"system: {system}\n" if system else ""
        prompt_repr += str(messages)
        span.set_attribute("gen_ai.prompt", prompt_repr[:2000])

    for k, v in get_current_context().items():
        span.set_attribute(k, str(v))


def _set_post_call_attributes(span: trace.Span, response: Any, model: str, start_time: float) -> None:
    latency_ms = int((time.time() - start_time) * 1000)
    span.set_attribute("llmscope.latency_ms", latency_ms)

    usage = getattr(response, "usage", None)
    input_tokens = 0
    output_tokens = 0

    if usage:
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)

    cost = calculate_cost(model, input_tokens, output_tokens)
    span.set_attribute("llmscope.cost_usd", cost)

    if not _config.get("redact_completions", False):
        content = getattr(response, "content", [])
        text = ""
        if content and hasattr(content[0], "text"):
            text = content[0].text or ""
        span.set_attribute("gen_ai.completion", text[:2000])


def _wrap_create(wrapped, instance, args, kwargs):
    """Sync wrapper for Messages.create."""
    if not _should_sample():
        return wrapped(*args, **kwargs)

    is_streaming = kwargs.get("stream", False)
    model = kwargs.get("model", "unknown")
    tracer = _config.get("tracer") or trace.get_tracer("llmscope")

    with tracer.start_as_current_span("llm.anthropic.messages") as span:
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
    """Async wrapper for AsyncMessages.create."""
    if not _should_sample():
        return await wrapped(*args, **kwargs)

    is_streaming = kwargs.get("stream", False)
    model = kwargs.get("model", "unknown")
    tracer = _config.get("tracer") or trace.get_tracer("llmscope")

    with tracer.start_as_current_span("llm.anthropic.messages") as span:
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
    """Wrap Anthropic sync streaming (MessageStream / raw stream)."""
    accumulated_text = ""
    input_tokens = 0
    output_tokens = 0

    try:
        # Anthropic streaming can be a MessageStreamManager or raw iterator
        if hasattr(stream, "__enter__"):
            ctx = stream.__enter__()
            stream_iter = ctx
        else:
            stream_iter = stream

        for event in stream_iter:
            event_type = getattr(event, "type", "")

            if event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta and hasattr(delta, "text"):
                    accumulated_text += delta.text or ""

            elif event_type == "message_delta":
                usage = getattr(event, "usage", None)
                if usage:
                    output_tokens = getattr(usage, "output_tokens", 0) or 0

            elif event_type == "message_start":
                msg = getattr(event, "message", None)
                if msg:
                    usage = getattr(msg, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "input_tokens", 0) or 0

            yield event

        _finalize_stream_span(span, model, input_tokens, output_tokens, accumulated_text, start_time)
        span.set_status(Status(StatusCode.OK))

    except Exception as e:
        span.record_exception(e)
        span.set_status(Status(StatusCode.ERROR, str(e)))
        raise
    finally:
        span.end()


async def _wrap_async_stream(span: trace.Span, stream, model: str, start_time: float) -> AsyncGenerator:
    """Wrap Anthropic async streaming."""
    accumulated_text = ""
    input_tokens = 0
    output_tokens = 0

    try:
        if hasattr(stream, "__aenter__"):
            ctx = await stream.__aenter__()
            stream_iter = ctx
        else:
            stream_iter = stream

        async for event in stream_iter:
            event_type = getattr(event, "type", "")

            if event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta and hasattr(delta, "text"):
                    accumulated_text += delta.text or ""

            elif event_type == "message_delta":
                usage = getattr(event, "usage", None)
                if usage:
                    output_tokens = getattr(usage, "output_tokens", 0) or 0

            elif event_type == "message_start":
                msg = getattr(event, "message", None)
                if msg:
                    usage = getattr(msg, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "input_tokens", 0) or 0

            yield event

        _finalize_stream_span(span, model, input_tokens, output_tokens, accumulated_text, start_time)
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
    latency_ms = int((time.time() - start_time) * 1000)
    span.set_attribute("llmscope.latency_ms", latency_ms)
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    span.set_attribute("llmscope.cost_usd", calculate_cost(model, input_tokens, output_tokens))

    if not _config.get("redact_completions", False):
        span.set_attribute("gen_ai.completion", content[:2000])
