"""Deep Zoom tiles cut on demand from a stored image, as read by OpenSeadragon.

A Deep Zoom image has one level per halving of its size. The last level,
``max_level = ceil(log2(max(width, height)))``, is the full image, and level ``0`` is a
single pixel. Each level is cut into square tiles of ``tile_size`` pixels that overlap
their neighbours by ``overlap`` pixels.
"""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyvips
from pydantic import Field

from cragradar_backend.racker.registry import racker
from cragradar_backend.tiler.abcs import ImageSize, TilerAbstract, TilerConfigAbstract
from cragradar_backend.tiler.errors import TileNotFoundError, UnreadableImageError

DEEP_ZOOM_NAMESPACE: str = "http://schemas.microsoft.com/deepzoom/2008"


class DeepZoomTilerConfig(TilerConfigAbstract):
    """Configuration of ``DeepZoomTiler``: how Deep Zoom tiles are cut and encoded.

    Attributes:
        tile_size: Width and height of a tile in pixels, without overlap.
        overlap: Pixels each tile shares with its neighbours.
        format: Image format of the tiles, also used as their file extension.
        jpeg_quality: Quality of JPEG tiles, from 1 to 100.
    """

    type: Literal["deepzoom"] = "deepzoom"
    tile_size: int = Field(default=254, gt=0)
    overlap: int = Field(default=1, ge=0)
    format: Literal["jpeg", "png"] = "jpeg"
    jpeg_quality: int = Field(default=90, ge=1, le=100)


@dataclass(frozen=True)
class TileBounds:
    """Region of a level covered by one tile, overlap included.

    Attributes:
        left: First column of pixels.
        top: First row of pixels.
        width: Width in pixels.
        height: Height in pixels.
    """

    left: int
    top: int
    width: int
    height: int


class DeepZoomTiler(TilerAbstract):
    """Describe images and cut their Deep Zoom tiles when they are requested."""

    def __init__(
        self,
        config: DeepZoomTilerConfig,
    ) -> None:
        """Initialize the Deep Zoom tiler with a configuration object.

        Args:
            config: How tiles are cut and encoded.
        """
        super().__init__(config=config)
        self.tile_settings: DeepZoomTilerConfig = config

    @property
    def tile_format(
        self,
    ) -> str:
        """Return the image format of the tiles, also used as their file extension.

        Returns:
            str: ``jpeg`` or ``png``.
        """
        return self.tile_settings.format

    @property
    def descriptor_media_type(
        self,
    ) -> str:
        """Return the media type of the ``.dzi`` descriptor.

        Returns:
            str: ``application/xml``.
        """
        return "application/xml"

    @property
    def media_type(
        self,
    ) -> str:
        """Return the media type of the tiles.

        Returns:
            str: ``image/jpeg`` or ``image/png``.
        """
        return f"image/{self.tile_settings.format}"

    def read_size(
        self,
        image_path: Path,
    ) -> ImageSize:
        """Read the size of an image without decoding its pixels.

        Args:
            image_path: Path of the image.

        Returns:
            ImageSize: Width and height of the image.

        Raises:
            UnreadableImageError: If the file is not an image libvips can read.
        """
        image: Any = self._open_image(image_path=image_path)
        return ImageSize(width=int(image.width), height=int(image.height))

    def describe(
        self,
        image_path: Path,
    ) -> str:
        """Build the Deep Zoom descriptor (``.dzi``) of an image.

        Args:
            image_path: Path of the image.

        Returns:
            str: XML document with the tile size, overlap, format and image size.

        Raises:
            UnreadableImageError: If the file is not an image libvips can read.
        """
        image_size: ImageSize = self.read_size(image_path=image_path)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Image xmlns="{DEEP_ZOOM_NAMESPACE}" '
            f'Format="{self.tile_settings.format}" '
            f'Overlap="{self.tile_settings.overlap}" '
            f'TileSize="{self.tile_settings.tile_size}">'
            f'<Size Width="{image_size.width}" Height="{image_size.height}"/>'
            "</Image>\n"
        )

    @staticmethod
    def get_max_level(
        image_size: ImageSize,
    ) -> int:
        """Get the level that holds the image at full size.

        Args:
            image_size: Size of the image.

        Returns:
            int: ``ceil(log2(max(width, height)))``; ``0`` for a 1x1 image.
        """
        longest_side: int = max(image_size.width, image_size.height)
        return math.ceil(math.log2(longest_side))

    def get_level_size(
        self,
        image_size: ImageSize,
        level: int,
    ) -> ImageSize:
        """Get the size of the image at a level.

        Args:
            image_size: Size of the image at full size.
            level: Deep Zoom level.

        Returns:
            ImageSize: Size at ``level``; each level below the last halves it, rounding up.

        Raises:
            TileNotFoundError: If the level is negative or above the last level.
        """
        max_level: int = self.get_max_level(image_size=image_size)
        is_level_in_range: bool = 0 <= level <= max_level
        if not is_level_in_range:
            raise TileNotFoundError(f"Level {level} is not between 0 and {max_level}")

        scale_divisor: int = 2 ** (max_level - level)
        return ImageSize(
            width=math.ceil(image_size.width / scale_divisor),
            height=math.ceil(image_size.height / scale_divisor),
        )

    def get_tile_bounds(
        self,
        level_size: ImageSize,
        column: int,
        row: int,
    ) -> TileBounds:
        """Get the region of a level covered by a tile, overlap included.

        Args:
            level_size: Size of the image at the level of the tile.
            column: Column of the tile, starting at ``0`` on the left.
            row: Row of the tile, starting at ``0`` at the top.

        Returns:
            TileBounds: Region of the tile inside the level.

        Raises:
            TileNotFoundError: If the tile is outside the level.
        """
        tile_size: int = self.tile_settings.tile_size
        overlap: int = self.tile_settings.overlap
        column_count: int = math.ceil(level_size.width / tile_size)
        row_count: int = math.ceil(level_size.height / tile_size)
        is_tile_in_level: bool = 0 <= column < column_count and 0 <= row < row_count
        if not is_tile_in_level:
            raise TileNotFoundError(
                f"Tile {column}_{row} is outside the {column_count}x{row_count} tiles of the level"
            )

        left: int = max(column * tile_size - overlap, 0)
        top: int = max(row * tile_size - overlap, 0)
        right: int = min((column + 1) * tile_size + overlap, level_size.width)
        bottom: int = min((row + 1) * tile_size + overlap, level_size.height)
        return TileBounds(left=left, top=top, width=right - left, height=bottom - top)

    def get_tile(
        self,
        image_path: Path,
        level: int,
        column: int,
        row: int,
    ) -> bytes:
        """Cut and encode one tile of an image.

        Only the levels below full size are resized, using libvips shrink-on-load when
        the image format supports it, and only the pixels of the tile are computed.

        Args:
            image_path: Path of the image.
            level: Deep Zoom level of the tile.
            column: Column of the tile.
            row: Row of the tile.

        Returns:
            bytes: The tile encoded in the configured format.

        Raises:
            UnreadableImageError: If the file is not an image libvips can read.
            TileNotFoundError: If the level or the tile does not exist.
        """
        image_size: ImageSize = self.read_size(image_path=image_path)
        level_size: ImageSize = self.get_level_size(image_size=image_size, level=level)
        tile_bounds: TileBounds = self.get_tile_bounds(
            level_size=level_size, column=column, row=row
        )

        is_full_size_level: bool = level_size == image_size
        level_image: Any = (
            self._open_image(image_path=image_path)
            if is_full_size_level
            else pyvips.Image.thumbnail(
                str(image_path),
                level_size.width,
                height=level_size.height,
                size="force",
                no_rotate=True,
            )
        )
        tile_image: Any = level_image.crop(
            tile_bounds.left, tile_bounds.top, tile_bounds.width, tile_bounds.height
        )
        return self._encode(tile_image=tile_image)

    @staticmethod
    def _open_image(
        image_path: Path,
    ) -> Any:
        """Open an image lazily; pixels are only decoded when they are needed.

        Args:
            image_path: Path of the image.

        Returns:
            Any: The ``pyvips.Image``.

        Raises:
            UnreadableImageError: If the file is not an image libvips can read.
        """
        try:
            return pyvips.Image.new_from_file(str(image_path))
        except pyvips.Error as error:
            raise UnreadableImageError(f"{image_path.name} is not a readable image") from error

    def _encode(
        self,
        tile_image: Any,
    ) -> bytes:
        """Encode a tile in the configured format.

        Args:
            tile_image: The ``pyvips.Image`` of the tile.

        Returns:
            bytes: The encoded tile. Transparent areas of JPEG tiles become white.
        """
        is_jpeg: bool = self.tile_settings.format == "jpeg"
        if is_jpeg:
            opaque_image: Any = (
                tile_image.flatten(background=255) if tile_image.hasalpha() else tile_image
            )
            return bytes(opaque_image.write_to_buffer(".jpeg", Q=self.tile_settings.jpeg_quality))
        return bytes(tile_image.write_to_buffer(".png"))


racker.register(
    class_=DeepZoomTiler,
    config_class=DeepZoomTilerConfig,
    base_class=TilerAbstract,
)
