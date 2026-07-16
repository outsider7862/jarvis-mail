import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import Lead, User
from app.db.session import get_db

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadOut(BaseModel):
    id: uuid.UUID
    email_analysis_id: uuid.UUID
    client_name: str | None
    client_company: str | None
    contact_email: str | None
    service_requested: str | None
    budget_mentioned: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadStatusUpdate(BaseModel):
    status: Literal["confirmed", "rejected"]


@router.get("", response_model=list[LeadOut])
async def list_leads(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Lead).where(Lead.user_id == current_user.id)
    if status:
        query = query.where(Lead.status == status)
    query = query.order_by(Lead.created_at.desc())

    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead_status(
    lead_id: uuid.UUID,
    update: LeadStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.user_id == current_user.id)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.status = update.status
    await db.commit()
    await db.refresh(lead)
    return lead
