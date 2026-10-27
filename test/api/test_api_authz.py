"""Authorization of tile requests by the nginx tile cache."""

import time

from fastapi.testclient import TestClient
from test.conftest import bearer, make_token

TILE_AUTHZ_PATH: str = "/api/authz/tiles"


def test_valid_token_is_granted(api_client: TestClient) -> None:
    """Check that a valid token is answered 204."""
    assert api_client.get(TILE_AUTHZ_PATH, headers=bearer(make_token())).status_code == 204


def test_missing_token_is_rejected(api_client: TestClient) -> None:
    """Check that a request without token is answered 401."""
    assert api_client.get(TILE_AUTHZ_PATH).status_code == 401


def test_expired_token_is_rejected(api_client: TestClient) -> None:
    """Check that an expired token is answered 401."""
    expired_token: str = make_token(exp=int(time.time()) - 10)
    assert api_client.get(TILE_AUTHZ_PATH, headers=bearer(expired_token)).status_code == 401


def test_token_for_another_audience_is_rejected(api_client: TestClient) -> None:
    """Check that a token issued for another client is answered 401."""
    other_audience_token: str = make_token(aud="account")
    assert api_client.get(TILE_AUTHZ_PATH, headers=bearer(other_audience_token)).status_code == 401


def test_token_from_another_issuer_is_rejected(api_client: TestClient) -> None:
    """Check that a token of another issuer is answered 401."""
    other_issuer_token: str = make_token(iss="http://evil.test/realms/x")
    assert api_client.get(TILE_AUTHZ_PATH, headers=bearer(other_issuer_token)).status_code == 401
