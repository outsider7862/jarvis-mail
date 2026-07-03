import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lead
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

    model_config = {"from_attributes": True}


class LeadStatusUpdate(BaseModel):
    status: Literal["confirmed", "rejected"]


@router.get("", response_model=list[LeadOut])
async def list_leads(
    user_id: uuid.UUID,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Lead).where(Lead.user_id == user_id)
    if status:
        query = query.where(Lead.status == status)
    query = query.order_by(Lead.created_at.desc())

    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead_status(
    lead_id: uuid.UUID,
    update: LeadStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.status = update.status
    await db.commit()
    await db.refresh(lead)
    return lead
