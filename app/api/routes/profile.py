import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.rate_limit import limiter
from app.db.models import User, UserProfile
from app.db.session import get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileOut(BaseModel):
    display_name: str | None
    work_type: str | None
    email_use: str | None
    preferred_tone: str | None
    custom_instructions: str | None
    onboarding_complete: bool

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    work_type: str | None = None
    email_use: str | None = None
    preferred_tone: str | None = None
    custom_instructions: str | None = None
    onboarding_complete: bool | None = None


@router.get("", response_model=ProfileOut)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        # No profile yet — return defaults so the dashboard sends the user to onboarding.
        return ProfileOut(
            display_name=None,
            work_type=None,
            email_use=None,
            preferred_tone=None,
            custom_instructions=None,
            onboarding_complete=False,
        )
    return profile


@router.patch("", response_model=ProfileOut)
@limiter.limit("30/minute")
async def update_profile(
    request: Request,
    update: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = UserProfile(
            id=uuid.uuid4(),
            user_id=current_user.id,
        )
        db.add(profile)

    for field, value in update.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(profile)
    return profile
