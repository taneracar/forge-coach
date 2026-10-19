import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import InvalidToken, TokenVerifier

ISSUER = "https://example.supabase.co/auth/v1"


class LocalJWKS:
    """Stands in for PyJWKClient: same lookup, keys from memory."""

    def __init__(self, keys: dict[str, ec.EllipticCurvePublicKey]):
        self._keys = keys

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in self._keys:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        return jwt.PyJWK.from_dict(
            {**jwt.algorithms.ECAlgorithm.to_jwk(self._keys[kid], as_dict=True), "kid": kid}
        )


@pytest.fixture
def key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def verifier(key):
    return TokenVerifier(LocalJWKS({"k1": key.public_key()}), ISSUER)


def sign(key, kid="k1", **overrides):
    claims = {
        "sub": "user-1",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 600,
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


def test_accepts_a_valid_token(key, verifier):
    token = sign(key)
    user = verifier.verify(token)
    assert user.id == "user-1"
    assert user.token == token


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "anon"},
        {"iss": "https://other.supabase.co/auth/v1"},
        {"exp": int(time.time()) - 10},
        {"sub": None},
        {"exp": None},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired", "no-subject", "no-expiry"],
)
def test_rejects_bad_claims(key, verifier, overrides):
    with pytest.raises(InvalidToken):
        verifier.verify(sign(key, **overrides))


def test_rejects_a_token_signed_by_another_key(verifier):
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(InvalidToken):
        verifier.verify(sign(other))


def test_rejects_an_unknown_key_id(key, verifier):
    with pytest.raises(InvalidToken):
        verifier.verify(sign(key, kid="k2"))


def test_rejects_garbage(verifier):
    with pytest.raises(InvalidToken):
        verifier.verify("not-a-jwt")
