import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectedAccount, EmailAnalysis, Lead, RawEmail, UserProfile
from app.db.session import get_db
from app.services.composio_client import parse_webhook
from app.services.extraction import analyze_email, compute_should_notify
from app.services.prefilter import is_system_noise

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _extract_gmail_fields(data: dict) -> tuple[str, str, str]:
    sender = (
        data.get("sender")
        or data.get("from_email")
        or data.get("from")
        or ""
    )
    subject = (
        data.get("subject")
        or data.get("email_subject")
        or ""
    )
    body = (
        data.get("message_text")
        or data.get("body_plain")
        or data.get("body")
        or data.get("snippet")
        or ""
    )
    return sender, subject, body

@router.post("/composio")
async def composio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    
    parsed = parse_webhook(raw_body, dict(request.headers))
    if parsed is None:
        return {"status": "ignored", "reason": "not a trigger message event"}

    if parsed["trigger_slug"] != "GMAIL_NEW_GMAIL_MESSAGE":
        return {"status": "ignored", "reason": f"unhandled trigger: {parsed['trigger_slug']}"}

    composio_account_id = parsed["connected_account_id"]
    result = await db.execute(
        select(ConnectedAccount).where(
            ConnectedAccount.composio_connected_account_id == composio_account_id,
            ConnectedAccount.active.is_(True),
        )
    )
    connected_account = result.scalars().first()
    if connected_account is None:
        return {"status": "ignored", "reason": "unknown or inactive connected account"}

    data = parsed["data"]
    sender, subject, body = _extract_gmail_fields(data)

    raw_email = RawEmail(
        id=uuid.uuid4(),
        connected_account_id=connected_account.id,
        composio_message_id=data.get("message_id") or data.get("id"),
        sender=sender,
        subject=subject,
        body_text=body,
        raw_payload=data,
    )
    db.add(raw_email)
    await db.commit()
    await db.refresh(raw_email)

    if is_system_noise(sender, subject, body):
        raw_email.was_filtered = True
        await db.commit()
        return {"status": "filtered"}

    background_tasks.add_task(process_email, raw_email.id, connected_account.user_id)
    return {"status": "queued"}


async def process_email(raw_email_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(RawEmail).where(RawEmail.id == raw_email_id))
        raw_email = result.scalar_one_or_none()
        if raw_email is None:
            return

        # Personalize classification with the user's onboarding profile, if any.
        profile_result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile_row = profile_result.scalar_one_or_none()
        user_profile = {
            "display_name": profile_row.display_name,
            "work_type": profile_row.work_type,
            "email_use": profile_row.email_use,
            "preferred_tone": profile_row.preferred_tone,
            "custom_instructions": profile_row.custom_instructions,
        } if profile_row else None

        try:
            extraction = await analyze_email(
                subject=raw_email.subject or "",
                body_text=raw_email.body_text or "",
                sender=raw_email.sender or "",
                user_profile=user_profile,
            )
        except Exception as exc:  # noqa: BLE001
            import traceback
            print(f"Classification failed for raw_email {raw_email_id}: {exc}")
            print(traceback.format_exc())
            return

        raw_email.processed = True

        analysis = EmailAnalysis(
            id=uuid.uuid4(),
            user_id=user_id,
            raw_email_id=raw_email.id,
            category=extraction.category,
            priority=extraction.priority,
            summary=extraction.summary,
            action_required=extraction.action_required,
            deadline=extraction.deadline,
            is_business_lead=extraction.is_business_lead,
            is_invoice=extraction.is_invoice,
            is_meeting=extraction.is_meeting,
            is_customer_support=extraction.is_customer_support,
            is_newsletter=extraction.is_newsletter,
            is_spam=extraction.is_spam,
            is_phishing=extraction.is_phishing,
            confidence=extraction.confidence,
            should_notify=compute_should_notify(extraction),
        )
        db.add(analysis)
        await db.flush()

        if extraction.is_business_lead and extraction.lead_detail:
            lead = Lead(
                id=uuid.uuid4(),
                user_id=user_id,
                email_analysis_id=analysis.id,
                client_name=extraction.lead_detail.client_name,
                client_company=extraction.lead_detail.client_company,
                contact_email=extraction.lead_detail.contact_email,
                service_requested=extraction.lead_detail.service_requested,
                budget_mentioned=extraction.lead_detail.budget_mentioned,
                status="pending",
            )
            db.add(lead)

        await db.commit()