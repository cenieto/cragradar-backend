"""Caches of the physical paths of pyramids, by image and version.

A version of an image never changes its pyramid, so cached paths never go stale. The tile
server gets its cache through the ``get_path_cache`` dependency, so another implementation,
such as one backed by Redis and shared by every tile server replica, only replaces that
function.
"""

import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

PYRAMID_PATH_CACHE_SIZE: int = 4096


class PyramidPathCache(Protocol):
    """Cache of the physical paths of pyramids, by image and version.

    Methods are asynchronous so that implementations can call a network service.
    """

    async def get(
        self,
        image_id: uuid.UUID,
        version: int,
    ) -> Path | None:
        """Get a cached path.

        Args:
            image_id: Image of the pyramid.
            version: Version of the pyramid.

        Returns:
            Path | None: The path, or ``None`` if it is not cached.
        """
        ...

    async def put(
        self,
        image_id: uuid.UUID,
        version: int,
        pyramid_path: Path,
    ) -> None:
        """Cache a path.

        Args:
            image_id: Image of the pyramid.
            version: Version of the pyramid.
            pyramid_path: Physical path of the pyramid.
        """
        ...


class PhysicalPyramidPathCache:
    """Cache kept in the memory of the process, which drops the oldest paths when full.

    Each tile server process has its own cache, filled by its first request for each image.
    """

    def __init__(
        self,
        max_entries: int,
    ) -> None:
        """Create an empty cache.

        Args:
            max_entries: Number of paths kept.
        """
        self.max_entries: int = max_entries
        self._paths: OrderedDict[tuple[uuid.UUID, int], Path] = OrderedDict()

    async def get(
        self,
        image_id: uuid.UUID,
        version: int,
    ) -> Path | None:
        """Get a cached path.

        Args:
            image_id: Image of the pyramid.
            version: Version of the pyramid.

        Returns:
            Path | None: The path, or ``None`` if it is not cached.
        """
        return self._paths.get((image_id, version))

    async def put(
        self,
        image_id: uuid.UUID,
        version: int,
        pyramid_path: Path,
    ) -> None:
        """Cache a path, dropping the oldest one when full.

        Args:
            image_id: Image of the pyramid.
            version: Version of the pyramid.
            pyramid_path: Physical path of the pyramid.
        """
        self._paths[(image_id, version)] = pyramid_path
        is_full: bool = len(self._paths) > self.max_entries
        if is_full:
            self._paths.popitem(last=False)


physical_pyramid_path_cache: PhysicalPyramidPathCache = PhysicalPyramidPathCache(
    max_entries=PYRAMID_PATH_CACHE_SIZE
)


def get_path_cache() -> PyramidPathCache:
    """FastAPI dependency giving the pyramid path cache of the tile server.

    Returns:
        PyramidPathCache: The in-process cache, shared by every request of the process.
    """
    return physical_pyramid_path_cache
