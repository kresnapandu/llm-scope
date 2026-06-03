"""Interceptors package for llm-scope."""

from opentelemetry import trace


def start_span(name: str, **attributes):
    """
    Manually start a span with the llmscope tracer.
    Useful for custom instrumentation outside auto-patching.

    Args:
        name: Span name.
        **attributes: Key-value attributes to set on the span.

    Returns:
        opentelemetry.trace.Span context manager.
    """
    from ..config import _config
    tracer = _config.get("tracer") or trace.get_tracer("llmscope")
    span = tracer.start_span(name)
    for k, v in attributes.items():
        if v is not None:
            span.set_attribute(k, str(v))
    return span
