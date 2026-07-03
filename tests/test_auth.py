from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.auth import decode_and_verify


class _FakeSigningKey:
    """Mimics the object PyJWKClient.get_signing_key_from_jwt() returns — just needs a .key attribute."""

    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    """Stands in for PyJWKClient so tests never hit the network. Always returns the same test key."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):  # noqa: ARG002 — signature must match PyJWKClient's
        return _FakeSigningKey(self._public_key)


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _make_token(private_key, *, exp_delta=timedelta(hours=1), **claims):
    payload = {
        "sub": "supabase-user-123",
        "email": "[email protected]",
        "aud": "authenticated",
        "exp": datetime.now(timezone.utc) + exp_delta,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-key-1"})


def test_valid_token_decodes_correctly(keypair):
    private_key, public_key = keypair
    token = _make_token(private_key)

    payload = decode_and_verify(token, jwks_client=_FakeJWKClient(public_key))

    assert payload["sub"] == "supabase-user-123"
    assert payload["email"] == "[email protected]"


def test_expired_token_is_rejected(keypair):
    private_key, public_key = keypair
    token = _make_token(private_key, exp_delta=timedelta(hours=-1))

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_and_verify(token, jwks_client=_FakeJWKClient(public_key))


def test_token_signed_by_different_key_is_rejected(keypair):
    _, public_key = keypair
    other_private_key = ec.generate_private_key(ec.SECP256R1())
    token = _make_token(other_private_key)  # signed with a DIFFERENT key than the one we'll verify against

    with pytest.raises(jwt.InvalidSignatureError):
        decode_and_verify(token, jwks_client=_FakeJWKClient(public_key))


def test_wrong_audience_is_rejected(keypair):
    private_key, public_key = keypair
    token = _make_token(private_key, aud="some-other-audience")

    with pytest.raises(jwt.InvalidAudienceError):
        decode_and_verify(token, jwks_client=_FakeJWKClient(public_key))
