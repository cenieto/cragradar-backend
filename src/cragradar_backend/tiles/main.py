"""ASGI app of the CragRadar tile server. All routes live under ``/tiles``.

Serves the Deep Zoom descriptor and tiles of ready images, cut on demand from their pyramidal
TIFF:

- ``/tiles/<image id>/v<version>/image.dzi``
- ``/tiles/<image id>/v<version>/image_files/<level>/<column>_<row>.<format>``

The nginx tile cache in front authorizes every request and caches the answers. Responses
carry no ``Cache-Control``: nginx sets the one the browser sees.
"""

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from cragradar_backend.core.database import get_session
from cragradar_backend.core.settings import Settings, get_settings
from cragradar_backend.models.image import Image, ImageStatus
from cragradar_backend.repos.abcs import RepositoryAbstract
from cragradar_backend.repos.errors import StoredFileNotFoundError
from cragradar_backend.tiler.abcs import TilerAbstract
from cragradar_backend.tiler.errors import TileNotFoundError, UnreadableImageError
from cragradar_backend.tiles.cache import PyramidPathCache, get_path_cache

app: FastAPI = FastAPI(title="CragRadar tiles", docs_url=None, redoc_url=None, openapi_url=None)


async def resolve_pyramid_path(
    image_id: uuid.UUID,
    version: int,
    session: AsyncSession,
    repository: RepositoryAbstract,
    path_cache: PyramidPathCache,
) -> Path:
    """Get the physical path of the pyramid of a ready image version.

    Args:
        image_id: Image of the pyramid.
        version: Requested version; only the current version of a ready image is served.
        session: Database session, used when the path is not cached.
        repository: Repository that stores the pyramids.
        path_cache: Cache of pyramid paths, read first and filled after a database lookup.

    Returns:
        Path: Physical path of the pyramid.

    Raises:
        HTTPException: 404 if the image does not exist, is not ready, or is at another
            version.
    """
    cached_path: Path | None = await path_cache.get(image_id=image_id, version=version)
    if cached_path is not None:
        return cached_path

    image: Image | None = await session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown image")
    is_requested_ready_version: bool = (
        image.status == ImageStatus.READY
        and image.version == version
        and image.pyramid_path is not None
    )
    if not is_requested_ready_version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image version not available")
    try:
        pyramid_path: Path = repository.resolve_path(
            url=repository.build_url(Path(str(image.pyramid_path)))
        )
    except StoredFileNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pyramid not stored") from error
    await path_cache.put(image_id=image_id, version=version, pyramid_path=pyramid_path)
    return pyramid_path


@app.get("/tiles/healthz")
def read_health() -> dict[str, str]:
    """Liveness and readiness probe."""
    return {"status": "ok", "service": "tiles"}


@app.get(
    "/tiles/{image_id}/v{version:int}/image.dzi",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}, 404: {}},
)
async def describe_image(
    image_id: uuid.UUID,
    version: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    path_cache: Annotated[PyramidPathCache, Depends(get_path_cache)],
) -> Response:
    """Return the Deep Zoom descriptor of an image, to give to OpenSeadragon.

    Args:
        image_id: Image to describe.
        version: Pyramid version.
        session: Database session.
        settings: Settings of the backend.
        path_cache: Cache of pyramid paths.

    Returns:
        Response: The ``.dzi`` XML document.

    Raises:
        HTTPException: 404 if the image version is not available, 422 if its pyramid is not
            readable.
    """
    tiler: TilerAbstract = settings.tiler
    pyramid_path: Path = await resolve_pyramid_path(
        image_id=image_id,
        version=version,
        session=session,
        repository=settings.repository,
        path_cache=path_cache,
    )
    try:
        descriptor: str = await run_in_threadpool(tiler.describe, image_path=pyramid_path)
    except UnreadableImageError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return Response(content=descriptor, media_type=tiler.descriptor_media_type)


@app.get(
    "/tiles/{image_id}/v{version:int}/image_files/{level:int}/{column:int}_{row:int}.{extension}",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}, 404: {}},
)
async def get_tile(
    image_id: uuid.UUID,
    version: int,
    level: int,
    column: int,
    row: int,
    extension: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    path_cache: Annotated[PyramidPathCache, Depends(get_path_cache)],
) -> Response:
    """Cut one Deep Zoom tile of an image.

    Args:
        image_id: Image of the tile.
        version: Pyramid version.
        level: Deep Zoom level, from ``0`` (one pixel) to the full-size level.
        column: Column of the tile.
        row: Row of the tile.
        extension: Tile format, which must match the configured one.
        session: Database session.
        settings: Settings of the backend.
        path_cache: Cache of pyramid paths.

    Returns:
        Response: The encoded tile.

    Raises:
        HTTPException: 404 if the image version is not available, the tile does not exist
            or the extension is not the configured format; 422 if the pyramid is not
            readable.
    """
    tiler: TilerAbstract = settings.tiler
    is_configured_extension: bool = extension == tiler.tile_format
    if not is_configured_extension:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tiles are not served in that format")
    pyramid_path: Path = await resolve_pyramid_path(
        image_id=image_id,
        version=version,
        session=session,
        repository=settings.repository,
        path_cache=path_cache,
    )
    try:
        tile: bytes = await run_in_threadpool(
            tiler.get_tile, image_path=pyramid_path, level=level, column=column, row=row
        )
    except TileNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except UnreadableImageError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return Response(content=tile, media_type=tiler.media_type)
