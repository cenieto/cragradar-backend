"""In-process cache of pyramid paths."""

import asyncio
import uuid
from pathlib import Path

from cragradar_backend.tiles.cache import (
    PhysicalPyramidPathCache,
    PyramidPathCache,
    get_path_cache,
)

FIRST_IMAGE_ID: uuid.UUID = uuid.UUID(int=1)
SECOND_IMAGE_ID: uuid.UUID = uuid.UUID(int=2)
THIRD_IMAGE_ID: uuid.UUID = uuid.UUID(int=3)


def put_path(
    cache: PyramidPathCache, image_id: uuid.UUID, version: int, pyramid_path: Path
) -> None:
    """Store a path in the cache."""
    asyncio.run(cache.put(image_id=image_id, version=version, pyramid_path=pyramid_path))


def get_path(cache: PyramidPathCache, image_id: uuid.UUID, version: int) -> Path | None:
    """Read a path from the cache."""
    return asyncio.run(cache.get(image_id=image_id, version=version))


def test_missing_path_is_none() -> None:
    """Check that an image never cached gives ``None``."""
    assert get_path(PhysicalPyramidPathCache(max_entries=2), FIRST_IMAGE_ID, 1) is None


def test_cached_path_is_returned_for_its_version_only() -> None:
    """Check that a path is found for its image and version, not for another version."""
    cache: PhysicalPyramidPathCache = PhysicalPyramidPathCache(max_entries=2)
    put_path(cache, FIRST_IMAGE_ID, 1, Path("/data/images/first.pyramid.tif"))

    assert get_path(cache, FIRST_IMAGE_ID, 1) == Path("/data/images/first.pyramid.tif")
    assert get_path(cache, FIRST_IMAGE_ID, 2) is None


def test_oldest_path_is_dropped_when_full() -> None:
    """Check that the first stored path is dropped when a path beyond ``max_entries`` arrives."""
    cache: PhysicalPyramidPathCache = PhysicalPyramidPathCache(max_entries=2)
    put_path(cache, FIRST_IMAGE_ID, 1, Path("/first.tif"))
    put_path(cache, SECOND_IMAGE_ID, 1, Path("/second.tif"))
    put_path(cache, THIRD_IMAGE_ID, 1, Path("/third.tif"))

    assert get_path(cache, FIRST_IMAGE_ID, 1) is None
    assert get_path(cache, SECOND_IMAGE_ID, 1) == Path("/second.tif")
    assert get_path(cache, THIRD_IMAGE_ID, 1) == Path("/third.tif")


def test_dependency_gives_the_process_cache() -> None:
    """Check that ``get_path_cache`` gives the same in-process cache to every request."""
    assert isinstance(get_path_cache(), PhysicalPyramidPathCache)
    assert get_path_cache() is get_path_cache()
