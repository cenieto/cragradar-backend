import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cragradar_backend.api.main import app
from cragradar_backend.core.security import AccessTokenVerifier, get_token_verifier

ISSUER: str = "http://cragradar.test/auth/realms/cragradar"
AUDIENCE: str = "cragradar-backend"
TILE_AUTHZ_PATH: str = "/api/authz/tiles"

signing_private_key: rsa.RSAPrivateKey = rsa.generate_private_key(
    public_exponent=65537, key_size=2048
)
signing_public_jwk: jwt.PyJWK = jwt.PyJWK(
    jwt.algorithms.RSAAlgorithm.to_jwk(signing_private_key.public_key(), as_dict=True),
    algorithm="RS256",
)


def make_token(**claim_overrides: Any) -> str:
    now: int = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, signing_private_key, algorithm="RS256")


@pytest.fixture
def client() -> Iterator[TestClient]:
    test_verifier = AccessTokenVerifier(
        issuer=ISSUER, audience=AUDIENCE, resolve_signing_key=lambda token: signing_public_jwk
    )
    app.dependency_overrides[get_token_verifier] = lambda: test_verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def get_tile_authz(client: TestClient, token: str | None) -> int:
    headers: dict[str, str] = {} if token is None else {"Authorization": f"Bearer {token}"}
    return client.get(TILE_AUTHZ_PATH, headers=headers).status_code


def test_valid_token_is_granted(client: TestClient) -> None:
    assert get_tile_authz(client, make_token()) == 204


def test_missing_token_is_rejected(client: TestClient) -> None:
    assert get_tile_authz(client, None) == 401


def test_expired_token_is_rejected(client: TestClient) -> None:
    assert get_tile_authz(client, make_token(exp=int(time.time()) - 10)) == 401


def test_token_for_another_audience_is_rejected(client: TestClient) -> None:
    assert get_tile_authz(client, make_token(aud="account")) == 401


def test_token_from_another_issuer_is_rejected(client: TestClient) -> None:
    assert get_tile_authz(client, make_token(iss="http://evil.test/realms/x")) == 401
