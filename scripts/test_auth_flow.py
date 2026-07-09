"""
Manual, one-time sanity check for the whole auth pipeline against your REAL
Supabase project — not part of the pytest suite (those are isolated/offline on
purpose; this one deliberately needs live credentials and a running server).

What it proves: a real Supabase login produces a JWT that our FastAPI backend
actually accepts, and that a local User row gets created on first use.

Before running:
  1. .env has real SUPABASE_URL and DATABASE_URL, and `py scripts/init_db.py`
     has been run
  2. In another terminal: uvicorn app.main:app --reload
  3. In the Supabase dashboard: Authentication -> Providers -> Email -> turn
     OFF "Confirm email" for now. With it on, sign_up() won't return a usable
     session until the test address clicks a confirmation link, which gets in
     the way of a quick local check. Turn it back on before real users show up.

Usage:
  py scripts/test_auth_flow.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
TEST_EMAIL = "jarvistest@gmail.com"
TEST_PASSWORD = "test-password-123!"
API_BASE_URL = "http://localhost:8000"


def get_session_token() -> str:
    supabase_url = os.environ["SUPABASE_URL"]

    # The anon/publishable key is safe to paste here — unlike DATABASE_URL, it's
    # meant to be public (Row Level Security is what actually protects data, not
    # secrecy of this key). Find it at Project Settings -> API -> Project API keys.
    anon_key = input("Paste your Supabase anon/publishable key: ").strip()
    client = create_client(supabase_url, anon_key)

    session = None
    try:
        result = client.auth.sign_up({"email": TEST_EMAIL, "password": TEST_PASSWORD})
        session = result.session
    except Exception as exc:
        print(f"sign_up() didn't return a fresh session ({exc}), trying sign_in instead...")

    if session is None:
        result = client.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
        session = result.session

    if session is None:
        raise SystemExit(
            "No session returned. Most likely cause: 'Confirm email' is still ON "
            "in Supabase (Authentication -> Providers -> Email) — turn it off for "
            "this local test, or check the test inbox and confirm manually."
        )

    return session.access_token


def main() -> None:
    token = get_session_token()
    print(f"\nGot a session token: {token[:24]}...\n")

    response = requests.get(
        f"{API_BASE_URL}/api/leads",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    print(f"GET /api/leads -> HTTP {response.status_code}")
    print(response.json())

    if response.status_code == 200:
        print(
            "\nAuth pipeline works end to end: Supabase login -> real JWT -> "
            "FastAPI verified it against the JWKS endpoint -> User row "
            "created/found -> empty leads list returned (expected, you haven't "
            "connected an inbox yet)."
        )
    else:
        print("\nSomething's off — check the uvicorn server logs for the actual error.")


if __name__ == "__main__":
    main()
