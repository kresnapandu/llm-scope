"""
Metrics router for llm-scope backend.
Provides time-series cost, hallucination, and summary analytics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import MetricsHourly, Trace

router = APIRouter()


@router.get("/cost")
async def get_cost_metrics(
    granularity: str = Query("hourly", regex="^(hourly|daily)$"),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    group_by: Optional[str] = Query(None, regex="^(model|feature|user_id|service_name)?$"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Cost time-series data for the dashboard chart.

    Args:
        granularity: 'hourly' or 'daily' aggregation.
        start_time: Filter start (default: 24h ago).
        end_time: Filter end (default: now).
        group_by: Optional dimension to group by.

    Returns:
        List of time-series data points with total_cost_usd.
    """
    now = datetime.now(timezone.utc)
    if not start_time:
        start_time = now - timedelta(hours=24)
    if not end_time:
        end_time = now

    # Build group-by columns
    group_col = None
    if group_by and group_by in {"model", "feature", "service_name"}:
        group_col = getattr(MetricsHourly, group_by)
    elif group_by == "user_id":
        group_col = MetricsHourly.user_id

    if granularity == "hourly":
        time_bucket = MetricsHourly.hour
    else:
        time_bucket = func.date_trunc("day", MetricsHourly.hour)

    select_cols = [
        time_bucket.label("bucket"),
        func.sum(MetricsHourly.total_cost_usd).label("total_cost_usd"),
        func.sum(MetricsHourly.total_calls).label("total_calls"),
        func.sum(MetricsHourly.total_input_tokens).label("total_input_tokens"),
        func.sum(MetricsHourly.total_output_tokens).label("total_output_tokens"),
    ]
    group_cols = [time_bucket]

    if group_col is not None:
        select_cols.append(group_col.label("dimension"))
        group_cols.append(group_col)

    query = (
        select(*select_cols)
        .where(
            and_(
                MetricsHourly.hour >= start_time,
                MetricsHourly.hour <= end_time,
            )
        )
        .group_by(*group_cols)
        .order_by(time_bucket)
    )

    result = await db.execute(query)
    rows = result.mappings().all()

    return {
        "granularity": granularity,
        "group_by": group_by,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "data": [dict(r) for r in rows],
    }


@router.get("/hallucination")
async def get_hallucination_metrics(
    model: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Hallucination rate time-series, optionally filtered by model and feature.
    """
    now = datetime.now(timezone.utc)
    if not start_time:
        start_time = now - timedelta(hours=24)
    if not end_time:
        end_time = now

    conditions = [
        MetricsHourly.hour >= start_time,
        MetricsHourly.hour <= end_time,
        MetricsHourly.hallucination_score_avg.isnot(None),
    ]

    if model:
        conditions.append(MetricsHourly.model == model)
    if feature:
        conditions.append(MetricsHourly.feature == feature)

    query = (
        select(
            func.date_trunc("hour", MetricsHourly.hour).label("hour"),
            MetricsHourly.model,
            func.avg(MetricsHourly.hallucination_score_avg).label("avg_score"),
            func.sum(MetricsHourly.total_calls).label("total_calls"),
        )
        .where(and_(*conditions))
        .group_by(func.date_trunc("hour", MetricsHourly.hour), MetricsHourly.model)
        .order_by(func.date_trunc("hour", MetricsHourly.hour))
    )

    result = await db.execute(query)
    rows = result.mappings().all()

    return {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "data": [dict(r) for r in rows],
    }


@router.get("/summary")
async def get_summary(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Dashboard summary: totals for today, top models, top features.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's aggregates from metrics_hourly
    today_q = await db.execute(
        select(
            func.sum(MetricsHourly.total_cost_usd).label("total_cost_today"),
            func.sum(MetricsHourly.total_calls).label("total_calls_today"),
            func.avg(MetricsHourly.avg_latency_ms).label("avg_latency_ms"),
            func.avg(MetricsHourly.hallucination_score_avg).label("hallucination_rate_today"),
            func.sum(MetricsHourly.error_count).label("total_errors_today"),
        ).where(MetricsHourly.hour >= today_start)
    )
    today = today_q.mappings().one_or_none() or {}

    # Top models by cost
    top_models_q = await db.execute(
        select(
            MetricsHourly.model,
            func.sum(MetricsHourly.total_cost_usd).label("cost"),
            func.sum(MetricsHourly.total_calls).label("calls"),
        )
        .where(MetricsHourly.hour >= today_start)
        .group_by(MetricsHourly.model)
        .order_by(func.sum(MetricsHourly.total_cost_usd).desc())
        .limit(5)
    )
    top_models = [dict(r) for r in top_models_q.mappings().all()]

    # Top features by calls
    top_features_q = await db.execute(
        select(
            MetricsHourly.feature,
            func.sum(MetricsHourly.total_calls).label("calls"),
            func.sum(MetricsHourly.total_cost_usd).label("cost"),
        )
        .where(
            and_(
                MetricsHourly.hour >= today_start,
                MetricsHourly.feature.isnot(None),
            )
        )
        .group_by(MetricsHourly.feature)
        .order_by(func.sum(MetricsHourly.total_calls).desc())
        .limit(10)
    )
    top_features = [dict(r) for r in top_features_q.mappings().all()]

    return {
        "total_cost_today": float(today.get("total_cost_today") or 0),
        "total_calls_today": int(today.get("total_calls_today") or 0),
        "avg_latency_ms": int(today.get("avg_latency_ms") or 0),
        "hallucination_rate_today": float(today.get("hallucination_rate_today") or 0),
        "total_errors_today": int(today.get("total_errors_today") or 0),
        "top_models": top_models,
        "top_features": top_features,
    }


@router.get("/leaderboard")
async def get_leaderboard(
    metric: str = Query("cost", regex="^(cost|calls|hallucination)$"),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Leaderboard of top users/features by cost, calls, or hallucination score.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if metric == "cost":
        order_col = func.sum(MetricsHourly.total_cost_usd).desc()
        value_col = func.sum(MetricsHourly.total_cost_usd).label("value")
    elif metric == "calls":
        order_col = func.sum(MetricsHourly.total_calls).desc()
        value_col = func.sum(MetricsHourly.total_calls).label("value")
    else:  # hallucination
        order_col = func.avg(MetricsHourly.hallucination_score_avg).desc()
        value_col = func.avg(MetricsHourly.hallucination_score_avg).label("value")

    query = (
        select(
            MetricsHourly.user_id,
            MetricsHourly.feature,
            value_col,
        )
        .where(
            and_(
                MetricsHourly.hour >= today_start,
                MetricsHourly.user_id.isnot(None),
            )
        )
        .group_by(MetricsHourly.user_id, MetricsHourly.feature)
        .order_by(order_col)
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.mappings().all()

    return {
        "metric": metric,
        "leaderboard": [dict(r) for r in rows],
    }
