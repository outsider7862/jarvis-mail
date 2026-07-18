"""
JARVIS reply drafting.

Nothing here ever sends an email — every endpoint returns text the user reviews
and sends themselves from Gmail. The "learning" is deliberately simple: recent
draft-vs-sent diffs (reply_feedback) are replayed into the prompt as style
examples. No embeddings, no fine-tuning, no stored conversations.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import EmailAnalysis, RawEmail, ReplyFeedback, User, UserProfile
from app.db.session import get_db

router = APIRouter(prefix="/api/reply", tags=["reply"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class QuickActionsResponse(BaseModel):
    actions: list[str]
    needs_clarification: bool
    clarifying_question: str | None


class DraftRequest(BaseModel):
    analysis_id: uuid.UUID
    intent: str
    conversation_history: list[dict] | None = None  # [{"role": "user"|"assistant", "content": "..."}]


class DraftResponse(BaseModel):
    subject: str
    body: str
    clarifying_question: str | None  # set when JARVIS needs more info before drafting


class FeedbackRequest(BaseModel):
    analysis_id: uuid.UUID
    intent: str
    category: str
    original_draft: str
    edited_draft: str   # what the user actually kept after editing


class RewriteRequest(BaseModel):
    analysis_id: uuid.UUID
    current_draft: str
    rewrite_instruction: str  # e.g. "make it shorter", "be more firm about the price"
    conversation_history: list[dict] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_owned_analysis(
    analysis_id: uuid.UUID, current_user: User, db: AsyncSession
) -> EmailAnalysis:
    result = await db.execute(
        select(EmailAnalysis).where(
            EmailAnalysis.id == analysis_id,
            EmailAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


def _sanitize_history(history: list[dict] | None) -> list[dict]:
    """
    conversation_history arrives from the client, so it can't be trusted verbatim
    — a crafted 'system' turn would let a caller rewrite JARVIS's instructions.
    Keep only user/assistant turns with string content.
    """
    if not history:
        return []
    clean: list[dict] = []
    for turn in history[-20:]:  # bound the context we replay
        if not isinstance(turn, dict):
            continue
        role, content = turn.get("role"), turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            clean.append({"role": role, "content": content[:4000]})
    return clean


async def _get_user_style_context(
    user_id: uuid.UUID, db: AsyncSession, limit: int = 10
) -> str:
    """
    Builds a style context string from the user's recent feedback history.
    This is how JARVIS learns — it reads past edits, not conversations.
    """
    result = await db.execute(
        select(ReplyFeedback)
        .where(ReplyFeedback.user_id == user_id)
        .order_by(ReplyFeedback.created_at.desc())
        .limit(limit)
    )
    feedbacks = result.scalars().all()

    if not feedbacks:
        return ""

    examples = []
    for fb in feedbacks:
        if fb.original_draft.strip() != fb.edited_draft.strip():
            examples.append(
                f"Intent: {fb.intent}\n"
                f"JARVIS wrote: {fb.original_draft[:300]}\n"
                f"User changed it to: {fb.edited_draft[:300]}"
            )

    if not examples:
        return ""

    return (
        "\n\nLearned style preferences from past interactions:\n"
        + "\n---\n".join(examples[:5])
        + "\n\nAdapt your draft to match the user's editing patterns above."
    )


async def _complete_json(messages: list[dict], temperature: float) -> dict:
    """
    Calls the model in JSON mode and parses the result.

    response_format=json_object matters: without it the model tends to wrap JSON
    in markdown fences, json.loads throws, and every call silently degrades to
    the fallback path. Returns {} if the response still isn't usable.
    """
    async with AsyncOpenAI(api_key=settings.openai_api_key) as client:
        response = await client.chat.completions.create(
            model=settings.openai_reply_model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    content = response.choices[0].message.content or ""
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{analysis_id}/quick-actions", response_model=QuickActionsResponse)
@limiter.limit("30/minute")
async def get_quick_actions(
    request: Request,
    analysis_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis = await _get_owned_analysis(analysis_id, current_user, db)
    raw_result = await db.execute(
        select(RawEmail).where(RawEmail.id == analysis.raw_email_id)
    )
    raw = raw_result.scalar_one_or_none()

    prompt = f"""You are JARVIS, an AI email assistant.

Based on this email, do two things:
1. Generate 4-6 context-aware quick reply action labels (3-5 words each)
2. Decide if you need clarification before drafting (set needs_clarification=true
   and provide a clarifying_question if the intent could go multiple ways)

Email category: {analysis.category}
Email summary: {analysis.summary}
Original email body: {(raw.body_text or '')[:2000] if raw else ''}

Return ONLY a JSON object with this structure:
{{
  "actions": ["Action 1", "Action 2", "Action 3", "Action 4"],
  "needs_clarification": false,
  "clarifying_question": null
}}

If clarification is needed, example:
{{
  "actions": ["Accept", "Decline", "Suggest New Time", "Ask for Details"],
  "needs_clarification": true,
  "clarifying_question": "Should I mention a specific alternative time, or keep it open-ended?"
}}"""

    result = await _complete_json([{"role": "user", "content": prompt}], temperature=0.3)

    actions = result.get("actions")
    if not isinstance(actions, list) or not actions:
        actions = ["Reply", "Decline", "Ask for More Info"]

    return QuickActionsResponse(
        actions=[str(a) for a in actions][:6],
        needs_clarification=bool(result.get("needs_clarification", False)),
        clarifying_question=result.get("clarifying_question"),
    )


@router.post("/draft", response_model=DraftResponse)
@limiter.limit("20/minute")
async def draft_reply(
    request: Request,
    payload: DraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis = await _get_owned_analysis(payload.analysis_id, current_user, db)

    raw_result = await db.execute(
        select(RawEmail).where(RawEmail.id == analysis.raw_email_id)
    )
    raw = raw_result.scalar_one_or_none()

    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()

    # Build learned style context from past edits
    style_context = await _get_user_style_context(current_user.id, db)

    system_prompt = f"""You are JARVIS, an AI email assistant for a service business owner.
You help draft email replies but NEVER send emails automatically.
You reduce decisions, not make them. When unsure, ask — don't assume.

User profile:
- Name: {profile.display_name if profile else 'the user'}
- Work type: {profile.work_type if profile else 'professional'}
- Preferred tone: {profile.preferred_tone if profile else 'professional'}
- Email use: {profile.email_use if profile else 'business communication'}
- Custom instructions: {profile.custom_instructions if profile else 'none'}
{style_context}

Original email context:
From: {raw.sender if raw else 'unknown'}
Subject: {raw.subject if raw else 'unknown'}
Body: {(raw.body_text or '')[:3000] if raw else ''}
AI Summary: {analysis.summary}

Rules:
- If the intent is ambiguous, return a clarifying_question instead of drafting
- Never invent facts (prices, dates, names) not in the email or intent
- Always sign off with the user's name
- Match the user's preferred tone
- Keep it concise unless the intent calls for detail

Return ONLY a JSON object:
{{"subject": "Re: ...", "body": "...", "clarifying_question": null}}

If clarification needed:
{{"subject": null, "body": null, "clarifying_question": "What specific time works for you?"}}"""

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(_sanitize_history(payload.conversation_history))
    messages.append({"role": "user", "content": f"Draft a reply with this intent: {payload.intent}"})

    result = await _complete_json(messages, temperature=0.7)

    fallback_subject = f"Re: {raw.subject if raw and raw.subject else ''}".strip()
    return DraftResponse(
        subject=result.get("subject") or fallback_subject,
        body=result.get("body") or "",
        clarifying_question=result.get("clarifying_question"),
    )


@router.post("/rewrite", response_model=DraftResponse)
@limiter.limit("20/minute")
async def rewrite_draft(
    request: Request,
    payload: RewriteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rewrites an existing draft based on a natural language instruction.
    e.g. "make it shorter", "be more firm about the price", "add a deadline"
    """
    await _get_owned_analysis(payload.analysis_id, current_user, db)

    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()

    style_context = await _get_user_style_context(current_user.id, db)

    system_prompt = f"""You are JARVIS, an AI email assistant.
Rewrite the draft email based on the user's instruction.
Keep what's working, change only what the instruction asks for.
User preferred tone: {profile.preferred_tone if profile else 'professional'}
{style_context}

Return ONLY a JSON object:
{{"subject": "...", "body": "...", "clarifying_question": null}}"""

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(_sanitize_history(payload.conversation_history))
    messages.append({
        "role": "user",
        "content": f"Current draft:\n{payload.current_draft}\n\nRewrite instruction: {payload.rewrite_instruction}",
    })

    result = await _complete_json(messages, temperature=0.6)

    # Body falls back to the current draft rather than "" — losing the user's
    # draft to a bad model response would be the worst possible failure here.
    return DraftResponse(
        subject=result.get("subject") or "",
        body=result.get("body") or payload.current_draft,
        clarifying_question=result.get("clarifying_question"),
    )


@router.post("/feedback")
@limiter.limit("30/minute")
async def save_feedback(
    request: Request,
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Called when the user opens the Gmail compose window with the draft.
    Saves the diff between what JARVIS wrote and what the user kept/changed.
    This is the learning signal — JARVIS adapts its style based on these edits.
    Only saves if the user actually changed something meaningful.
    """
    # Confirm the analysis belongs to this user before writing a row against it.
    await _get_owned_analysis(payload.analysis_id, current_user, db)

    # Only save if the user made changes (not just whitespace)
    if payload.original_draft.strip() == payload.edited_draft.strip():
        return {"saved": False, "reason": "no changes"}

    feedback = ReplyFeedback(
        id=uuid.uuid4(),
        user_id=current_user.id,
        analysis_id=payload.analysis_id,
        original_draft=payload.original_draft,
        edited_draft=payload.edited_draft,
        intent=payload.intent,
        category=payload.category,
    )
    db.add(feedback)
    await db.commit()
    return {"saved": True}
