"""Images and their processing state."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cragradar_backend.core.database import get_session
from cragradar_backend.core.security import AuthenticatedUser, get_content_editor
from cragradar_backend.models.image import Image, ImageStatus

router: APIRouter = APIRouter(prefix="/api/images", tags=["images"])


def build_descriptor_url(
    image: Image,
) -> str:
    """Build the URL of the Deep Zoom descriptor of an image, for OpenSeadragon.

    Args:
        image: Image with a built pyramid.

    Returns:
        str: ``/tiles/<id>/v<version>/image.dzi``.
    """
    return f"/tiles/{image.id}/v{image.version}/image.dzi"


class ImageRead(BaseModel):
    """An image as returned by the API.

    Attributes:
        id: Identifier.
        file_name: Name of the uploaded file.
        size_bytes: Size of the upload.
        status: Lifecycle state.
        width: Width in pixels, once ready.
        height: Height in pixels, once ready.
        version: Pyramid version.
        error: Why processing failed.
        dzi_url: Deep Zoom descriptor for OpenSeadragon, once ready.
        created_at: When the upload started.
    """

    id: uuid.UUID
    file_name: str
    size_bytes: int
    status: ImageStatus
    width: int | None
    height: int | None
    version: int
    error: str | None
    dzi_url: str | None
    created_at: datetime

    @classmethod
    def from_image(
        cls,
        image: Image,
    ) -> "ImageRead":
        """Build the API representation of an image.

        Args:
            image: Image row.

        Returns:
            ImageRead: The representation, with ``dzi_url`` set when the image is ready.
        """
        is_ready: bool = image.status == ImageStatus.READY
        return cls(
            id=image.id,
            file_name=image.file_name,
            size_bytes=image.size_bytes,
            status=image.status,
            width=image.width,
            height=image.height,
            version=image.version,
            error=image.error,
            dzi_url=build_descriptor_url(image=image) if is_ready else None,
            created_at=image.created_at,
        )


@router.get("")
async def list_images(
    user: Annotated[AuthenticatedUser, Depends(get_content_editor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ImageRead]:
    """List every image, newest first.

    Args:
        user: Content editor of the request.
        session: Database session.

    Returns:
        list[ImageRead]: The images.
    """
    images: list[Image] = list(
        (await session.scalars(select(Image).order_by(Image.created_at.desc()))).all()
    )
    return [ImageRead.from_image(image=image) for image in images]


@router.get("/{image_id}", responses={404: {"description": "Unknown image"}})
async def read_image(
    image_id: uuid.UUID,
    user: Annotated[AuthenticatedUser, Depends(get_content_editor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ImageRead:
    """Get one image, to follow its processing.

    Args:
        image_id: Image to get.
        user: Content editor of the request.
        session: Database session.

    Returns:
        ImageRead: The image.

    Raises:
        HTTPException: 404 if the image does not exist.
    """
    image: Image | None = await session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown image")
    return ImageRead.from_image(image=image)
