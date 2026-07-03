import base64
import hashlib
import hmac

from app.core.config import settings
from app.services.composio_client import verify_webhook_signature


def _sign(webhook_id: str, timestamp: str, body: bytes) -> str:
    signing_string = f"{webhook_id}.{timestamp}.{body.decode()}"
    digest = hmac.new(settings.composio_webhook_secret.encode(), signing_string.encode(), hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


def test_valid_signature_is_accepted():
    webhook_id, timestamp, body = "msg_1", "1700000000", b'{"payload": {"subject": "test"}}'
    header = _sign(webhook_id, timestamp, body)
    assert verify_webhook_signature(
        signature_header=header, webhook_id=webhook_id, timestamp=timestamp, raw_body=body
    ) is True


def test_tampered_signature_is_rejected():
    webhook_id, timestamp, body = "msg_1", "1700000000", b'{"payload": {"subject": "test"}}'
    assert verify_webhook_signature(
        signature_header="v1,not_the_real_signature==", webhook_id=webhook_id, timestamp=timestamp, raw_body=body
    ) is False


def test_signature_for_different_body_is_rejected():
    webhook_id, timestamp = "msg_1", "1700000000"
    header = _sign(webhook_id, timestamp, b'{"payload": {"subject": "original"}}')
    tampered_body = b'{"payload": {"subject": "tampered"}}'
    assert verify_webhook_signature(
        signature_header=header, webhook_id=webhook_id, timestamp=timestamp, raw_body=tampered_body
    ) is False


def test_missing_v1_prefix_is_rejected():
    assert verify_webhook_signature(
        signature_header="deadbeef", webhook_id="msg_1", timestamp="1700000000", raw_body=b"{}"
    ) is False
