import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.db.models import ConnectedAccount, User
from app.db.session import get_db
from app.services.composio_client import composio, create_gmail_trigger, delete_trigger, start_gmail_connection

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class ConnectedAccountOut(BaseModel):
    provider: str
    email_address: str
    active: bool

    model_config = {"from_attributes": True}


class ConnectResponse(BaseModel):
    redirect_url: str


class TriggerResponse(BaseModel):
    success: bool


def _extract_email(account, fallback: str) -> str:
    """
    Composio's connected_accounts.list() response has no stable top-level email
    field for OAuth2 connections (Gmail's account details live in state.val, which
    varies by auth flow and doesn't include it either). Best-effort pull from the
    legacy `data` blob some toolkits populate; otherwise fall back to the Jarvis
    Mail login email, since in this flow a business owner connects their own inbox.
    """
    data = account.data or {}
    for key in ("email", "email_address", "connectedAccountEmail"):
        value = data.get(key)
        if value:
            return value
    return fallback


@router.get("/connected", response_model=list[ConnectedAccountOut])
async def list_connected_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConnectedAccount).where(ConnectedAccount.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("/connect/gmail", response_model=ConnectResponse)
async def connect_gmail(current_user: User = Depends(get_current_user)):
    return_url = f"{settings.frontend_url}/dashboard/settings?connected=true"
    redirect_url = await run_in_threadpool(start_gmail_connection, str(current_user.id), return_url)
    return ConnectResponse(redirect_url=redirect_url)


@router.post("/trigger", response_model=TriggerResponse)
async def create_trigger(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Idempotent: a browser-back-button replay of the OAuth callback URL must not
    # create a second row (or a second live trigger) for the same connection.
    # Only active rows count — a disconnected account must be reconnectable.
    existing = await db.execute(
        select(ConnectedAccount).where(
            ConnectedAccount.user_id == current_user.id,
            ConnectedAccount.provider == "gmail",
            ConnectedAccount.active.is_(True),
        )
    )
    if existing.scalars().first() is not None:
        return TriggerResponse(success=True)

    accounts = await run_in_threadpool(
        composio.connected_accounts.list,
        user_ids=[str(current_user.id)],
        toolkit_slugs=["gmail"],
        statuses=["ACTIVE"],
        order_by="created_at",
        order_direction="desc",
    )
    if not accounts.items:
        raise HTTPException(status_code=404, detail="No active Gmail connection found for this user")
    account = accounts.items[0]

    trigger_id = await run_in_threadpool(create_gmail_trigger, str(current_user.id))

    connected_account = ConnectedAccount(
        id=uuid.uuid4(),
        user_id=current_user.id,
        provider="gmail",
        email_address=_extract_email(account, fallback=current_user.email),
        composio_connected_account_id=account.id,
        composio_trigger_id=trigger_id,
        active=True,
    )
    db.add(connected_account)
    await db.commit()

    return TriggerResponse(success=True)


@router.post("/disconnect/gmail", response_model=TriggerResponse)
async def disconnect_gmail(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConnectedAccount).where(
            ConnectedAccount.user_id == current_user.id,
            ConnectedAccount.provider == "gmail",
            ConnectedAccount.active.is_(True),
        )
    )
    accounts = result.scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="No connected Gmail account")

    for account in accounts:
        if account.composio_trigger_id:
            # Best effort — deactivating the local row already stops webhook
            # processing, so a Composio hiccup shouldn't block the disconnect.
            try:
                await run_in_threadpool(delete_trigger, account.composio_trigger_id)
            except Exception:  # noqa: BLE001
                pass
        account.active = False

    await db.commit()
    return TriggerResponse(success=True)
