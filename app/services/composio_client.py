"""
Wraps Composio for: connecting a user's Gmail/Outlook, creating a real-time trigger
for new mail, and verifying that incoming webhook calls actually came from Composio.

IMPORTANT — real-time vs polling: use trigger types that Composio delivers via
webhook in real time (e.g. GMAIL_NEW_GMAIL_MESSAGE configured for push delivery).
Do not rely on polling-interval triggers for "new lead just arrived" — Composio now
enforces a 15-minute minimum poll interval, which defeats the point here.
"""

import hashlib
import hmac
import base64

from composio import Composio

from app.core.config import settings

composio = Composio(api_key=settings.composio_api_key)


def start_gmail_connection(user_id: str) -> str:
    """
    Kicks off the OAuth flow for connecting a user's Gmail account.
    Returns a redirect URL — send the business owner there to grant access.
    """
    session = composio.create(user_id=user_id, toolkits=["gmail"])
    connection_request = session.authorize("gmail")
    return connection_request.redirect_url


def start_outlook_connection(user_id: str) -> str:
    session = composio.create(user_id=user_id, toolkits=["outlook"])
    connection_request = session.authorize("outlook")
    return connection_request.redirect_url


def create_new_email_trigger(user_id: str, provider: str) -> str:
    """
    Creates a trigger that fires on new inbound mail for the given provider
    ("gmail" or "outlook"). Returns the trigger_id to store against the
    ConnectedAccount row.

    Run this once, right after a user finishes the OAuth flow above.
    """
    slug = "GMAIL_NEW_GMAIL_MESSAGE" if provider == "gmail" else "OUTLOOK_NEW_MESSAGE"
    trigger = composio.triggers.create(
        slug=slug,
        user_id=user_id,
        trigger_config={},
    )
    return trigger.trigger_id


def verify_webhook_signature(
    *, signature_header: str, webhook_id: str, timestamp: str, raw_body: bytes
) -> bool:
    """
    Verifies the `webhook-signature` header Composio sends on every webhook POST.

    Header format: "v1,<base64_hmac_sha256>"
    Signing string: "{webhook_id}.{timestamp}.{raw_body}"

    Reject the request if this returns False — do not process unverified payloads.
    """
    if not signature_header.startswith("v1,"):
        return False

    received_signature = signature_header[3:]
    signing_string = f"{webhook_id}.{timestamp}.{raw_body.decode('utf-8')}"

    expected = base64.b64encode(
        hmac.new(
            settings.composio_webhook_secret.encode("utf-8"),
            signing_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(received_signature, expected)
