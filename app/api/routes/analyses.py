import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import EmailAnalysis, RawEmail, User
from app.db.session import get_db

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


class EmailAnalysisOut(BaseModel):
    id: uuid.UUID
    raw_email_id: uuid.UUID
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
    received_at: datetime | None = None

    model_config = {"from_attributes": True}


class AttachmentInfo(BaseModel):
    name: str | None
    mime_type: str | None
    size: int | None


class RawEmailOut(BaseModel):
    sender: str | None
    subject: str | None
    body_text: str | None
    received_at: datetime | None
    thread_id: str | None
    attachments: list[AttachmentInfo]

    model_config = {"from_attributes": True}


class AnalysisStatusUpdate(BaseModel):
    status: Literal["read", "actioned", "dismissed"]


class MorningBrief(BaseModel):
    business_leads: int
    invoices: int
    meetings_today: int
    follow_ups: int
    possible_phishing: int
    estimated_minutes: int


async def _get_owned_analysis(analysis_id: uuid.UUID, current_user: User, db: AsyncSession) -> EmailAnalysis:
    result = await db.execute(
        select(EmailAnalysis).where(EmailAnalysis.id == analysis_id, EmailAnalysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


@router.get("", response_model=list[EmailAnalysisOut])
async def list_analyses(
    category: str | None = None,
    priority: str | None = None,
    sender: str | None = Query(default=None, description="Filter by sender substring"),
    keyword: str | None = Query(default=None, description="Filter by keyword in summary"),
    is_business_lead: bool | None = Query(default=None),
    is_invoice: bool | None = Query(default=None),
    is_meeting: bool | None = Query(default=None),
    is_customer_support: bool | None = Query(default=None),
    is_newsletter: bool | None = Query(default=None),
    is_spam: bool | None = Query(default=None),
    is_phishing: bool | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(EmailAnalysis, RawEmail.received_at)
        .join(RawEmail, RawEmail.id == EmailAnalysis.raw_email_id)
        .where(EmailAnalysis.user_id == current_user.id)
    )

    # Primary category filter (exact match — kept for backward compat, and it's
    # still the only way to reach "personal" since that has no boolean flag).
    if category:
        query = query.where(EmailAnalysis.category == category)

    # Flag-based filters — these catch emails regardless of primary category, so
    # e.g. a business_lead email that's also is_meeting shows up under Meetings too.
    if is_business_lead is not None:
        query = query.where(EmailAnalysis.is_business_lead.is_(is_business_lead))
    if is_invoice is not None:
        query = query.where(EmailAnalysis.is_invoice.is_(is_invoice))
    if is_meeting is not None:
        query = query.where(EmailAnalysis.is_meeting.is_(is_meeting))
    if is_customer_support is not None:
        query = query.where(EmailAnalysis.is_customer_support.is_(is_customer_support))
    if is_newsletter is not None:
        query = query.where(EmailAnalysis.is_newsletter.is_(is_newsletter))
    if is_spam is not None:
        query = query.where(EmailAnalysis.is_spam.is_(is_spam))
    if is_phishing is not None:
        query = query.where(EmailAnalysis.is_phishing.is_(is_phishing))

    if priority:
        query = query.where(EmailAnalysis.priority == priority)
    if keyword:
        query = query.where(EmailAnalysis.summary.ilike(f"%{keyword}%"))
    if sender:
        query = query.where(RawEmail.sender.ilike(f"%{sender}%"))

    query = query.order_by(EmailAnalysis.created_at.desc())
    result = await db.execute(query)
    return [
        EmailAnalysisOut.model_validate(analysis).model_copy(update={"received_at": received_at})
        for analysis, received_at in result.all()
    ]


@router.patch("/{analysis_id}", response_model=EmailAnalysisOut)
async def update_analysis_status(
    analysis_id: uuid.UUID,
    update: AnalysisStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis = await _get_owned_analysis(analysis_id, current_user, db)
    analysis.status = update.status
    await db.commit()
    await db.refresh(analysis)
    return analysis


@router.get("/morning-brief", response_model=MorningBrief)
async def morning_brief(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    query = select(
        func.count().filter(EmailAnalysis.is_business_lead.is_(True)).label("business_leads"),
        func.count().filter(EmailAnalysis.is_invoice.is_(True)).label("invoices"),
        func.count().filter(EmailAnalysis.is_meeting.is_(True)).label("meetings_today"),
        func.count().filter(EmailAnalysis.is_phishing.is_(True)).label("possible_phishing"),
        func.count()
        .filter(EmailAnalysis.action_required.is_not(None) & EmailAnalysis.status.in_(["new", "read"]))
        .label("follow_ups"),
    ).where(EmailAnalysis.user_id == current_user.id, EmailAnalysis.created_at >= since)

    row = (await db.execute(query)).one()

    estimated_minutes = row.follow_ups * 2 + row.business_leads * 3 + row.invoices + row.meetings_today

    return MorningBrief(
        business_leads=row.business_leads,
        invoices=row.invoices,
        meetings_today=row.meetings_today,
        follow_ups=row.follow_ups,
        possible_phishing=row.possible_phishing,
        estimated_minutes=estimated_minutes,
    )


@router.get("/notifications/pending", response_model=list[EmailAnalysisOut])
async def pending_notifications(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = (
        select(EmailAnalysis, RawEmail.received_at)
        .join(RawEmail, RawEmail.id == EmailAnalysis.raw_email_id)
        .where(
            EmailAnalysis.user_id == current_user.id,
            EmailAnalysis.should_notify.is_(True),
            EmailAnalysis.notified_at.is_(None),
        )
        .order_by(EmailAnalysis.created_at.desc())
    )
    result = await db.execute(query)
    return [
        EmailAnalysisOut.model_validate(analysis).model_copy(update={"received_at": received_at})
        for analysis, received_at in result.all()
    ]


@router.post("/notifications/{analysis_id}/mark-notified", response_model=EmailAnalysisOut)
async def mark_notified(
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis = await _get_owned_analysis(analysis_id, current_user, db)
    analysis.notified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(analysis)
    return analysis


@router.get("/{analysis_id}/raw-email", response_model=RawEmailOut)
async def get_raw_email(
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis = await _get_owned_analysis(analysis_id, current_user, db)
    result = await db.execute(
        select(RawEmail).where(RawEmail.id == analysis.raw_email_id)
    )
    raw = result.scalar_one_or_none()
    if raw is None:
        raise HTTPException(status_code=404, detail="Raw email not found")

    # Parse attachments from the stored Composio payload
    attachment_list = raw.raw_payload.get("attachment_list", []) if raw.raw_payload else []
    attachments = [
        {
            "name": a.get("name") or a.get("filename"),
            "mime_type": a.get("mimeType") or a.get("mime_type"),
            "size": a.get("size"),
        }
        for a in attachment_list
        if a  # skip nulls
    ]

    # thread_id for deep-linking back to Gmail
    thread_id = raw.raw_payload.get("thread_id") if raw.raw_payload else None

    return {
        "sender": raw.sender,
        "subject": raw.subject,
        "body_text": raw.body_text,
        "received_at": raw.received_at,
        "thread_id": thread_id,
        "attachments": attachments,
    }