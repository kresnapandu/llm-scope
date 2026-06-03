"""
Traces router for llm-scope backend.
Provides CRUD and search over stored OTel spans.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Trace

router = APIRouter()


@router.get("")
async def list_traces(
    service_name: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    feature: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    search: Optional[str] = Query(None, description="Full-text search in attributes"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    List traces with optional filtering and pagination.

    Returns paginated list of spans matching the given filters.
    """
    conditions = []

    if service_name:
        conditions.append(Trace.service_name == service_name)
    if status:
        conditions.append(Trace.status == status.upper())
    if start_time:
        conditions.append(Trace.start_time >= start_time)
    if end_time:
        conditions.append(Trace.start_time <= end_time)

    # JSONB attribute filters
    if model:
        conditions.append(
            Trace.attributes["gen_ai.request.model"].astext == model
        )
    if feature:
        conditions.append(
            Trace.attributes["feature"].astext == feature
        )
    if user_id:
        conditions.append(
            Trace.attributes["user.id"].astext == user_id
        )
    if search:
        # Full-text search across attributes JSONB
        conditions.append(
            Trace.attributes.cast(text("text")).ilike(f"%{search}%")
        )

    query = select(Trace).order_by(Trace.start_time.desc())
    if conditions:
        query = query.where(and_(*conditions))

    # Count total
    count_query = select(func.count()).select_from(
        query.subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    traces = result.scalars().all()

    return {
        "traces": [t.to_dict() for t in traces],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{trace_id}")
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get a single trace with all its child spans in tree structure.
    """
    result = await db.execute(
        select(Trace).where(Trace.trace_id == trace_id).order_by(Trace.start_time)
    )
    spans = result.scalars().all()

    if not spans:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")

    # Build tree structure
    span_map: Dict[str, Dict] = {s.span_id: s.to_dict() for s in spans}
    roots = []

    for span in spans:
        span_dict = span_map[span.span_id]
        span_dict["children"] = []
        if span.parent_span_id and span.parent_span_id in span_map:
            parent = span_map[span.parent_span_id]
            parent.setdefault("children", []).append(span_dict)
        else:
            roots.append(span_dict)

    return {"trace_id": trace_id, "spans": roots, "total_spans": len(spans)}


@router.get("/{trace_id}/spans")
async def get_trace_spans(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get all spans in a trace, ordered by start_time.
    """
    result = await db.execute(
        select(Trace).where(Trace.trace_id == trace_id).order_by(Trace.start_time)
    )
    spans = result.scalars().all()

    if not spans:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")

    return {"trace_id": trace_id, "spans": [s.to_dict() for s in spans]}


@router.delete("/{trace_id}")
async def delete_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Delete a trace and all its child spans.
    Useful for data retention management.
    """
    result = await db.execute(
        delete(Trace).where(Trace.trace_id == trace_id)
    )
    deleted = result.rowcount

    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")

    await db.commit()
    return {"deleted": deleted, "trace_id": trace_id}
