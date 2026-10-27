"""Ingest jobs run by the worker."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test.conftest import ingest_upload, queue_upload, write_gradient

from cragradar_backend.core.settings import Settings
from cragradar_backend.ingest.staging import get_upload_path
from cragradar_backend.models.image import Image, ImageStatus
from cragradar_backend.worker.jobs import ClaimedImage, claim_next_image, process_image


def read_image(session_factory: async_sessionmaker[AsyncSession], image_id: uuid.UUID) -> Image:
    """Read an image row from the test database."""

    async def read() -> Image:
        """Read the row in a new session."""
        async with session_factory() as session:
            image: Image | None = await session.get(Image, image_id)
            assert image is not None
            return image

    return asyncio.run(read())


def test_upload_becomes_a_ready_image(
    work_dir: Path, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Check that the worker stores original and pyramid, records them and cleans staging."""
    image_id: uuid.UUID = ingest_upload(
        settings, session_factory, write_gradient(work_dir / "gradient.png")
    )

    image: Image = read_image(session_factory, image_id)
    assert image.status == ImageStatus.READY
    assert (image.width, image.height) == (1000, 600)
    assert image.version == 1
    assert str(image.original_path).endswith(f"{image_id}.original.png")
    assert str(image.pyramid_path).endswith(f"{image_id}.pyramid.tif")
    assert (settings.repository.base_root / str(image.pyramid_path)).is_file()
    assert not get_upload_path(settings.upload.staging_root, image_id).exists()


def test_unreadable_upload_fails(
    work_dir: Path, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Check that a file that is not an image is marked failed with a message."""
    text_path: Path = work_dir / "notes.png"
    text_path.write_text("not an image")

    image_id: uuid.UUID = ingest_upload(settings, session_factory, text_path)

    image: Image = read_image(session_factory, image_id)
    assert image.status == ImageStatus.FAILED
    assert image.error == "The file is not a readable image"


def test_empty_queue_gives_nothing_to_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Check that no image is claimed when none waits."""
    assert asyncio.run(claim_next_image(session_factory, lease_seconds=60)) is None


def test_claimed_image_is_not_claimed_twice(
    work_dir: Path, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Check that an image under a valid lease is left to its worker."""
    queue_upload(settings, session_factory, write_gradient(work_dir / "gradient.png"))

    first_claim: ClaimedImage | None = asyncio.run(claim_next_image(session_factory, 60))
    second_claim: ClaimedImage | None = asyncio.run(claim_next_image(session_factory, 60))

    assert first_claim is not None
    assert second_claim is None


def test_expired_lease_is_taken_over(
    work_dir: Path, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Check that an image whose worker stopped renewing its lease is processed again."""
    image_id: uuid.UUID = queue_upload(
        settings, session_factory, write_gradient(work_dir / "gradient.png")
    )
    asyncio.run(claim_next_image(session_factory, 60))

    async def expire_lease() -> None:
        """Move the lease of the image to the past."""
        async with session_factory() as session:
            await session.execute(
                update(Image)
                .where(Image.id == image_id)
                .values(lease_expires_at=datetime.now(tz=UTC) - timedelta(seconds=1))
            )
            await session.commit()

    asyncio.run(expire_lease())
    takeover_claim: ClaimedImage | None = asyncio.run(claim_next_image(session_factory, 60))

    assert takeover_claim is not None
    assert takeover_claim.image_id == image_id
    asyncio.run(process_image(session_factory, settings, takeover_claim))
    assert read_image(session_factory, image_id).status == ImageStatus.READY
