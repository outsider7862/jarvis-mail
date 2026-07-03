"""
Auth for Jarvis Mail's own users (the business owners logging into the dashboard
or Android app) — separate from Composio, which handles OAuth to *their clients'*
Gmail/Outlook.

The dashboard/Android app authenticates against Supabase directly and sends the
resulting Supabase session JWT as `Authorization: Bearer <token>` on every request
to this API. We verify that token here rather than trusting a client-supplied
user_id.

decode_and_verify() is a pure function (no DB, no FastAPI) so it can be unit
tested directly. get_current_user() wraps it with the DB lookup/creation and is
what routes actually depend on.
"""

import uuid

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.session import get_db


def decode_and_verify(token: str) -> dict:
    """
    Verifies a Supabase-issued JWT and returns its payload.
    Raises jwt.PyJWTError (or a subclass) on any invalid/expired/malformed token —
    callers are expected to catch this and translate it into an HTTP 401.
    """
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
    )


async def get_current_user(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_and_verify(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    supabase_user_id = payload.get("sub")
    email = payload.get("email")
    if not supabase_user_id or not email:
        raise HTTPException(status_code=401, detail="Token missing required claims")

    result = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
    user = result.scalar_one_or_none()

    if user is None:
        # First request from a newly-signed-up user — create their local row now
        # rather than requiring a separate signup-sync step.
        user = User(id=uuid.uuid4(), supabase_user_id=supabase_user_id, email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user
