from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.auth import decode_and_verify
from app.core.config import settings


def _make_token(*, secret=None, exp_delta=timedelta(hours=1), **claims):
    payload = {
        "sub": "supabase-user-123",
        "email": "[email protected]",
        "aud": "authenticated",
        "exp": datetime.now(timezone.utc) + exp_delta,
        **claims,
    }
    return jwt.encode(payload, secret or settings.supabase_jwt_secret, algorithm="HS256")


def test_valid_token_decodes_correctly():
    token = _make_token()
    payload = decode_and_verify(token)
    assert payload["sub"] == "supabase-user-123"
    assert payload["email"] == "[email protected]"


def test_expired_token_is_rejected():
    token = _make_token(exp_delta=timedelta(hours=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_and_verify(token)


def test_wrong_secret_is_rejected():
    token = _make_token(secret="a-completely-different-secret")
    with pytest.raises(jwt.InvalidSignatureError):
        decode_and_verify(token)


def test_wrong_audience_is_rejected():
    token = _make_token(aud="some-other-audience")
    with pytest.raises(jwt.InvalidAudienceError):
        decode_and_verify(token)
