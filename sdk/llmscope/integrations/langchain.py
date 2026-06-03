"""
LangChain callback handler for llm-scope.
Implements BaseCallbackHandler to trace chains, LLMs, retrievers, and tools.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

import httpx
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Context, Span, Status, StatusCode

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.outputs import LLMResult
except ImportError:
    raise ImportError(
        "langchain-core is required for LLMScopeCallbackHandler. "
        "Install it with: pip install llmscope[langchain]"
    )

from ..config import _config, calculate_cost
from ..context import get_current_context

logger = logging.getLogger(__name__)


class LLMScopeCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that emits OpenTelemetry spans for all
    chain, LLM, retriever, and tool events.

    Usage:
        from llmscope.integrations.langchain import LLMScopeCallbackHandler

        handler = LLMScopeCallbackHandler(judge_faithfulness=True)
        chain.invoke({"input": "..."}, config={"callbacks": [handler]})
    """

    def __init__(
        self,
        judge_faithfulness: bool = False,
        raise_error: bool = False,
    ) -> None:
        super().__init__()
        self.judge_faithfulness = judge_faithfulness
        self.raise_error = raise_error

        # State maps keyed by run_id
        self._spans: Dict[UUID, Span] = {}
        self._contexts: Dict[UUID, Any] = {}
        self._retrieval_ctx: Dict[UUID, str] = {}
        self._start_times: Dict[UUID, float] = {}

    def _get_tracer(self) -> trace.Tracer:
        return _config.get("tracer") or trace.get_tracer("llmscope")

    def _get_parent_context(self, parent_run_id: Optional[UUID]) -> Any:
        if parent_run_id and parent_run_id in self._contexts:
            return self._contexts[parent_run_id]
        return otel_context.get_current()

    # ── Chain callbacks ───────────────────────────────────────────────────────

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tracer = self._get_tracer()
        parent_ctx = self._get_parent_context(parent_run_id)
        chain_name = (serialized.get("id") or ["chain"])[-1]

        span = tracer.start_span(f"chain.{chain_name}", context=parent_ctx)
        span.set_attribute("langchain.type", "chain")
        span.set_attribute("langchain.chain_name", chain_name)

        for k, v in get_current_context().items():
            span.set_attribute(k, str(v))

        self._spans[run_id] = span
        self._contexts[run_id] = trace.set_span_in_context(span)
        self._start_times[run_id] = time.time()

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            span.set_status(Status(StatusCode.OK))
            span.end()
        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    def on_chain_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()
        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    # ── LLM callbacks ─────────────────────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tracer = self._get_tracer()
        parent_ctx = self._get_parent_context(parent_run_id)

        model_name = (
            kwargs.get("invocation_params", {}).get("model_name")
            or kwargs.get("invocation_params", {}).get("model")
            or serialized.get("kwargs", {}).get("model_name")
            or "unknown"
        )

        span = tracer.start_span(f"llm.{model_name}", context=parent_ctx)
        span.set_attribute("gen_ai.request.model", model_name)
        span.set_attribute("langchain.type", "llm")

        if not _config.get("redact_prompts", False) and prompts:
            span.set_attribute("gen_ai.prompt", str(prompts[0])[:2000])

        for k, v in get_current_context().items():
            span.set_attribute(k, str(v))

        self._spans[run_id] = span
        self._contexts[run_id] = trace.set_span_in_context(span)
        self._start_times[run_id] = time.time()

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if not span:
            return

        start_time = self._start_times.pop(run_id, time.time())
        latency_ms = int((time.time() - start_time) * 1000)
        span.set_attribute("llmscope.latency_ms", latency_ms)

        # Extract token usage
        llm_output = response.llm_output or {}
        token_usage = llm_output.get("token_usage", {})
        input_tokens = token_usage.get("prompt_tokens", 0) or 0
        output_tokens = token_usage.get("completion_tokens", 0) or 0
        model = llm_output.get("model_name", "unknown")

        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("llmscope.cost_usd", calculate_cost(model, input_tokens, output_tokens))

        completion = ""
        if response.generations and response.generations[0]:
            gen = response.generations[0][0]
            completion = getattr(gen, "text", "") or ""
            if not _config.get("redact_completions", False):
                span.set_attribute("gen_ai.completion", completion[:2000])

        span.set_status(Status(StatusCode.OK))
        span.end()
        self._contexts.pop(run_id, None)

        # Optionally judge faithfulness
        if self.judge_faithfulness and random.random() < _config.get("judge_sample_rate", 0.1):
            span_id = format(span.get_span_context().span_id, "016x")
            context_docs = self._retrieval_ctx.get(parent_run_id or run_id, "")
            if context_docs:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(self._judge_async(str(run_id), completion, context_docs, span_id))
                    else:
                        loop.run_until_complete(self._judge_async(str(run_id), completion, context_docs, span_id))
                except Exception as e:
                    logger.warning(f"llm-scope: failed to schedule judge: {e}")

    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()
        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    # ── Retriever callbacks ────────────────────────────────────────────────────

    def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tracer = self._get_tracer()
        parent_ctx = self._get_parent_context(parent_run_id)
        retriever_type = (serialized.get("id") or ["retriever"])[-1]

        span = tracer.start_span(f"retrieval.{retriever_type}", context=parent_ctx)
        span.set_attribute("retrieval.query", query[:500])
        span.set_attribute("langchain.type", "retriever")

        self._spans[run_id] = span
        self._contexts[run_id] = trace.set_span_in_context(span)
        self._start_times[run_id] = time.time()

    def on_retriever_end(
        self,
        documents: List[Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            num_docs = len(documents)
            span.set_attribute("retrieval.num_docs", num_docs)

            # Top score if available
            if documents and hasattr(documents[0], "metadata"):
                score = documents[0].metadata.get("score") or documents[0].metadata.get("relevance_score")
                if score is not None:
                    span.set_attribute("retrieval.top_score", float(score))

            span.set_status(Status(StatusCode.OK))
            span.end()

        # Store formatted docs for judge (keyed by parent_run_id for LLM lookup)
        if documents:
            formatted = "\n\n".join(
                getattr(doc, "page_content", str(doc)) for doc in documents[:5]
            )
            key = parent_run_id or run_id
            self._retrieval_ctx[key] = formatted[:4000]

        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    def on_retriever_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()
        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    # ── Tool callbacks ─────────────────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tracer = self._get_tracer()
        parent_ctx = self._get_parent_context(parent_run_id)
        tool_name = serialized.get("name") or (serialized.get("id") or ["tool"])[-1]

        span = tracer.start_span(f"tool.{tool_name}", context=parent_ctx)
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.input", str(input_str)[:500])
        span.set_attribute("langchain.type", "tool")

        self._spans[run_id] = span
        self._contexts[run_id] = trace.set_span_in_context(span)
        self._start_times[run_id] = time.time()

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            span.set_attribute("tool.output", str(output)[:500])
            span.set_status(Status(StatusCode.OK))
            span.end()
        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(run_id, None)
        if span:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()
        self._contexts.pop(run_id, None)
        self._start_times.pop(run_id, None)

    # ── Judge ─────────────────────────────────────────────────────────────────

    async def _judge_async(
        self,
        chain_run_id: str,
        completion: str,
        context_docs: str,
        span_id: str,
    ) -> None:
        """
        Send completion to hallucination judge and update span attribute.
        Handles all network errors gracefully without raising.
        """
        judge_endpoint = _config.get("judge_endpoint", "http://localhost:8000/api/judge")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    judge_endpoint,
                    json={
                        "context": context_docs,
                        "completion": completion,
                        "span_id": span_id,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                score = data.get("score", 0.0)
                logger.debug(f"llm-scope judge: span={span_id} score={score:.3f}")
        except httpx.TimeoutException:
            logger.warning(f"llm-scope: judge timeout for span {span_id}")
        except httpx.HTTPError as e:
            logger.warning(f"llm-scope: judge HTTP error for span {span_id}: {e}")
        except Exception as e:
            logger.warning(f"llm-scope: judge unexpected error for span {span_id}: {e}")
