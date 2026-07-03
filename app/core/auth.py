"""
Auth for Jarvis Mail's own users (the business owners logging into the dashboard
or Android app) — separate from Composio, which handles OAuth to *their clients'*
Gmail/Outlook.

Supabase projects created since mid-2025 default to asymmetric JWT signing
(ES256): Supabase Auth signs session tokens with a private key it never
exposes, and publishes the matching public key at
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. We verify tokens against that
public key locally — no shared secret needs to live in our environment at all,
and key rotation on Supabase's side doesn't require us to redeploy anything.

decode_and_verify() takes an optional jwks_client so tests can inject a fake one
signing with a locally-generated keypair, instead of hitting the network.
get_current_user() is the FastAPI dependency routes actually use.
"""

import uuid

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.session import get_db

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        # PyJWKClient caches fetched keys in memory and only re-fetches when it
        # sees a kid it doesn't recognize (e.g. after a key rotation), so this
        # doesn't mean a network round trip on every request.
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def decode_and_verify(token: str, jwks_client: PyJWKClient | None = None) -> dict:
    """
    Verifies a Supabase-issued JWT against its public signing key and returns
    the payload. Raises jwt.PyJWTError (or a subclass) on any invalid/expired/
    malformed token — callers are expected to catch this and translate it into
    an HTTP 401.
    """
    client = jwks_client or _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
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
