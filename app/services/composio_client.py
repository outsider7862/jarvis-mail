"""
Wraps Composio for:
  - Connecting a user's Gmail/Outlook via OAuth
  - Creating a GMAIL_NEW_GMAIL_MESSAGE trigger on their account
  - Registering our webhook URL so Composio delivers events to us
  - Parsing and verifying incoming webhook payloads (v3 format)
"""

from composio import Composio
from app.core.config import settings

composio = Composio(api_key=settings.composio_api_key)


# ── OAuth connection ──────────────────────────────────────────────────────────

def start_gmail_connection(user_id: str, redirect_uri: str | None = None) -> str:
    """
    Kicks off the OAuth flow for connecting a user's Gmail account.
    Returns a redirect URL — send the business owner there to grant access.

    redirect_uri is where Google/Composio sends the user back to once they grant
    access. The installed SDK's session.authorize() calls this kwarg callback_url,
    not redirect_uri — passed through under that name here.
    """
    session = composio.create(user_id=user_id, toolkits=["gmail"])
    connection_request = session.authorize("gmail", callback_url=redirect_uri)
    return connection_request.redirect_url


def start_outlook_connection(user_id: str) -> str:
    session = composio.create(user_id=user_id, toolkits=["outlook"])
    connection_request = session.authorize("outlook")
    return connection_request.redirect_url


# ── Trigger creation ──────────────────────────────────────────────────────────

def delete_trigger(trigger_id: str) -> None:
    """Permanently removes a trigger instance — used when a user disconnects their inbox."""
    composio.triggers.delete(trigger_id)


def create_gmail_trigger(user_id: str) -> str:
    """
    Creates a GMAIL_NEW_GMAIL_MESSAGE trigger for the given user.
    Returns the trigger_id — store it against the ConnectedAccount row.
    """
    trigger = composio.triggers.create(
        slug="GMAIL_NEW_GMAIL_MESSAGE",
        user_id=user_id,
        trigger_config={},
    )
    return trigger.trigger_id


# ── Webhook subscription registration ────────────────────────────────────────

def register_webhook(webhook_url: str) -> str:
    """
    Registers our FastAPI webhook endpoint with Composio.
    Call this ONCE per deployment — not per user.
    Returns the webhook secret — store as COMPOSIO_WEBHOOK_SECRET in .env.
    """
    subscription = composio.triggers.set_webhook_subscription(
        webhook_url=webhook_url,
    )
    return subscription.get("secret", "")


# ── Payload parsing and verification ─────────────────────────────────────────

def parse_webhook(raw_body: bytes, headers: dict) -> dict | None:
    result = composio.triggers.parse(
        body=raw_body,
        headers=headers,
        verify_secret=settings.composio_webhook_secret,
    )

    raw = result.get("raw_payload", {})
    if raw.get("type") != "composio.trigger.message":
        return None

    # connected_account_id lives in metadata, not payload
    metadata = raw.get("metadata", {})
    return {
        "trigger_slug":         metadata.get("trigger_slug", ""),
        "connected_account_id": metadata.get("connected_account_id", ""),
        "user_id":              metadata.get("user_id", ""),
        "data":                 raw.get("data", {}),
    }