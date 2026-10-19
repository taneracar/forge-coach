"""Supabase access-token verification.

Same rules as forge-api's TokenVerifier: the project signs with ES256 and
publishes its public key at the JWKS endpoint, so nothing secret lives here.
A token is accepted only with a valid signature, the project's issuer, the
`authenticated` audience, an unexpired `exp`, and a subject.
"""

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings


@dataclass(frozen=True)
class CurrentUser:
    id: str
    token: str


class TokenVerifier:
    def __init__(self, jwks: jwt.PyJWKClient, issuer: str):
        self._jwks = jwks
        self._issuer = issuer

    @classmethod
    def for_project(cls, supabase_url: str) -> "TokenVerifier":
        issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        # The client caches keys and refetches only for an unknown `kid`.
        return cls(jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True), issuer)

    def verify(self, token: str) -> CurrentUser:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["ES256"],
                issuer=self._issuer,
                audience="authenticated",
                options={"require": ["exp", "sub"]},
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError) as e:
            raise InvalidToken(str(e)) from e
        return CurrentUser(id=claims["sub"], token=token)


class InvalidToken(Exception):
    pass


_bearer = HTTPBearer(auto_error=False)
_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier.for_project(get_settings().supabase_url)
    return _verifier


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        return verifier.verify(creds.credentials)
    except InvalidToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from None
