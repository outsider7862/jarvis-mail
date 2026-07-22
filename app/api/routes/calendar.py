import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.rate_limit import limiter
from app.db.models import CalendarEvent, User
from app.db.session import get_db

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class CalendarEventOut(BaseModel):
    id: uuid.UUID
    email_analysis_id: uuid.UUID | None
    title: str
    description: str | None
    event_type: str
    start_at: datetime
    end_at: datetime | None
    all_day: bool
    status: str
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateEventRequest(BaseModel):
    title: str
    description: str | None = None
    event_type: Literal["meeting", "deadline", "order", "payment", "custom"]
    start_at: datetime
    end_at: datetime | None = None
    all_day: bool = False


class UpdateEventRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    status: Literal["pending", "confirmed", "rejected"] | None = None


async def _get_owned_event(event_id: uuid.UUID, current_user: User, db: AsyncSession) -> CalendarEvent:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == current_user.id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("", response_model=list[CalendarEventOut])
async def list_events(
    status: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(CalendarEvent).where(
        CalendarEvent.user_id == current_user.id,
        CalendarEvent.status != "rejected",  # never show rejected events
    )
    if status:
        query = query.where(CalendarEvent.status == status)
    if event_type:
        query = query.where(CalendarEvent.event_type == event_type)
    if from_date:
        query = query.where(CalendarEvent.start_at >= from_date)
    if to_date:
        query = query.where(CalendarEvent.start_at <= to_date)

    query = query.order_by(CalendarEvent.start_at.asc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/pending", response_model=list[CalendarEventOut])
async def pending_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-detected events waiting for user confirmation."""
    result = await db.execute(
        select(CalendarEvent)
        .where(
            CalendarEvent.user_id == current_user.id,
            CalendarEvent.status == "pending",
            CalendarEvent.source == "ai_detected",
        )
        .order_by(CalendarEvent.start_at.asc())
    )
    return result.scalars().all()


@router.post("", response_model=CalendarEventOut)
@limiter.limit("60/minute")
async def create_event(
    request: Request,
    payload: CreateEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = CalendarEvent(
        id=uuid.uuid4(),
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        event_type=payload.event_type,
        start_at=payload.start_at,
        end_at=payload.end_at,
        all_day=payload.all_day,
        status="confirmed",  # manually added events are auto-confirmed
        source="manual",
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.patch("/{event_id}", response_model=CalendarEventOut)
@limiter.limit("60/minute")
async def update_event(
    request: Request,
    event_id: uuid.UUID,
    payload: UpdateEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = await _get_owned_event(event_id, current_user, db)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(event, field, value)

    event.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(event)
    return event


@router.delete("/{event_id}")
@limiter.limit("60/minute")
async def delete_event(
    request: Request,
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = await _get_owned_event(event_id, current_user, db)
    await db.delete(event)
    await db.commit()
    return {"deleted": True}
