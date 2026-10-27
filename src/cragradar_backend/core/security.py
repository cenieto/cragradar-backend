"""Validation of the access tokens issued by Keycloak, and role checks."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status

from cragradar_backend.core.settings import OidcSettings, get_settings

BEARER_PREFIX: str = "Bearer "

PLATFORM_ADMIN_ROLE: str = "platform_admin"
CONTENT_GENERATOR_ROLE: str = "content_generator"
VIEWER_ROLE: str = "viewer"

CONTENT_EDITOR_ROLES: frozenset[str] = frozenset({PLATFORM_ADMIN_ROLE, CONTENT_GENERATOR_ROLE})
"""Roles allowed to upload and manage images."""


@dataclass(frozen=True)
class AccessTokenVerifier:
    """Checks the signature, issuer, audience and expiry of access tokens.

    Attributes:
        issuer: Expected ``iss`` claim.
        audience: Expected ``aud`` claim.
        resolve_signing_key: Returns the public key that signed the given token.
    """

    issuer: str
    audience: str
    resolve_signing_key: Callable[[str], jwt.PyJWK]

    def verify(
        self,
        token: str,
    ) -> dict[str, Any]:
        """Return the claims of a valid token.

        Args:
            token: Encoded access token.

        Returns:
            dict[str, Any]: The claims of the token.

        Raises:
            jwt.PyJWTError: If the token is invalid, or its signing key cannot be fetched.
        """
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


@dataclass(frozen=True)
class AuthenticatedUser:
    """User of a request with a valid access token.

    Attributes:
        subject: Keycloak id of the user (``sub`` claim).
        roles: Realm roles of the user.
    """

    subject: str
    roles: frozenset[str]

    @classmethod
    def from_claims(
        cls,
        claims: dict[str, Any],
    ) -> "AuthenticatedUser":
        """Build the user from the claims of a Keycloak access token.

        Args:
            claims: Validated claims; realm roles are read from ``realm_access.roles``.

        Returns:
            AuthenticatedUser: The user.
        """
        realm_access: dict[str, Any] = claims.get("realm_access") or {}
        roles: list[str] = realm_access.get("roles") or []
        return cls(subject=str(claims["sub"]), roles=frozenset(roles))

    def has_any_role(
        self,
        roles: frozenset[str],
    ) -> bool:
        """Tell whether the user has at least one of the roles.

        Args:
            roles: Accepted roles.

        Returns:
            bool: ``True`` if the user has one of ``roles``.
        """
        return not self.roles.isdisjoint(roles)


def build_token_verifier(
    oidc_settings: OidcSettings,
) -> AccessTokenVerifier:
    """Build a verifier that downloads and caches the signing keys of Keycloak.

    Args:
        oidc_settings: Issuer, audience and signing keys URL.

    Returns:
        AccessTokenVerifier: The verifier.
    """
    jwks_client: jwt.PyJWKClient = jwt.PyJWKClient(
        oidc_settings.jwks_url,
        cache_keys=True,
        lifespan=oidc_settings.signing_keys_cache_seconds,
    )
    return AccessTokenVerifier(
        issuer=oidc_settings.issuer,
        audience=oidc_settings.audience,
        resolve_signing_key=jwks_client.get_signing_key_from_jwt,
    )


@lru_cache
def get_token_verifier() -> AccessTokenVerifier:
    """FastAPI dependency giving the verifier of the process, built once.

    Returns:
        AccessTokenVerifier: The verifier.
    """
    return build_token_verifier(oidc_settings=get_settings().oidc)


def read_bearer_token(
    authorization: str | None,
) -> str | None:
    """Get the token of an ``Authorization: Bearer <token>`` header.

    Args:
        authorization: Value of the ``Authorization`` header, if any.

    Returns:
        str | None: The token, or ``None`` if the header is missing or not a bearer token.
    """
    has_bearer_token: bool = authorization is not None and authorization.startswith(BEARER_PREFIX)
    if not has_bearer_token:
        return None
    return str(authorization).removeprefix(BEARER_PREFIX)


def get_authenticated_user(
    token_verifier: Annotated[AccessTokenVerifier, Depends(get_token_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """FastAPI dependency giving the user of a request with a valid bearer token.

    Args:
        token_verifier: Verifier of access tokens.
        authorization: ``Authorization`` header of the request.

    Returns:
        AuthenticatedUser: The user.

    Raises:
        HTTPException: 401 if the token is missing or invalid, 503 if the signing keys
            cannot be fetched.
    """
    token: str | None = read_bearer_token(authorization=authorization)
    is_token_missing: bool = token is None
    if is_token_missing:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing bearer token", {"WWW-Authenticate": "Bearer"}
        )
    try:
        claims: dict[str, Any] = token_verifier.verify(str(token))
    except jwt.PyJWKClientConnectionError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Signing keys unavailable"
        ) from error
    except jwt.PyJWTError as error:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid token", {"WWW-Authenticate": "Bearer"}
        ) from error
    return AuthenticatedUser.from_claims(claims=claims)


def get_content_editor(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> AuthenticatedUser:
    """FastAPI dependency giving a user allowed to upload and manage images.

    Args:
        user: Authenticated user of the request.

    Returns:
        AuthenticatedUser: The user.

    Raises:
        HTTPException: 403 if the user has none of ``CONTENT_EDITOR_ROLES``.
    """
    is_content_editor: bool = user.has_any_role(roles=CONTENT_EDITOR_ROLES)
    if not is_content_editor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires a content generator role")
    return user
