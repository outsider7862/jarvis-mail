"""
Guards the one unauthenticated endpoint: the Composio webhook, whose signature
IS its auth.

The previous version of this file tested a hand-rolled verify_webhook_signature()
helper that no longer exists — verification moved to the SDK's
composio.triggers.parse(verify_secret=...). That left the file failing at import,
which took the whole suite down with it and meant nothing guarded the
verify_secret wiring. These tests target the current implementation instead.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_parse_webhook_passes_the_configured_secret():
    """If verify_secret ever regresses to None, signatures stop being checked."""
    from app.services.composio_client import parse_webhook

    with patch("app.services.composio_client.composio.triggers.parse") as mocked:
        mocked.return_value = {"raw_payload": {"type": "something.else"}}
        parse_webhook(b"{}", {"webhook-id": "msg_1"})

    kwargs = mocked.call_args.kwargs
    assert kwargs["verify_secret"] == settings.composio_webhook_secret
    assert kwargs["verify_secret"] is not None


def test_unsigned_request_is_rejected_with_401():
    """A junk/unsigned payload must be refused, not 500 with a stack trace."""
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/webhooks/composio", json={"payload": "junk"})
    assert response.status_code == 401


def test_tampered_signature_is_rejected_with_401():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/webhooks/composio",
        json={"payload": "junk"},
        headers={
            "webhook-id": "msg_1",
            "webhook-timestamp": "1700000000",
            "webhook-signature": "v1,not_the_real_signature==",
        },
    )
    assert response.status_code == 401


def test_valid_signature_reaches_handler():
    """With verification passing, a non-trigger event is ignored (not 401)."""
    client = TestClient(app, raise_server_exceptions=False)
    with patch("app.api.routes.webhooks.parse_webhook", return_value=None):
        response = client.post("/api/webhooks/composio", json={"payload": "ok"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
