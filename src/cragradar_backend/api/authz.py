"""Authorization of tile requests, called by the nginx tile cache through ``auth_request``.

nginx caches each answer for a short time per token and image, so this endpoint is not called for
every tile.
"""

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, Response, status

from cragradar_backend.core.security import AccessTokenVerifier, get_token_verifier

router: APIRouter = APIRouter(prefix="/api/authz", tags=["authz"])

BEARER_PREFIX: str = "Bearer "


def reject_as_unauthenticated() -> Response:
    return Response(
        status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
    )


@router.get("/tiles", status_code=status.HTTP_204_NO_CONTENT)
def authorize_tile_request(
    token_verifier: Annotated[AccessTokenVerifier, Depends(get_token_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """204 grants access to the tile, 401 rejects a missing or invalid token."""
    has_bearer_token: bool = authorization is not None and authorization.startswith(BEARER_PREFIX)
    if not has_bearer_token or authorization is None:
        return reject_as_unauthenticated()
    token: str = authorization.removeprefix(BEARER_PREFIX)
    try:
        token_verifier.verify(token)
    except jwt.PyJWKClientConnectionError:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except jwt.PyJWTError:
        return reject_as_unauthenticated()
    # TODO: when tags are stored, also require that the user shares at least one tag with the
    # image (the nginx tile cache sends its id in X-Tile-Image-Id), and answer 403 otherwise.
    # Until then every authenticated user can read every tile.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
