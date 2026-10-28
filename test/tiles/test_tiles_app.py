"""Deep Zoom descriptor and tiles of ready images."""

import asyncio
import uuid
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import pytest
import pyvips
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test.conftest import ingest_upload, queue_upload, write_gradient

from cragradar_backend.core.settings import Settings
from cragradar_backend.tiler.deepzoom import DEEP_ZOOM_NAMESPACE
from cragradar_backend.tiles.cache import PhysicalPyramidPathCache, get_path_cache
from cragradar_backend.tiles.main import app


@pytest.fixture
def ready_image_id(
    work_dir: Path, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> uuid.UUID:
    """Ingest a 1000x600 gradient and give its id."""
    image_id: uuid.UUID = ingest_upload(
        settings, session_factory, write_gradient(work_dir / "gradient.png")
    )
    return image_id


def test_descriptor_gives_the_image_size(
    tiles_client: TestClient, ready_image_id: uuid.UUID
) -> None:
    """Check that the descriptor of version 1 is served with the full size."""
    response: Response = tiles_client.get(f"/tiles/{ready_image_id}/v1/image.dzi")

    assert response.status_code == 200
    size_element: Any = ElementTree.fromstring(response.text).find(f"{{{DEEP_ZOOM_NAMESPACE}}}Size")
    assert size_element.attrib == {"Width": "1000", "Height": "600"}
    assert "cache-control" not in response.headers


def test_tile_is_cut_from_the_pyramid(tiles_client: TestClient, ready_image_id: uuid.UUID) -> None:
    """Check that a full-size and a reduced tile are served as JPEG of the expected size."""
    full_size_tile: Response = tiles_client.get(
        f"/tiles/{ready_image_id}/v1/image_files/10/0_0.jpeg"
    )
    reduced_tile: Response = tiles_client.get(f"/tiles/{ready_image_id}/v1/image_files/8/0_0.jpeg")

    assert full_size_tile.headers["content-type"] == "image/jpeg"
    full_size_image: Any = pyvips.Image.new_from_buffer(full_size_tile.content, "")
    reduced_image: Any = pyvips.Image.new_from_buffer(reduced_tile.content, "")
    assert (full_size_image.width, full_size_image.height) == (255, 255)
    assert (reduced_image.width, reduced_image.height) == (250, 150)


def test_other_version_is_not_served(tiles_client: TestClient, ready_image_id: uuid.UUID) -> None:
    """Check that a version other than the current one is answered 404."""
    assert tiles_client.get(f"/tiles/{ready_image_id}/v2/image.dzi").status_code == 404


def test_other_format_is_not_served(tiles_client: TestClient, ready_image_id: uuid.UUID) -> None:
    """Check that a tile in another format than the configured one is answered 404."""
    response: Response = tiles_client.get(f"/tiles/{ready_image_id}/v1/image_files/8/0_0.png")
    assert response.status_code == 404


def test_image_not_ready_is_not_served(
    work_dir: Path,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tiles_client: TestClient,
) -> None:
    """Check that an image waiting for the worker is answered 404."""
    image_id: uuid.UUID = queue_upload(
        settings, session_factory, write_gradient(work_dir / "gradient.png")
    )
    assert tiles_client.get(f"/tiles/{image_id}/v0/image.dzi").status_code == 404


def test_unknown_image_is_not_served(tiles_client: TestClient) -> None:
    """Check that an unknown image is answered 404."""
    assert tiles_client.get(f"/tiles/{uuid.uuid4()}/v1/image.dzi").status_code == 404


def test_pyramid_path_is_read_from_the_injected_cache(
    tiles_client: TestClient, ready_image_id: uuid.UUID
) -> None:
    """Check that the first request fills the cache given by ``get_path_cache``."""
    path_cache: PhysicalPyramidPathCache = app.dependency_overrides[get_path_cache]()

    tiles_client.get(f"/tiles/{ready_image_id}/v1/image.dzi")

    cached_path: Path | None = asyncio.run(path_cache.get(image_id=ready_image_id, version=1))
    assert cached_path is not None
    assert cached_path.name == f"{ready_image_id}.pyramid.tif"
