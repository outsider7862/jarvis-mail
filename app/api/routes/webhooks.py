import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectedAccount, EmailAnalysis, Lead, RawEmail
from app.db.session import get_db
from app.services.composio_client import verify_webhook_signature
from app.services.extraction import analyze_email, compute_should_notify
from app.services.prefilter import is_system_noise

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/composio")
async def composio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()

    signature = request.headers.get("webhook-signature", "")
    webhook_id = request.headers.get("webhook-id", "")
    timestamp = request.headers.get("webhook-timestamp", "")

    if not verify_webhook_signature(
        signature_header=signature, webhook_id=webhook_id, timestamp=timestamp, raw_body=raw_body
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = json.loads(raw_body)
    payload = event.get("payload", {})
    connected_account_composio_id = event.get("connectedAccountId") or payload.get("connectedAccountId")

    result = await db.execute(
        select(ConnectedAccount).where(
            ConnectedAccount.composio_connected_account_id == connected_account_composio_id
        )
    )
    connected_account = result.scalar_one_or_none()
    if connected_account is None:
        # Event for an account we don't recognize — ack anyway so Composio doesn't retry forever,
        # but don't process it.
        return {"status": "ignored", "reason": "unknown connected account"}

    sender = payload.get("sender") or payload.get("from", "")
    subject = payload.get("subject", "")
    body_text = payload.get("message_text") or payload.get("body", "")

    raw_email = RawEmail(
        id=uuid.uuid4(),
        connected_account_id=connected_account.id,
        composio_message_id=payload.get("id"),
        sender=sender,
        subject=subject,
        body_text=body_text,
        raw_payload=event,
    )
    db.add(raw_email)
    await db.commit()
    await db.refresh(raw_email)

    if is_system_noise(sender, subject, body_text):
        raw_email.was_filtered = True
        await db.commit()
        return {"status": "filtered"}

    background_tasks.add_task(process_email, raw_email.id, connected_account.user_id)
    return {"status": "queued"}


async def process_email(raw_email_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """
    Runs the LLM classification and stores the result. Executed as a FastAPI
    background task so the webhook responds to Composio immediately.

    For pilot-scale volume this is fine. Once you have more than a handful of
    active users, move this to a real queue (Celery/arq) so a slow OpenAI call
    can't back up webhook processing or get lost if the process restarts mid-request.
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(RawEmail).where(RawEmail.id == raw_email_id))
        raw_email = result.scalar_one_or_none()
        if raw_email is None:
            return

        try:
            extraction = await analyze_email(
                subject=raw_email.subject or "",
                body_text=raw_email.body_text or "",
                sender=raw_email.sender or "",
            )
        except Exception as exc:  # noqa: BLE001 — log and move on, don't crash the background task
            print(f"Classification failed for raw_email {raw_email_id}: {exc}")
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
        await db.flush()  # get analysis.id before building the Lead FK

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
