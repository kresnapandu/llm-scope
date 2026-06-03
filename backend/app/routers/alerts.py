"""
Alerts router for llm-scope backend.
Manage alert rules for cost spikes, hallucination, and error rates.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AlertRule

router = APIRouter()


class AlertRuleCreate(BaseModel):
    name: str
    type: str = Field(..., pattern="^(cost_spike|high_hallucination|error_rate)$")
    threshold: float
    window_minutes: int = 60
    webhook_url: Optional[str] = None
    slack_webhook: Optional[str] = None
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    threshold: Optional[float] = None
    window_minutes: Optional[int] = None
    webhook_url: Optional[str] = None
    slack_webhook: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_alerts(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """List all alert rules."""
    result = await db.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))
    rules = result.scalars().all()
    return {"rules": [r.to_dict() for r in rules]}


@router.post("", status_code=201)
async def create_alert(
    body: AlertRuleCreate,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Create a new alert rule."""
    rule = AlertRule(
        id=uuid.uuid4(),
        **body.model_dump(),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule.to_dict()


@router.get("/{rule_id}")
async def get_alert(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get a single alert rule."""
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == uuid.UUID(rule_id))
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return rule.to_dict()


@router.patch("/{rule_id}")
async def update_alert(
    rule_id: str,
    body: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update an existing alert rule."""
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == uuid.UUID(rule_id))
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    update_data = body.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(rule, k, v)

    await db.commit()
    await db.refresh(rule)
    return rule.to_dict()


@router.delete("/{rule_id}")
async def delete_alert(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete an alert rule."""
    result = await db.execute(
        delete(AlertRule).where(AlertRule.id == uuid.UUID(rule_id))
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await db.commit()
    return Response(status_code=204)
