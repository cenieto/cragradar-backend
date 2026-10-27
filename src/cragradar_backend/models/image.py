"""Images: uploads and the pyramids the worker builds from them."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Enum, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from cragradar_backend.models.base import Base


class ImageStatus(StrEnum):
    """Lifecycle of an image."""

    UPLOADING = "uploading"
    """The upload has started and is not complete."""
    UPLOADED = "uploaded"
    """The upload is complete and waits for the worker."""
    PROCESSING = "processing"
    """A worker is building the pyramid."""
    READY = "ready"
    """The pyramid is built and tiles can be served."""
    FAILED = "failed"
    """The pyramid could not be built; ``error`` tells why."""


class Image(Base):
    """An uploaded image.

    Attributes:
        id: Identifier, also used in upload and tile URLs.
        file_name: Name of the uploaded file.
        size_bytes: Size of the upload.
        status: Lifecycle state.
        width: Width in pixels, once the pyramid is built.
        height: Height in pixels, once the pyramid is built.
        original_path: Path of the original in the repository.
        pyramid_path: Path of the pyramidal TIFF in the repository.
        version: Incremented each time a pyramid is built. Tile URLs contain it, so cached
            tiles never go stale.
        error: Why the pyramid could not be built.
        lease_expires_at: While processing, when the worker lease ends.
        created_by: Keycloak id of the uploader.
        created_at: When the upload started.
        updated_at: Last change.
    """

    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_name: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[ImageStatus] = mapped_column(
        Enum(
            ImageStatus,
            native_enum=False,
            length=16,
            create_constraint=True,
            name="image_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=ImageStatus.UPLOADING,
        index=True,
    )
    width: Mapped[int | None]
    height: Mapped[int | None]
    original_path: Mapped[str | None] = mapped_column(Text)
    pyramid_path: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
