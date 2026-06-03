"""
Context management for llm-scope using Python contextvars.
Allows injecting metadata (user_id, session_id, feature, etc.) into LLM spans.
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from contextvars import ContextVar, Token
from functools import wraps
from typing import Any, Callable, Dict, Generator, Optional


# ContextVar that stores current trace context
_current_context: ContextVar[Dict[str, Any]] = ContextVar(
    "llmscope_context", default={}
)


@contextmanager
def trace_context(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    feature: Optional[str] = None,
    ab_variant: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
) -> Generator[None, None, None]:
    """
    Context manager to inject metadata into all LLM spans within its scope.

    Usage:
        with trace_context(user_id="u_123", feature="rag-bot"):
            response = client.chat.completions.create(...)

    Args:
        user_id: User identifier to attach to all spans.
        session_id: Session identifier for grouping related spans.
        feature: Feature or endpoint name (e.g. "summarizer", "rag-bot").
        ab_variant: A/B test variant label.
        tags: Additional arbitrary string tags.
    """
    ctx: Dict[str, Any] = dict(_current_context.get())  # copy parent context

    if user_id is not None:
        ctx["user.id"] = user_id
    if session_id is not None:
        ctx["session.id"] = session_id
    if feature is not None:
        ctx["feature"] = feature
    if ab_variant is not None:
        ctx["ab_variant"] = ab_variant
    if tags:
        for k, v in tags.items():
            ctx[f"tag.{k}"] = v

    token: Token = _current_context.set(ctx)
    try:
        yield
    finally:
        _current_context.reset(token)


def traced(
    feature: Optional[str] = None,
    extract_user_id: bool = True,
) -> Callable:
    """
    Decorator that automatically injects context from function arguments.
    If the function has an argument named 'user_id', it is auto-extracted.

    Usage:
        @traced(feature="summarizer")
        def summarize(user_id: str, text: str) -> str:
            ...

        @traced(feature="async-chat")
        async def chat(user_id: str, message: str) -> str:
            ...

    Args:
        feature: Feature name to tag on all spans within this function.
        extract_user_id: If True, auto-extract 'user_id' from function args.
    """
    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                extracted_user_id: Optional[str] = None
                if extract_user_id:
                    bound = sig.bind_partial(*args, **kwargs)
                    bound.apply_defaults()
                    extracted_user_id = bound.arguments.get("user_id")

                with trace_context(
                    user_id=str(extracted_user_id) if extracted_user_id else None,
                    feature=feature,
                ):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                extracted_user_id: Optional[str] = None
                if extract_user_id:
                    bound = sig.bind_partial(*args, **kwargs)
                    bound.apply_defaults()
                    extracted_user_id = bound.arguments.get("user_id")

                with trace_context(
                    user_id=str(extracted_user_id) if extracted_user_id else None,
                    feature=feature,
                ):
                    return func(*args, **kwargs)
            return sync_wrapper

    return decorator


def get_current_context() -> Dict[str, Any]:
    """Return current trace context — called by interceptors when building spans."""
    return _current_context.get()
