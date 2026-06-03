"""Tests for llmscope.context module."""

from __future__ import annotations

import asyncio
import pytest
from llmscope.context import get_current_context, trace_context, traced


def test_trace_context_sets_and_restores():
    """trace_context should set values and clean up after exit."""
    assert get_current_context() == {}

    with trace_context(user_id="u1", session_id="s1", feature="test"):
        ctx = get_current_context()
        assert ctx["user.id"] == "u1"
        assert ctx["session.id"] == "s1"
        assert ctx["feature"] == "test"

    # After context exits, should be cleared
    assert get_current_context() == {}


def test_trace_context_nesting():
    """Nested trace_context should layer values correctly."""
    with trace_context(user_id="outer", feature="outer-feature"):
        assert get_current_context()["user.id"] == "outer"

        with trace_context(user_id="inner", feature="inner-feature"):
            ctx = get_current_context()
            assert ctx["user.id"] == "inner"
            assert ctx["feature"] == "inner-feature"

        # Back to outer
        assert get_current_context()["user.id"] == "outer"


def test_trace_context_custom_tags():
    """Custom tags should be prefixed with 'tag.'."""
    with trace_context(tags={"env": "prod", "version": "1.2"}):
        ctx = get_current_context()
        assert ctx["tag.env"] == "prod"
        assert ctx["tag.version"] == "1.2"


def test_traced_decorator_sync():
    """@traced decorator should inject context for sync functions."""
    captured = {}

    @traced(feature="sync-feature")
    def my_func(user_id: str, text: str) -> str:
        captured.update(get_current_context())
        return text

    result = my_func(user_id="u123", text="hello")
    assert result == "hello"
    assert captured["user.id"] == "u123"
    assert captured["feature"] == "sync-feature"


def test_traced_decorator_async():
    """@traced decorator should inject context for async functions."""
    captured = {}

    @traced(feature="async-feature")
    async def my_async_func(user_id: str) -> None:
        captured.update(get_current_context())

    asyncio.run(my_async_func(user_id="u456"))
    assert captured["user.id"] == "u456"
    assert captured["feature"] == "async-feature"


def test_traced_no_user_id_arg():
    """@traced with extract_user_id=True but no user_id arg should not crash."""
    captured = {}

    @traced(feature="no-uid")
    def my_func(text: str) -> str:
        captured.update(get_current_context())
        return text

    my_func(text="hi")
    assert captured.get("feature") == "no-uid"
    assert "user.id" not in captured
