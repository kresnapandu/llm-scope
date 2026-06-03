"""
OTel OTLP collector receiver for llm-scope.
Listens on gRPC port 4317, parses spans, and inserts into the database.
Also triggers alert checks and aggregates metrics hourly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

# Try to import gRPC OTel receiver components
try:
    from grpc import aio as grpc_aio
    from opentelemetry.proto.collector.trace.v1 import (
        trace_service_pb2,
        trace_service_pb2_grpc,
    )
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    logger.warning("gRPC not available — OTLP collector will not start")


def _ns_to_datetime(ns: int) -> datetime:
    """Convert nanoseconds epoch to UTC datetime."""
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _span_status_code(code: int) -> str:
    """Map OTel StatusCode int to string."""
    return {0: "UNSET", 1: "OK", 2: "ERROR"}.get(code, "UNSET")


def _parse_attributes(attrs) -> Dict[str, Any]:
    """Convert OTel AnyValue attributes to a plain dict."""
    result: Dict[str, Any] = {}
    for kv in attrs:
        key = kv.key
        val = kv.value
        kind = val.WhichOneof("value")
        if kind == "string_value":
            result[key] = val.string_value
        elif kind == "int_value":
            result[key] = val.int_value
        elif kind == "double_value":
            result[key] = val.double_value
        elif kind == "bool_value":
            result[key] = val.bool_value
        elif kind == "bytes_value":
            result[key] = val.bytes_value.hex()
        else:
            result[key] = str(val)
    return result


class TraceServiceServicer(
    trace_service_pb2_grpc.TraceServiceServicer if GRPC_AVAILABLE else object
):
    """
    gRPC servicer that receives OTLP spans and inserts them into the database.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def Export(self, request, context):
        """Handle incoming OTLP export request."""
        from .models import Trace

        spans_to_insert: List[Trace] = []

        for resource_spans in request.resource_spans:
            # Extract service.name from resource attributes
            resource_attrs = _parse_attributes(resource_spans.resource.attributes)
            service_name = resource_attrs.get("service.name", "unknown")

            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    trace_id = span.trace_id.hex()
                    span_id = span.span_id.hex()
                    parent_span_id = span.parent_span_id.hex() if span.parent_span_id else None
                    if parent_span_id == "0" * 16:
                        parent_span_id = None

                    attributes = _parse_attributes(span.attributes)
                    attributes.update(resource_attrs)

                    start_time = _ns_to_datetime(span.start_time_unix_nano)
                    end_time = _ns_to_datetime(span.end_time_unix_nano)
                    duration_ms = int((span.end_time_unix_nano - span.start_time_unix_nano) / 1e6)

                    events = [
                        {
                            "name": e.name,
                            "time": _ns_to_datetime(e.time_unix_nano).isoformat(),
                            "attributes": _parse_attributes(e.attributes),
                        }
                        for e in span.events
                    ]

                    trace_record = Trace(
                        id=uuid.uuid4(),
                        trace_id=trace_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        name=span.name,
                        service_name=service_name,
                        start_time=start_time,
                        end_time=end_time,
                        duration_ms=duration_ms,
                        status=_span_status_code(span.status.code),
                        attributes=attributes,
                        events=events or None,
                    )
                    spans_to_insert.append(trace_record)

        if spans_to_insert:
            async with self._session_factory() as session:
                session.add_all(spans_to_insert)
                await session.commit()

            logger.debug(f"Inserted {len(spans_to_insert)} spans")
            # Trigger alert check asynchronously
            asyncio.create_task(check_alerts(spans_to_insert, self._session_factory))

        return trace_service_pb2.ExportTraceServiceResponse()


async def check_alerts(spans: List[Any], session_factory) -> None:
    """
    Check alert rules against recently inserted spans.
    Send notifications if thresholds are exceeded.
    """
    try:
        from .models import AlertRule
        from sqlalchemy import select, and_, func
        from datetime import timedelta
        import httpx

        async with session_factory() as session:
            result = await session.execute(
                select(AlertRule).where(AlertRule.enabled == True)
            )
            rules = result.scalars().all()

        for rule in rules:
            if rule.type == "error_rate":
                error_spans = [s for s in spans if s.status == "ERROR"]
                if len(error_spans) / max(len(spans), 1) > float(rule.threshold):
                    await _send_alert(rule, f"Error rate exceeded threshold {rule.threshold:.1%}")

            elif rule.type == "cost_spike":
                total_cost = sum(
                    float(s.attributes.get("llmscope.cost_usd", 0)) for s in spans
                )
                if total_cost > float(rule.threshold):
                    await _send_alert(rule, f"Cost spike: ${total_cost:.4f} in batch (threshold: ${rule.threshold})")

            elif rule.type == "high_hallucination":
                scored_spans = [
                    s for s in spans
                    if "llmscope.hallucination_score" in s.attributes
                ]
                if scored_spans:
                    avg_score = sum(
                        float(s.attributes["llmscope.hallucination_score"]) for s in scored_spans
                    ) / len(scored_spans)
                    if avg_score > float(rule.threshold):
                        await _send_alert(
                            rule,
                            f"Hallucination score {avg_score:.3f} exceeded threshold {rule.threshold}",
                        )

    except Exception as e:
        logger.warning(f"Alert check failed: {e}")


async def _send_alert(rule: Any, message: str) -> None:
    """Send alert notification via webhook or Slack."""
    import httpx

    payload = {
        "alert": rule.name,
        "type": rule.type,
        "message": message,
        "threshold": float(rule.threshold),
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if rule.slack_webhook:
                await client.post(
                    rule.slack_webhook,
                    json={"text": f":warning: *{rule.name}*: {message}"},
                )
            if rule.webhook_url:
                await client.post(rule.webhook_url, json=payload)
    except Exception as e:
        logger.warning(f"Failed to send alert '{rule.name}': {e}")


async def aggregate_metrics_hourly(session_factory) -> None:
    """
    Aggregate trace data into metrics_hourly table.
    Called periodically by APScheduler.
    """
    from .models import MetricsHourly, Trace
    from sqlalchemy import select, func, and_, text
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    # Aggregate last 2 hours to cover any late-arriving spans
    since = now - timedelta(hours=2)

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(
                    func.date_trunc("hour", Trace.start_time).label("hour"),
                    Trace.service_name,
                    Trace.attributes["gen_ai.request.model"].astext.label("model"),
                    Trace.attributes["feature"].astext.label("feature"),
                    Trace.attributes["user.id"].astext.label("user_id"),
                    func.count().label("total_calls"),
                    func.sum(
                        func.cast(
                            Trace.attributes["gen_ai.usage.input_tokens"].astext,
                            text("BIGINT"),
                        )
                    ).label("total_input_tokens"),
                    func.sum(
                        func.cast(
                            Trace.attributes["gen_ai.usage.output_tokens"].astext,
                            text("BIGINT"),
                        )
                    ).label("total_output_tokens"),
                    func.sum(
                        func.cast(
                            Trace.attributes["llmscope.cost_usd"].astext,
                            text("FLOAT"),
                        )
                    ).label("total_cost_usd"),
                    func.avg(
                        func.cast(
                            Trace.attributes["llmscope.latency_ms"].astext,
                            text("FLOAT"),
                        )
                    ).label("avg_latency_ms"),
                    func.sum(
                        func.cast(Trace.status == "ERROR", text("INT"))
                    ).label("error_count"),
                    func.avg(
                        func.cast(
                            Trace.attributes["llmscope.hallucination_score"].astext,
                            text("FLOAT"),
                        )
                    ).label("hallucination_score_avg"),
                )
                .where(
                    and_(
                        Trace.start_time >= since,
                        Trace.attributes["gen_ai.request.model"].astext.isnot(None),
                    )
                )
                .group_by(
                    func.date_trunc("hour", Trace.start_time),
                    Trace.service_name,
                    Trace.attributes["gen_ai.request.model"].astext,
                    Trace.attributes["feature"].astext,
                    Trace.attributes["user.id"].astext,
                )
            )

            rows = result.mappings().all()
            for row in rows:
                metric = MetricsHourly(
                    hour=row["hour"],
                    service_name=row["service_name"],
                    model=row["model"] or "unknown",
                    feature=row["feature"],
                    user_id=row["user_id"],
                    total_calls=int(row["total_calls"] or 0),
                    total_input_tokens=int(row["total_input_tokens"] or 0),
                    total_output_tokens=int(row["total_output_tokens"] or 0),
                    total_cost_usd=float(row["total_cost_usd"] or 0),
                    avg_latency_ms=int(row["avg_latency_ms"] or 0),
                    error_count=int(row["error_count"] or 0),
                    hallucination_score_avg=float(row["hallucination_score_avg"])
                    if row["hallucination_score_avg"] is not None
                    else None,
                )
                await session.merge(metric)

            await session.commit()
            logger.info(f"Aggregated {len(rows)} hourly metric rows")

    except Exception as e:
        logger.error(f"Metrics aggregation failed: {e}")


async def start_grpc_server(session_factory, port: int = 4317) -> None:
    """Start the gRPC OTLP receiver."""
    if not GRPC_AVAILABLE:
        logger.warning("gRPC not available, OTLP collector not started")
        return

    server = grpc_aio.server()
    servicer = TraceServiceServicer(session_factory)
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    logger.info(f"OTLP gRPC collector started on port {port}")

    # Setup hourly aggregation scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        aggregate_metrics_hourly,
        "interval",
        hours=1,
        args=[session_factory],
        id="metrics_aggregation",
    )
    scheduler.start()

    await server.wait_for_termination()
