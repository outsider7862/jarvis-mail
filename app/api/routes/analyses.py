import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmailAnalysis, RawEmail
from app.db.session import get_db

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


class EmailAnalysisOut(BaseModel):
    id: uuid.UUID
    category: str
    priority: str
    summary: str
    action_required: str | None
    deadline: str | None
    is_business_lead: bool
    is_invoice: bool
    is_meeting: bool
    is_customer_support: bool
    is_newsletter: bool
    is_spam: bool
    is_phishing: bool
    confidence: float
    status: str
    should_notify: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisStatusUpdate(BaseModel):
    status: Literal["read", "actioned", "dismissed"]


class MorningBrief(BaseModel):
    business_leads: int
    invoices: int
    meetings_today: int
    follow_ups: int  # unresolved items with an action_required, not yet actioned/dismissed
    possible_phishing: int
    estimated_minutes: int


@router.get("", response_model=list[EmailAnalysisOut])
async def list_analyses(
    user_id: uuid.UUID,
    category: str | None = None,
    priority: str | None = None,
    sender: str | None = Query(default=None, description="Filter by sender substring"),
    keyword: str | None = Query(default=None, description="Filter by keyword in summary"),
    db: AsyncSession = Depends(get_db),
):
    query = select(EmailAnalysis).where(EmailAnalysis.user_id == user_id)

    if category:
        query = query.where(EmailAnalysis.category == category)
    if priority:
        query = query.where(EmailAnalysis.priority == priority)
    if keyword:
        query = query.where(EmailAnalysis.summary.ilike(f"%{keyword}%"))
    if sender:
        # Sender lives on RawEmail, so join when this filter is used.
        query = query.join(RawEmail, RawEmail.id == EmailAnalysis.raw_email_id).where(
            RawEmail.sender.ilike(f"%{sender}%")
        )

    query = query.order_by(EmailAnalysis.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/{analysis_id}", response_model=EmailAnalysisOut)
async def update_analysis_status(
    analysis_id: uuid.UUID,
    update: AnalysisStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EmailAnalysis).where(EmailAnalysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    analysis.status = update.status
    await db.commit()
    await db.refresh(analysis)
    return analysis


@router.get("/morning-brief", response_model=MorningBrief)
async def morning_brief(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Aggregates today's classified emails into the "Good Morning" summary from the
    spec. "Today" is treated as the last 24 hours in UTC for now — swap for the
    user's actual timezone once accounts store one.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    base = select(func.count()).select_from(EmailAnalysis).where(
        EmailAnalysis.user_id == user_id, EmailAnalysis.created_at >= since
    )

    async def count(extra_filter) -> int:
        result = await db.execute(base.where(extra_filter))
        return result.scalar_one()

    business_leads = await count(EmailAnalysis.is_business_lead.is_(True))
    invoices = await count(EmailAnalysis.is_invoice.is_(True))
    meetings_today = await count(EmailAnalysis.is_meeting.is_(True))
    possible_phishing = await count(EmailAnalysis.is_phishing.is_(True))
    follow_ups = await count(
        EmailAnalysis.action_required.is_not(None) & EmailAnalysis.status.in_(["new", "read"])
    )

    # Rough, transparent heuristic — 2 min per follow-up, 3 min per lead, 1 min per
    # invoice/meeting glance. Tune once you have real usage data instead of guessing further.
    estimated_minutes = follow_ups * 2 + business_leads * 3 + invoices + meetings_today

    return MorningBrief(
        business_leads=business_leads,
        invoices=invoices,
        meetings_today=meetings_today,
        follow_ups=follow_ups,
        possible_phishing=possible_phishing,
        estimated_minutes=estimated_minutes,
    )


@router.get("/notifications/pending", response_model=list[EmailAnalysisOut])
async def pending_notifications(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Returns analyses flagged should_notify=True that haven't been delivered yet.
    Intended to be polled by the web dashboard and, later, the Android app — or
    swapped for a push mechanism (e.g. FCM for Android) once that's wired up.
    Caller is responsible for marking them delivered via the mark-notified endpoint.
    """
    query = (
        select(EmailAnalysis)
        .where(
            EmailAnalysis.user_id == user_id,
            EmailAnalysis.should_notify.is_(True),
            EmailAnalysis.notified_at.is_(None),
        )
        .order_by(EmailAnalysis.created_at.desc())
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/notifications/{analysis_id}/mark-notified", response_model=EmailAnalysisOut)
async def mark_notified(analysis_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EmailAnalysis).where(EmailAnalysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    analysis.notified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(analysis)
    return analysis
