"""Conversion of uploaded images into pyramidal tiled TIFFs.

A pyramidal TIFF holds the image at full size and at every halving of its size, each cut
into tiles. Tilers read only the tiles of the closest level, so a tile of a 1 GB image is
cut in milliseconds instead of decoding the whole image.
"""

from pathlib import Path
from typing import Any

import pyvips

from cragradar_backend.core.settings import PyramidSettings
from cragradar_backend.tiler.abcs import ImageSize
from cragradar_backend.tiler.errors import UnreadableImageError

GREYSCALE_INTERPRETATIONS: frozenset[str] = frozenset({"b-w", "grey16"})


def prepare_for_tiles(
    image: Any,
) -> Any:
    """Convert an image to 8-bit sRGB or greyscale without transparency.

    JPEG compression, the default of pyramids and tiles, accepts only that.

    Args:
        image: The ``pyvips.Image`` to convert.

    Returns:
        Any: The converted ``pyvips.Image``; transparent areas become white.
    """
    prepared_image: Any = image.flatten(background=255) if image.hasalpha() else image
    is_greyscale: bool = prepared_image.interpretation in GREYSCALE_INTERPRETATIONS
    target_colourspace: str = "b-w" if is_greyscale else "srgb"
    prepared_image = prepared_image.colourspace(target_colourspace)
    return prepared_image.cast("uchar")


def build_pyramid(
    source_path: Path,
    target_path: Path,
    pyramid_settings: PyramidSettings,
) -> ImageSize:
    """Write the pyramidal tiled TIFF of an image.

    The source is read once, from top to bottom, so memory stays low whatever the size of
    the image. EXIF orientation is not applied: a rotated photo stays as it was stored.

    Args:
        source_path: Uploaded image, in any format libvips reads.
        target_path: TIFF to write; replaced if it exists.
        pyramid_settings: Tile size and compression of the TIFF.

    Returns:
        ImageSize: Size of the image at full size.

    Raises:
        UnreadableImageError: If the source is not an image libvips can read, or the TIFF
            cannot be written from it.
    """
    try:
        source_image: Any = pyvips.Image.new_from_file(str(source_path), access="sequential")
        prepared_image: Any = prepare_for_tiles(image=source_image)
        prepared_image.tiffsave(
            str(target_path),
            tile=True,
            tile_width=pyramid_settings.tile_size,
            tile_height=pyramid_settings.tile_size,
            pyramid=True,
            compression=pyramid_settings.compression,
            Q=pyramid_settings.quality,
            bigtiff=True,
        )
    except pyvips.Error as error:
        raise UnreadableImageError(f"{source_path.name} cannot be converted: {error}") from error
    return ImageSize(width=int(source_image.width), height=int(source_image.height))
