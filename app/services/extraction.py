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
- other: use this rather than forcing a bad fit into another category.

Only fill in optional fields (action_required, deadline, lead_detail) when you can \
support them from the email content. Leave them null rather than guessing."""


async def analyze_email(*, subject: str, body_text: str, sender: str) -> EmailAnalysisExtraction:
    # Cap body length so a huge thread doesn't blow the context window or cost —
    # the first ~10k characters is almost always enough to classify an email.
    truncated_body = (body_text or "")[:10_000]

    response = await client.responses.parse(
        model=settings.openai_extraction_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
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
    return False
