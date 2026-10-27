"""Validation of the access tokens issued by Keycloak."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt

from cragradar_backend.core.settings import get_settings

SIGNING_KEYS_CACHE_SECONDS: int = 300


@dataclass(frozen=True)
class AccessTokenVerifier:
    issuer: str
    audience: str
    # Returns the public key that signed the given token.
    resolve_signing_key: Callable[[str], jwt.PyJWK]

    def verify(self, token: str) -> dict[str, Any]:
        """Return the claims of a valid token. Raise ``jwt.PyJWTError`` otherwise."""
        signing_key: jwt.PyJWK = self.resolve_signing_key(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        return claims


@lru_cache
def get_token_verifier() -> AccessTokenVerifier:
    """FastAPI dependency. The JWKS client caches the signing keys between requests."""
    settings = get_settings()
    jwks_client: jwt.PyJWKClient = jwt.PyJWKClient(
        settings.oidc_jwks_url, cache_keys=True, lifespan=SIGNING_KEYS_CACHE_SECONDS
    )
    return AccessTokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        resolve_signing_key=jwks_client.get_signing_key_from_jwt,
    )
