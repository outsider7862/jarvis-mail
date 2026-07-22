"""
Extracts calendar events from classified emails.
Called after classification in process_email() in webhooks.py.
Only creates events for emails where there's a meaningful date/time to extract.

Events start as 'pending' — the user confirms them before they land on the
calendar, so a mis-parsed date never silently pollutes it.
"""

import uuid
from datetime import datetime, timedelta, timezone

from dateutil import parser as dateutil_parser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CalendarEvent, EmailAnalysis


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = dateutil_parser.parse(date_str, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError, TypeError):
        # deadline is free-text from the model ("within 24 hours", "ASAP") and
        # often isn't a parseable date — that's expected, just skip it.
        return None


def _should_extract_event(analysis: EmailAnalysis) -> bool:
    """Only extract if there's a meaningful event to put on the calendar."""
    if not analysis.deadline:
        return False
    if analysis.is_spam or analysis.is_newsletter:
        return False
    if analysis.is_otp:  # OTPs expire in minutes, not calendar-worthy
        return False
    return (
        analysis.is_meeting
        or analysis.is_invoice
        or analysis.is_order
        or analysis.is_business_lead
        or analysis.deadline is not None
    )


def _build_event(analysis: EmailAnalysis, user_id: uuid.UUID) -> CalendarEvent | None:
    start_at = _parse_date(analysis.deadline)
    if not start_at:
        return None

    if analysis.is_meeting:
        event_type = "meeting"
        title = f"Meeting: {analysis.summary[:60]}"
        end_at = start_at + timedelta(hours=1)  # default 1 hour
    elif analysis.is_invoice:
        event_type = "payment"
        title = f"Payment due: {analysis.summary[:60]}"
        end_at = None
    elif analysis.is_order:
        event_type = "order"
        title = f"Delivery/Order: {analysis.summary[:60]}"
        end_at = None
    elif analysis.is_business_lead:
        event_type = "deadline"
        title = f"Lead deadline: {analysis.summary[:60]}"
        end_at = None
    else:
        event_type = "deadline"
        title = f"Deadline: {analysis.summary[:60]}"
        end_at = None

    return CalendarEvent(
        id=uuid.uuid4(),
        user_id=user_id,
        email_analysis_id=analysis.id,
        title=title,
        description=analysis.action_required,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        all_day=(analysis.is_invoice or analysis.is_order),
        status="pending",  # user must confirm before it appears on the calendar
        source="ai_detected",
    )


async def maybe_create_calendar_event(
    analysis: EmailAnalysis,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Creates a pending calendar event from a classified email if applicable.
    Idempotent — won't create duplicates for the same email.
    """
    existing = await db.execute(
        select(CalendarEvent).where(CalendarEvent.email_analysis_id == analysis.id)
    )
    if existing.scalar_one_or_none():
        return

    if not _should_extract_event(analysis):
        return

    event = _build_event(analysis, user_id)
    if event:
        db.add(event)
