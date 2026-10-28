"""Authorization of tile requests, called by the nginx tile cache through ``auth_request``.

nginx caches each answer for a short time per token and image, so this endpoint is not called
for every tile.
"""

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, Response, status

from cragradar_backend.core.security import (
    AccessTokenVerifier,
    get_token_verifier,
    read_bearer_token,
)

router: APIRouter = APIRouter(prefix="/api/authz", tags=["authz"])


def reject_as_unauthenticated() -> Response:
    """Build the answer to a missing or invalid token.

    Returns:
        Response: 401 with ``WWW-Authenticate: Bearer``.
    """
    return Response(
        status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
    )


@router.get("/tiles", status_code=status.HTTP_204_NO_CONTENT)
def authorize_tile_request(
    token_verifier: Annotated[AccessTokenVerifier, Depends(get_token_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Grant or reject a tile request.

    Args:
        token_verifier: Verifier of access tokens.
        authorization: ``Authorization`` header of the tile request.

    Returns:
        Response: 204 grants access, 401 rejects a missing or invalid token, 503 tells that
            the signing keys cannot be fetched.
    """
    token: str | None = read_bearer_token(authorization=authorization)
    is_token_missing: bool = token is None
    if is_token_missing:
        return reject_as_unauthenticated()

    try:
        token_verifier.verify(str(token))
    except jwt.PyJWKClientConnectionError:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except jwt.PyJWTError:
        return reject_as_unauthenticated()
    # TODO: when tags are stored, also require that the user shares at least one tag with the
    # image (the nginx tile cache sends its id in X-Tile-Image-Id), and answer 403 otherwise.
    # Until then every authenticated user can read every tile.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
