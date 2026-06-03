"""
SQLAlchemy models for llm-scope backend.
Tables: traces, metrics_hourly, alert_rules
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Trace(Base):
    """Individual OpenTelemetry span stored from the collector."""

    __tablename__ = "traces"

    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: str = Column(String(32), nullable=False, index=True)
    span_id: str = Column(String(16), nullable=False)
    parent_span_id: Optional[str] = Column(String(16), nullable=True)
    name: str = Column(String(255), nullable=False)
    service_name: str = Column(String(100), nullable=False, index=True)
    start_time: datetime = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    end_time: Optional[datetime] = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms: Optional[int] = Column(Integer, nullable=True)
    status: str = Column(String(20), nullable=False, default="UNSET", index=True)
    attributes: Dict[str, Any] = Column(JSONB, nullable=False, default=dict)
    events: Optional[Dict[str, Any]] = Column(JSONB, nullable=True)
    created_at: datetime = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_traces_attributes_gin", "attributes", postgresql_using="gin"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "service_name": self.service_name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MetricsHourly(Base):
    """Pre-aggregated hourly metrics for fast dashboard queries."""

    __tablename__ = "metrics_hourly"

    hour: datetime = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    service_name: str = Column(String(100), primary_key=True, nullable=False)
    model: str = Column(String(100), primary_key=True, nullable=False)
    feature: Optional[str] = Column(String(100), nullable=True)
    user_id: Optional[str] = Column(String(255), nullable=True)
    total_calls: int = Column(Integer, nullable=False, default=0)
    total_input_tokens: int = Column(BigInteger, nullable=False, default=0)
    total_output_tokens: int = Column(BigInteger, nullable=False, default=0)
    total_cost_usd: float = Column(Numeric(10, 6), nullable=False, default=0.0)
    avg_latency_ms: int = Column(Integer, nullable=False, default=0)
    error_count: int = Column(Integer, nullable=False, default=0)
    hallucination_score_avg: Optional[float] = Column(Numeric(4, 3), nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hour": self.hour.isoformat() if self.hour else None,
            "service_name": self.service_name,
            "model": self.model,
            "feature": self.feature,
            "user_id": self.user_id,
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": float(self.total_cost_usd),
            "avg_latency_ms": self.avg_latency_ms,
            "error_count": self.error_count,
            "hallucination_score_avg": float(self.hallucination_score_avg)
            if self.hallucination_score_avg is not None
            else None,
        }


class AlertRule(Base):
    """User-configured alert rules for cost, hallucination, and error spikes."""

    __tablename__ = "alert_rules"

    id: uuid.UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: str = Column(String(255), nullable=False)
    type: str = Column(String(50), nullable=False)  # cost_spike, high_hallucination, error_rate
    threshold: float = Column(Numeric(10, 4), nullable=False)
    window_minutes: int = Column(Integer, nullable=False, default=60)
    webhook_url: Optional[str] = Column(String(500), nullable=True)
    slack_webhook: Optional[str] = Column(String(500), nullable=True)
    enabled: bool = Column(Boolean, nullable=False, default=True)
    created_at: datetime = Column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.type,
            "threshold": float(self.threshold),
            "window_minutes": self.window_minutes,
            "webhook_url": self.webhook_url,
            "slack_webhook": self.slack_webhook,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
