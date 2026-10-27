"""Ingest jobs: build the pyramid of each uploaded image.

The ``images`` table is the queue. A worker claims an image with ``FOR UPDATE SKIP LOCKED``,
so concurrent workers never take the same one, and holds it with a lease that it renews while
working. If the worker dies, the lease expires and another worker takes the image over.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cragradar_backend.core.settings import Settings
from cragradar_backend.ingest.pyramid import build_pyramid
from cragradar_backend.ingest.staging import get_pyramid_scratch_path, get_upload_path
from cragradar_backend.models.image import Image, ImageStatus
from cragradar_backend.repos.abcs import RepositoryAbstract
from cragradar_backend.tiler.abcs import ImageSize
from cragradar_backend.tiler.errors import UnreadableImageError

logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedImage:
    """Image assigned to this worker.

    Attributes:
        image_id: Identifier of the image.
        file_name: Name of the uploaded file, whose extension the stored original keeps.
    """

    image_id: uuid.UUID
    file_name: str


def utc_now() -> datetime:
    """Return the current time in UTC.

    Returns:
        datetime: Timezone-aware current time.
    """
    return datetime.now(tz=UTC)


async def claim_next_image(
    session_factory: async_sessionmaker[AsyncSession],
    lease_seconds: int,
) -> ClaimedImage | None:
    """Assign the oldest waiting image to this worker.

    An image waits when its upload is complete, or when the lease of the worker that was
    processing it has expired.

    Args:
        session_factory: Factory of database sessions.
        lease_seconds: Duration of the lease.

    Returns:
        ClaimedImage | None: The claimed image, or ``None`` if no image waits.
    """
    now: datetime = utc_now()
    async with session_factory() as session:
        image: Image | None = await session.scalar(
            select(Image)
            .where(
                or_(
                    Image.status == ImageStatus.UPLOADED,
                    (Image.status == ImageStatus.PROCESSING) & (Image.lease_expires_at < now),
                )
            )
            .order_by(Image.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if image is None:
            return None
        image.status = ImageStatus.PROCESSING
        image.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await session.commit()
        return ClaimedImage(image_id=image.id, file_name=image.file_name)


async def renew_lease(
    session_factory: async_sessionmaker[AsyncSession],
    image_id: uuid.UUID,
    lease_seconds: int,
) -> None:
    """Extend the lease of an image every third of its duration, until cancelled.

    Args:
        session_factory: Factory of database sessions.
        image_id: Image being processed.
        lease_seconds: Duration of the lease.
    """
    while True:
        await asyncio.sleep(lease_seconds / 3)
        async with session_factory() as session:
            await session.execute(
                update(Image)
                .where(Image.id == image_id, Image.status == ImageStatus.PROCESSING)
                .values(lease_expires_at=utc_now() + timedelta(seconds=lease_seconds))
            )
            await session.commit()


def store_image_files(
    repository: RepositoryAbstract,
    upload_path: Path,
    pyramid_path: Path,
    claimed_image: ClaimedImage,
) -> tuple[Path, Path]:
    """Store the original and the pyramid of an image in the repository.

    Args:
        repository: Repository of originals and pyramids.
        upload_path: Received upload.
        pyramid_path: Pyramid written by ``build_pyramid``.
        claimed_image: Image the files belong to.

    Returns:
        tuple[Path, Path]: Paths of the original and the pyramid inside the repository.

    Raises:
        RepositoryError: If a file cannot be stored.
    """
    original_suffix: str = Path(claimed_image.file_name).suffix.lower()
    with upload_path.open("rb") as upload_file:
        original_path: Path = repository.save(
            upload_file,
            file_name=f"{claimed_image.image_id}.original{original_suffix}",
            overwrite=True,
        )
    with pyramid_path.open("rb") as pyramid_file:
        stored_pyramid_path: Path = repository.save(
            pyramid_file,
            file_name=f"{claimed_image.image_id}.pyramid.tif",
            overwrite=True,
        )
    return original_path, stored_pyramid_path


async def mark_image_failed(
    session_factory: async_sessionmaker[AsyncSession],
    image_id: uuid.UUID,
    error_message: str,
) -> None:
    """Record that the pyramid of an image could not be built.

    Args:
        session_factory: Factory of database sessions.
        image_id: Image that failed.
        error_message: Why it failed, shown to the uploader.
    """
    async with session_factory() as session:
        await session.execute(
            update(Image)
            .where(Image.id == image_id)
            .values(status=ImageStatus.FAILED, error=error_message, lease_expires_at=None)
        )
        await session.commit()


async def process_image(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    claimed_image: ClaimedImage,
) -> None:
    """Build and store the pyramid of a claimed image, then mark it ready or failed.

    The staging files are deleted once the image is ready, or when it is not a readable
    image. They are kept after other errors, so the image can be processed again.

    Args:
        session_factory: Factory of database sessions.
        settings: Settings of the backend.
        claimed_image: Image to process.
    """
    image_id: uuid.UUID = claimed_image.image_id
    staging_root: Path = settings.upload.staging_root
    upload_path: Path = get_upload_path(staging_root=staging_root, image_id=image_id)
    scratch_pyramid_path: Path = get_pyramid_scratch_path(
        staging_root=staging_root, image_id=image_id
    )
    lease_renewal: asyncio.Task[None] = asyncio.create_task(
        renew_lease(
            session_factory=session_factory,
            image_id=image_id,
            lease_seconds=settings.worker.lease_seconds,
        )
    )
    try:
        logger.info("Building the pyramid of %s", image_id)
        image_size: ImageSize = await asyncio.to_thread(
            build_pyramid,
            source_path=upload_path,
            target_path=scratch_pyramid_path,
            pyramid_settings=settings.pyramid,
        )
        original_path, pyramid_path = await asyncio.to_thread(
            store_image_files,
            repository=settings.repository,
            upload_path=upload_path,
            pyramid_path=scratch_pyramid_path,
            claimed_image=claimed_image,
        )
    except UnreadableImageError as error:
        logger.warning("Image %s is not readable: %s", image_id, error)
        await mark_image_failed(
            session_factory=session_factory,
            image_id=image_id,
            error_message="The file is not a readable image",
        )
        upload_path.unlink(missing_ok=True)
        scratch_pyramid_path.unlink(missing_ok=True)
        return
    except Exception as error:
        logger.exception("Image %s could not be processed", image_id)
        await mark_image_failed(
            session_factory=session_factory, image_id=image_id, error_message=str(error)
        )
        return
    finally:
        lease_renewal.cancel()

    async with session_factory() as session:
        await session.execute(
            update(Image)
            .where(Image.id == image_id)
            .values(
                status=ImageStatus.READY,
                width=image_size.width,
                height=image_size.height,
                original_path=original_path.as_posix(),
                pyramid_path=pyramid_path.as_posix(),
                version=Image.version + 1,
                error=None,
                lease_expires_at=None,
            )
        )
        await session.commit()
    upload_path.unlink(missing_ok=True)
    scratch_pyramid_path.unlink(missing_ok=True)
    logger.info("Image %s ready: %dx%d", image_id, image_size.width, image_size.height)


async def run_worker(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Process waiting images one at a time, forever.

    Args:
        session_factory: Factory of database sessions.
        settings: Settings of the backend.
    """
    logger.info("Worker started")
    while True:
        claimed_image: ClaimedImage | None = await claim_next_image(
            session_factory=session_factory, lease_seconds=settings.worker.lease_seconds
        )
        if claimed_image is None:
            await asyncio.sleep(settings.worker.poll_interval_seconds)
            continue
        await process_image(
            session_factory=session_factory, settings=settings, claimed_image=claimed_image
        )
