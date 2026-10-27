"""Resumable uploads with the tus protocol (https://tus.io), version 1.0.0.

Supports the core protocol and the ``creation`` extension, which is what tus clients such as
Uppy need:

- ``POST /api/uploads`` creates an upload and its image, and answers its URL in ``Location``.
- ``HEAD <upload URL>`` tells how many bytes were received, to resume after an interruption.
- ``PATCH <upload URL>`` appends bytes at the given offset.

When the last byte arrives the image becomes ``uploaded`` and waits for the worker.
"""

import base64
import binascii
import fcntl
import logging
import uuid
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from cragradar_backend.core.database import get_session
from cragradar_backend.core.security import AuthenticatedUser, get_content_editor
from cragradar_backend.core.settings import Settings, get_settings
from cragradar_backend.ingest.staging import get_upload_path
from cragradar_backend.models.image import Image, ImageStatus

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api/uploads", tags=["uploads"])

TUS_VERSION: str = "1.0.0"
TUS_CONTENT_TYPE: str = "application/offset+octet-stream"
DEFAULT_FILE_NAME: str = "image"
FILE_NAME_METADATA_KEYS: tuple[str, ...] = ("filename", "name")
"""Metadata keys that hold the file name; Uppy sends both."""


def build_tus_headers(
    **extra_headers: str,
) -> dict[str, str]:
    """Build the headers every tus response carries.

    Args:
        **extra_headers: Other headers, with ``_`` in their names written as ``-``.

    Returns:
        dict[str, str]: ``Tus-Resumable`` and the extra headers.
    """
    headers: dict[str, str] = {"Tus-Resumable": TUS_VERSION}
    headers.update(
        {name.replace("_", "-"): value for name, value in extra_headers.items()},
    )
    return headers


def check_tus_version(
    tus_resumable: str | None,
) -> None:
    """Reject requests of another tus version.

    Args:
        tus_resumable: ``Tus-Resumable`` header of the request.

    Raises:
        HTTPException: 412 if the version is not ``1.0.0``.
    """
    is_supported_version: bool = tus_resumable == TUS_VERSION
    if not is_supported_version:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            f"Only tus {TUS_VERSION} is supported",
            build_tus_headers(Tus_Version=TUS_VERSION),
        )


def read_file_name(
    upload_metadata: str | None,
) -> str:
    """Get the file name from an ``Upload-Metadata`` header.

    The header is a comma-separated list of ``key base64(value)`` pairs.

    Args:
        upload_metadata: ``Upload-Metadata`` header of the request, if any.

    Returns:
        str: The ``filename`` or ``name`` value, or ``image`` when neither is given.

    Raises:
        HTTPException: 400 if a value is not valid base64 or UTF-8.
    """
    metadata: dict[str, str] = {}
    pair: str
    for pair in (upload_metadata or "").split(","):
        key, _, encoded_value = pair.strip().partition(" ")
        try:
            metadata[key] = base64.b64decode(encoded_value, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError) as error:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Invalid Upload-Metadata value for {key!r}"
            ) from error
    file_name_key: str
    for file_name_key in FILE_NAME_METADATA_KEYS:
        file_name: str = metadata.get(file_name_key, "").strip()
        is_file_name_given: bool = file_name != ""
        if is_file_name_given:
            return file_name
    return DEFAULT_FILE_NAME


async def get_own_image(
    session: AsyncSession,
    image_id: uuid.UUID,
    user: AuthenticatedUser,
) -> Image:
    """Get an image uploaded by the user.

    Args:
        session: Database session.
        image_id: Image of the upload.
        user: User of the request.

    Returns:
        Image: The image.

    Raises:
        HTTPException: 404 if the image does not exist or was uploaded by someone else.
    """
    image: Image | None = await session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown upload", build_tus_headers())
    is_own_image: bool = image.created_by == user.subject
    if not is_own_image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown upload", build_tus_headers())
    return image


def get_received_size(
    image: Image,
    upload_path: Path,
) -> int:
    """Get how many bytes of an upload were received.

    Args:
        image: Image of the upload.
        upload_path: File receiving the upload.

    Returns:
        int: Size of the upload file while uploading; the full size once complete.
    """
    is_uploading: bool = image.status == ImageStatus.UPLOADING
    if not is_uploading:
        return image.size_bytes
    return upload_path.stat().st_size if upload_path.exists() else 0


@router.options("", status_code=status.HTTP_204_NO_CONTENT)
def describe_tus_server(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Tell tus clients which version, extensions and maximum size are supported.

    Args:
        settings: Settings of the backend.

    Returns:
        Response: Empty response with the tus capability headers.
    """
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers=build_tus_headers(
            Tus_Version=TUS_VERSION,
            Tus_Extension="creation",
            Tus_Max_Size=str(settings.upload.max_size_bytes),
        ),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_content_editor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_length: Annotated[int, Header(ge=1)],
    tus_resumable: Annotated[str | None, Header()] = None,
    upload_metadata: Annotated[str | None, Header()] = None,
) -> Response:
    """Create an upload and the image it belongs to.

    Args:
        request: Current request, used to build the upload URL.
        user: Content editor uploading the image.
        session: Database session.
        settings: Settings of the backend.
        upload_length: Total size of the upload in bytes (``Upload-Length``).
        tus_resumable: tus version of the client (``Tus-Resumable``).
        upload_metadata: ``Upload-Metadata`` header with the file name.

    Returns:
        Response: 201 with the upload URL in ``Location``.

    Raises:
        HTTPException: 412 for another tus version, 413 if the upload is larger than
            ``upload.max_size_bytes``, 400 for invalid metadata.
    """
    check_tus_version(tus_resumable=tus_resumable)
    is_too_large: bool = upload_length > settings.upload.max_size_bytes
    if is_too_large:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Uploads are limited to {settings.upload.max_size_bytes} bytes",
            build_tus_headers(),
        )

    image: Image = Image(
        id=uuid.uuid4(),
        file_name=read_file_name(upload_metadata=upload_metadata),
        size_bytes=upload_length,
        status=ImageStatus.UPLOADING,
        created_by=user.subject,
    )
    upload_path: Path = get_upload_path(
        staging_root=settings.upload.staging_root, image_id=image.id
    )
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.touch(exist_ok=False)
    session.add(image)
    await session.commit()
    logger.info("Upload %s of %r created by %s", image.id, image.file_name, user.subject)

    upload_url: str = str(request.url_for("append_to_upload", image_id=image.id))
    return Response(
        status_code=status.HTTP_201_CREATED,
        headers=build_tus_headers(Location=upload_url),
    )


@router.head("/{image_id}", name="read_upload_offset")
async def read_upload_offset(
    image_id: uuid.UUID,
    user: Annotated[AuthenticatedUser, Depends(get_content_editor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Tell how many bytes of an upload were received, so a client can resume it.

    Args:
        image_id: Image of the upload.
        user: Content editor who started the upload.
        session: Database session.
        settings: Settings of the backend.

    Returns:
        Response: Empty response with ``Upload-Offset`` and ``Upload-Length``.

    Raises:
        HTTPException: 404 if the upload does not exist or belongs to another user.
    """
    image: Image = await get_own_image(session=session, image_id=image_id, user=user)
    upload_path: Path = get_upload_path(
        staging_root=settings.upload.staging_root, image_id=image_id
    )
    return Response(
        status_code=status.HTTP_200_OK,
        headers=build_tus_headers(
            Upload_Offset=str(get_received_size(image=image, upload_path=upload_path)),
            Upload_Length=str(image.size_bytes),
            Cache_Control="no-store",
        ),
    )


@router.patch("/{image_id}", name="append_to_upload", status_code=status.HTTP_204_NO_CONTENT)
async def append_to_upload(
    image_id: uuid.UUID,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_content_editor)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_offset: Annotated[int, Header(ge=0)],
    content_type: Annotated[str | None, Header()] = None,
    tus_resumable: Annotated[str | None, Header()] = None,
) -> Response:
    """Append the request body to an upload, starting at ``Upload-Offset``.

    The body is written as it arrives. If the client disconnects, the bytes received so far
    are kept and the client resumes from the offset that ``HEAD`` reports.

    Args:
        image_id: Image of the upload.
        request: Current request, whose body is appended.
        user: Content editor who started the upload.
        session: Database session.
        settings: Settings of the backend.
        upload_offset: Offset the body starts at; it must equal the bytes received so far.
        content_type: Must be ``application/offset+octet-stream``.
        tus_resumable: tus version of the client.

    Returns:
        Response: 204 with the new ``Upload-Offset``.

    Raises:
        HTTPException: 412 for another tus version, 415 for another content type, 404 for
            an unknown upload, 409 if the upload is complete or the offset does not match,
            423 if another request is appending to the same upload, 413 if the body goes
            past the declared length.
    """
    check_tus_version(tus_resumable=tus_resumable)
    is_tus_content_type: bool = content_type == TUS_CONTENT_TYPE
    if not is_tus_content_type:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Content-Type must be {TUS_CONTENT_TYPE}",
            build_tus_headers(),
        )
    image: Image = await get_own_image(session=session, image_id=image_id, user=user)
    is_uploading: bool = image.status == ImageStatus.UPLOADING
    if not is_uploading:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Upload already complete", build_tus_headers()
        )

    upload_path: Path = get_upload_path(
        staging_root=settings.upload.staging_root, image_id=image_id
    )
    async with await anyio.open_file(upload_path, "r+b") as upload_file:
        try:
            fcntl.flock(upload_file.wrapped.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise HTTPException(
                status.HTTP_423_LOCKED, "Upload in progress elsewhere", build_tus_headers()
            ) from error

        received_size: int = upload_path.stat().st_size
        is_expected_offset: bool = upload_offset == received_size
        if not is_expected_offset:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Upload-Offset must be {received_size}",
                build_tus_headers(Upload_Offset=str(received_size)),
            )

        await upload_file.seek(received_size)
        written_size: int = received_size
        try:
            chunk: bytes
            async for chunk in request.stream():
                is_past_declared_length: bool = written_size + len(chunk) > image.size_bytes
                if is_past_declared_length:
                    await upload_file.truncate(received_size)
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        "Body goes past Upload-Length",
                        build_tus_headers(Upload_Offset=str(received_size)),
                    )
                await upload_file.write(chunk)
                written_size += len(chunk)
        except ClientDisconnect:
            logger.info("Upload %s interrupted at %d bytes", image_id, written_size)
        await upload_file.flush()

    is_complete: bool = written_size == image.size_bytes
    if is_complete:
        image.status = ImageStatus.UPLOADED
        await session.commit()
        logger.info("Upload %s complete: %d bytes", image_id, written_size)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers=build_tus_headers(Upload_Offset=str(written_size)),
    )
