"""
One-time Composio setup script. Run this to:
  1. Connect a Gmail account (opens a browser OAuth flow)
  2. Create a GMAIL_NEW_GMAIL_MESSAGE trigger on that account
  3. Register your webhook URL with Composio

Prerequisites:
  - .env has a real COMPOSIO_API_KEY
  - uvicorn app.main:app --reload is running in another terminal
  - ngrok http 8000 is running and you have the https URL

Usage:
  py scripts/setup_composio.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.services.composio_client import (
    create_gmail_trigger,
    register_webhook,
    start_gmail_connection,
)


async def main() -> None:
    print("\n=== Jarvis Mail — Composio Setup ===\n")
    print("(Webhook registered via dashboard — connecting Gmail now)\n")

    user_id = input(
        "Enter the user_id to connect Gmail for\n"
        "(use the UUID from your Supabase users table)\n"
        "> "
    ).strip() or "test-user-1"

    redirect_url = start_gmail_connection(user_id)
    print(f"\n✓ Open this URL in your browser to authorise Gmail:\n  {redirect_url}\n")
    input("Press Enter once you've completed the OAuth flow in the browser...")

    print("\nCreating GMAIL_NEW_GMAIL_MESSAGE trigger...")
    try:
        trigger_id = create_gmail_trigger(user_id)
        print(f"\n✓ Trigger created: {trigger_id}")
        print("\n=== Setup complete ===")
        print("Send an email to the connected Gmail address.")
        print("Watch uvicorn logs — you should see POST /api/webhooks/composio within seconds.")
    except Exception as e:
        print(f"\n✗ Trigger creation failed: {e}")
        print("Make sure the OAuth flow completed fully before running again.")


if __name__ == "__main__":
    asyncio.run(main())
