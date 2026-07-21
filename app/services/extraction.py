"""
Turns raw email text into a full EmailAnalysisExtraction using OpenAI's Responses
API with a Pydantic schema (structured outputs — the model cannot return malformed
JSON here, so no manual parsing/retry logic is needed for shape, only for
API-level failures like timeouts).

This runs for every email that makes it past the light prefilter — unlike the
original lead-only version, "classify everything" is the actual product now
(morning brief, notifications, search all depend on every email having a category),
so we deliberately send more volume through here. See prefilter.py for the
reasoning on what still gets skipped.
"""

from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.analysis import EmailAnalysisExtraction

client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """You are Jarvis Mail's email classifier, working for a small \
service business (an agency, contractor, or consultant). Read the email and \
classify it accurately across every field in the schema.

Category guidance:
- business_lead: inbound inquiry, referral, or request to hire the business. Be \
conservative — existing-client project chatter is NOT a new lead.
- invoice: a bill, receipt, or payment request (incoming or outgoing).
- meeting: proposes, confirms, reschedules, or discusses a meeting or call.
- customer_support: an existing client reporting an issue or asking for help.
- newsletter: mailing-list content, digests, promotional sends.
- spam: unsolicited, irrelevant, or low-quality bulk email.
- phishing: shows signs of a phishing or social-engineering attempt — spoofed or \
mismatched sender/reply-to, urgent credential or payment requests, suspicious \
links, impersonation of a known contact or service. Flag generously here; a false \
positive costs the user a glance, a missed phishing email could cost real money.
- personal: emails from friends, family, or social contacts — invitations, \
personal conversations, dating, celebrations, condolences. These should NOT be \
treated as business emails or flagged as low priority just because they are not \
work-related.
- order: order confirmations, shipping notifications, delivery updates, tracking \
emails, and purchase receipts. The user bought or ordered something and this is a \
transactional update about it.
- otp: emails containing a one-time password, verification code, login code, or \
any time-sensitive authentication code. Treat these as high priority since codes \
expire. Never repeat the actual code in the summary.
- security_alert: legitimate security notifications from known services — new \
device logins, password change confirmations, account activity summaries. CRITICAL \
distinction from phishing: security alerts do NOT ask the user to click a link to \
verify credentials or take urgent action. They inform, not demand. If the email \
pressures the user to act urgently or click a link, classify as phishing instead.
- other: use this rather than forcing a bad fit into another category.

Priority guidance:
- Emails classified as otp should always be priority='urgent' — verification codes \
expire quickly.
- Security alerts should be priority='high'.

Summary guidance — CRITICAL:
- Preserve all specific numbers, percentages, monetary amounts, and dates verbatim \
in the summary. Do not round or generalise them.
- Example: write "2% of users" not "some users", write "PKR 150,000" not \
"a budget", write "by August 31" not "soon".
- Keep key context that affects the recipient's decision — deadlines, amounts, \
names, and conditions matter.

Only fill in optional fields (action_required, deadline, lead_detail) when you can \
support them from the email content. Leave them null rather than guessing."""


def _build_profile_context(user_profile: dict | None) -> str:
    """Turns the onboarding profile into a short prompt suffix. Empty when no profile."""
    if not user_profile:
        return ""
    parts = []
    if user_profile.get("display_name"):
        parts.append(f"The user's name is {user_profile['display_name']}.")
    if user_profile.get("work_type"):
        parts.append(f"They work as a {user_profile['work_type']}.")
    if user_profile.get("email_use"):
        parts.append(f"They mainly use email for {user_profile['email_use']}.")
    if user_profile.get("preferred_tone"):
        parts.append(f"Their preferred communication tone is {user_profile['preferred_tone']}.")
    if user_profile.get("custom_instructions"):
        parts.append(f"Additional context: {user_profile['custom_instructions']}")
    if not parts:
        return ""
    return "\n\nUser profile:\n" + " ".join(parts)


async def analyze_email(
    *,
    subject: str,
    body_text: str,
    sender: str,
    user_profile: dict | None = None,
) -> EmailAnalysisExtraction:
    # Create a fresh client per call — avoids closed connection pool
    # issues when running inside FastAPI background tasks
    system_prompt = SYSTEM_PROMPT + _build_profile_context(user_profile)
    async with AsyncOpenAI(api_key=settings.openai_api_key) as client:
        truncated_body = (body_text or "")[:10_000]
        response = await client.responses.parse(
            model=settings.openai_extraction_model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"From: {sender}\nSubject: {subject}\n\nBody:\n{truncated_body}",
                },
            ],
            text_format=EmailAnalysisExtraction,
        )
        return response.output_parsed


def compute_should_notify(analysis: EmailAnalysisExtraction) -> bool:
    """
    Decides whether this classification should trigger a notification, per the
    spec: high priority, new business lead, meeting (same-day handled by the
    caller which knows "today" in the user's timezone), or phishing.
    """
    if analysis.priority in ("high", "urgent"):
        return True
    if analysis.is_business_lead:
        return True
    if analysis.is_phishing:
        return True
    if analysis.is_meeting:
        return True
    if analysis.is_otp:
        return True
    if analysis.is_security_alert:
        return True
    return False
