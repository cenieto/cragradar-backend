"""Images and their processing state."""

import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test.conftest import bearer, ingest_upload, make_token, queue_upload, write_gradient

from cragradar_backend.core.settings import Settings

EDITOR_HEADERS: dict[str, str] = bearer(make_token(roles=("content_generator",)))


def test_ready_image_gives_its_descriptor_url(
    work_dir: Path,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    api_client: TestClient,
) -> None:
    """Check that a ready image has its size and the versioned descriptor URL."""
    image_id: uuid.UUID = ingest_upload(
        settings, session_factory, write_gradient(work_dir / "gradient.png")
    )

    image: dict[str, Any] = api_client.get(f"/api/images/{image_id}", headers=EDITOR_HEADERS).json()

    assert image["status"] == "ready"
    assert (image["width"], image["height"]) == (1000, 600)
    assert image["dzi_url"] == f"/tiles/{image_id}/v1/image.dzi"


def test_waiting_image_has_no_descriptor_url(
    work_dir: Path,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    api_client: TestClient,
) -> None:
    """Check that an image waiting for the worker is listed without descriptor URL."""
    queue_upload(settings, session_factory, write_gradient(work_dir / "gradient.png"))

    images: list[dict[str, Any]] = api_client.get("/api/images", headers=EDITOR_HEADERS).json()

    assert [image["status"] for image in images] == ["uploaded"]
    assert images[0]["dzi_url"] is None


def test_unknown_image_is_not_found(api_client: TestClient) -> None:
    """Check that an unknown image is answered 404."""
    response: Any = api_client.get(f"/api/images/{uuid.uuid4()}", headers=EDITOR_HEADERS)
    assert response.status_code == 404


def test_viewer_cannot_list_images(api_client: TestClient) -> None:
    """Check that a user without a content role is answered 403."""
    viewer_headers: dict[str, str] = bearer(make_token(roles=("viewer",)))
    assert api_client.get("/api/images", headers=viewer_headers).status_code == 403
