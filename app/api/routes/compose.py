"""
JARVIS free-form email composer.

Writes a brand-new email from a plain-language prompt ("what kind of email do
you want written?"). Like the reply flow, it NEVER sends — it returns text the
user reviews, edits, copies, or opens in Gmail to send themselves.

The model helpers (_complete_json / _sanitize_history / _get_user_style_context)
are shared with the reply flow, so composing learns from the same style history.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.reply import (
    _complete_json,
    _get_user_style_context,
    _sanitize_history,
)
from app.core.auth import get_current_user
from app.core.rate_limit import limiter
from app.db.models import User, UserProfile
from app.db.session import get_db

router = APIRouter(prefix="/api/compose", tags=["compose"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ComposeRequest(BaseModel):
    prompt: str
    recipient: str | None = None
    conversation_history: list[dict] | None = None  # for re-prompt / clarification loop


class ComposeRewriteRequest(BaseModel):
    current_draft: str
    current_subject: str | None = None
    rewrite_instruction: str  # e.g. "make it shorter", "warmer tone", "add a deadline"
    conversation_history: list[dict] | None = None


class ComposeResponse(BaseModel):
    subject: str
    body: str
    clarifying_question: str | None  # set when JARVIS needs more info before drafting


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_profile(user_id, db: AsyncSession) -> UserProfile | None:
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _profile_block(profile: UserProfile | None) -> str:
    return (
        f"- Name: {profile.display_name if profile else 'the user'}\n"
        f"- Work type: {profile.work_type if profile else 'professional'}\n"
        f"- Preferred tone: {profile.preferred_tone if profile else 'professional'}\n"
        f"- Email use: {profile.email_use if profile else 'business communication'}\n"
        f"- Custom instructions: {profile.custom_instructions if profile else 'none'}"
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/draft", response_model=ComposeResponse)
@limiter.limit("20/minute")
async def compose_draft(
    request: Request,
    payload: ComposeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile(current_user.id, db)
    style_context = await _get_user_style_context(current_user.id, db)

    system_prompt = f"""You are JARVIS, an AI email assistant.
You write brand-new emails from scratch based on what the user asks for.
You NEVER send emails — the user always reviews and sends themselves.

User profile:
{_profile_block(profile)}
{style_context}

Recipient (if provided): {payload.recipient or 'not specified'}

Rules:
- If the request is too vague to write a useful email (unclear purpose or missing
  a key fact you cannot reasonably infer), return a clarifying_question instead of
  drafting.
- Never invent specific facts (names, prices, dates, links, order numbers) the user
  did not provide. When a concrete detail is genuinely required but unknown, use a
  short placeholder in [square brackets] the user can fill in.
- Write a clear, specific subject line.
- Match the user's preferred tone; keep it concise unless the request calls for detail.
- Sign off with the user's name if it is known.

Return ONLY a JSON object:
{{"subject": "...", "body": "...", "clarifying_question": null}}

If clarification is needed:
{{"subject": null, "body": null, "clarifying_question": "Who is this email to, and what's the main ask?"}}"""

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(_sanitize_history(payload.conversation_history))
    messages.append({"role": "user", "content": f"Write an email: {payload.prompt}"})

    result = await _complete_json(messages, temperature=0.7)

    return ComposeResponse(
        subject=result.get("subject") or "",
        body=result.get("body") or "",
        clarifying_question=result.get("clarifying_question"),
    )


@router.post("/rewrite", response_model=ComposeResponse)
@limiter.limit("20/minute")
async def compose_rewrite(
    request: Request,
    payload: ComposeRewriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rewrites an existing composed draft based on a natural-language instruction."""
    profile = await _get_profile(current_user.id, db)
    style_context = await _get_user_style_context(current_user.id, db)

    system_prompt = f"""You are JARVIS, an AI email assistant.
Rewrite the draft email based on the user's instruction.
Keep what's working, change only what the instruction asks for.
Do not invent facts that aren't already in the draft or the instruction.
User preferred tone: {profile.preferred_tone if profile else 'professional'}
{style_context}

Return ONLY a JSON object:
{{"subject": "...", "body": "...", "clarifying_question": null}}"""

    current = payload.current_draft
    if payload.current_subject:
        current = f"Subject: {payload.current_subject}\n\n{current}"

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(_sanitize_history(payload.conversation_history))
    messages.append({
        "role": "user",
        "content": f"Current draft:\n{current}\n\nRewrite instruction: {payload.rewrite_instruction}",
    })

    result = await _complete_json(messages, temperature=0.6)

    # Body falls back to the current draft — never lose the user's text to a bad
    # model response.
    return ComposeResponse(
        subject=result.get("subject") or (payload.current_subject or ""),
        body=result.get("body") or payload.current_draft,
        clarifying_question=result.get("clarifying_question"),
    )
