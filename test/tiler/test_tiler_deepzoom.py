"""Unit tests for the Deep Zoom tiler."""

import shutil
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import pyvips
from pydantic import ValidationError
from test.config import TMP_DIR

from cragradar_backend.racker.registry import racker
from cragradar_backend.tiler.abcs import ImageSize, TilerAbstract
from cragradar_backend.tiler.deepzoom import (
    DEEP_ZOOM_NAMESPACE,
    DeepZoomTiler,
    DeepZoomTilerConfig,
    TileBounds,
)
from cragradar_backend.tiler.errors import TileNotFoundError, UnreadableImageError


@pytest.fixture
def images_dir() -> Iterator[Path]:
    """Give a folder under ``TMP_DIR`` for test images and delete it afterwards."""
    images_dir: Path = TMP_DIR / "tiler_images"
    images_dir.mkdir(parents=True)
    yield images_dir
    shutil.rmtree(images_dir)


@pytest.fixture
def image_path(images_dir: Path) -> Path:
    """Write a 1000x600 grey gradient PNG and give its path."""
    image_path: Path = images_dir / "gradient.png"
    pyvips.Image.xyz(1000, 600)[0].cast("uchar").write_to_file(str(image_path))
    return image_path


@pytest.fixture
def tiler() -> DeepZoomTiler:
    """Build a tiler with the default 254 pixel tiles and 1 pixel overlap."""
    return DeepZoomTiler(config=DeepZoomTilerConfig())


def read_tile_size(tile: bytes) -> tuple[int, int]:
    """Decode a tile and return its width and height."""
    tile_image: Any = pyvips.Image.new_from_buffer(tile, "")
    return (int(tile_image.width), int(tile_image.height))


def test_tiler_reads_image_size(tiler: DeepZoomTiler, image_path: Path) -> None:
    """Check that the size is read from the image header."""
    assert tiler.read_size(image_path=image_path) == ImageSize(width=1000, height=600)


def test_tiler_raises_when_file_is_not_an_image(tiler: DeepZoomTiler, images_dir: Path) -> None:
    """Check that a file libvips cannot read is reported as unreadable."""
    text_path: Path = images_dir / "notes.png"
    text_path.write_text("not an image")

    with pytest.raises(UnreadableImageError, match=r"notes.png is not a readable image"):
        tiler.read_size(image_path=text_path)


def test_tiler_describes_image_as_deep_zoom_xml(tiler: DeepZoomTiler, image_path: Path) -> None:
    """Check that the descriptor holds the format, overlap, tile size and image size."""
    descriptor: ElementTree.Element = ElementTree.fromstring(
        tiler.describe(image_path=image_path).encode()
    )
    size_element: ElementTree.Element | None = descriptor.find(f"{{{DEEP_ZOOM_NAMESPACE}}}Size")

    assert descriptor.tag == f"{{{DEEP_ZOOM_NAMESPACE}}}Image"
    assert descriptor.attrib == {"Format": "jpeg", "Overlap": "1", "TileSize": "254"}
    assert size_element is not None
    assert size_element.attrib == {"Width": "1000", "Height": "600"}


@pytest.mark.parametrize(
    ("image_size", "expected_max_level"),
    [
        (ImageSize(1, 1), 0),
        (ImageSize(2, 1), 1),
        (ImageSize(1000, 600), 10),
        (ImageSize(1024, 3), 10),
    ],
)
def test_tiler_max_level_is_log2_of_longest_side(
    image_size: ImageSize, expected_max_level: int
) -> None:
    """Check that the full-size level is ``ceil(log2(max(width, height)))``."""
    assert DeepZoomTiler.get_max_level(image_size=image_size) == expected_max_level


@pytest.mark.parametrize(
    ("level", "expected_level_size"),
    [
        (10, ImageSize(1000, 600)),
        (9, ImageSize(500, 300)),
        (1, ImageSize(2, 2)),
        (0, ImageSize(1, 1)),
    ],
)
def test_tiler_level_size_halves_rounding_up(
    tiler: DeepZoomTiler, level: int, expected_level_size: ImageSize
) -> None:
    """Check that each level below full size halves the image, rounding up."""
    assert tiler.get_level_size(image_size=ImageSize(1000, 600), level=level) == expected_level_size


@pytest.mark.parametrize("level", [-1, 11])
def test_tiler_raises_when_level_is_out_of_range(tiler: DeepZoomTiler, level: int) -> None:
    """Check that levels outside ``0..max_level`` do not exist."""
    with pytest.raises(TileNotFoundError, match=r"is not between 0 and 10"):
        tiler.get_level_size(image_size=ImageSize(1000, 600), level=level)


@pytest.mark.parametrize(
    ("column", "row", "expected_bounds"),
    [
        (0, 0, TileBounds(left=0, top=0, width=255, height=255)),
        (1, 1, TileBounds(left=253, top=253, width=256, height=256)),
        (3, 2, TileBounds(left=761, top=507, width=239, height=93)),
    ],
)
def test_tiler_tile_bounds_include_overlap_except_at_image_edges(
    tiler: DeepZoomTiler, column: int, row: int, expected_bounds: TileBounds
) -> None:
    """Check that tiles share ``overlap`` pixels with neighbours but stop at the edges."""
    assert (
        tiler.get_tile_bounds(level_size=ImageSize(1000, 600), column=column, row=row)
        == expected_bounds
    )


@pytest.mark.parametrize(("column", "row"), [(4, 0), (0, 3), (-1, 0)])
def test_tiler_raises_when_tile_is_outside_level(
    tiler: DeepZoomTiler, column: int, row: int
) -> None:
    """Check that tiles past the last column or row do not exist."""
    with pytest.raises(TileNotFoundError, match=r"outside the 4x3 tiles"):
        tiler.get_tile_bounds(level_size=ImageSize(1000, 600), column=column, row=row)


@pytest.mark.parametrize(
    ("level", "column", "row", "expected_size"),
    [(10, 0, 0, (255, 255)), (10, 3, 2, (239, 93)), (9, 1, 1, (247, 47)), (0, 0, 0, (1, 1))],
)
def test_tiler_cuts_tiles_of_the_expected_size(
    tiler: DeepZoomTiler,
    image_path: Path,
    level: int,
    column: int,
    row: int,
    expected_size: tuple[int, int],
) -> None:
    """Check that full-size and resized levels give tiles of the Deep Zoom size."""
    tile: bytes = tiler.get_tile(image_path=image_path, level=level, column=column, row=row)

    assert read_tile_size(tile) == expected_size


def test_tiler_encodes_jpeg_tiles_by_default(tiler: DeepZoomTiler, image_path: Path) -> None:
    """Check that tiles are JPEG by default."""
    tile: bytes = tiler.get_tile(image_path=image_path, level=10, column=0, row=0)

    assert tile.startswith(b"\xff\xd8\xff")
    assert tiler.media_type == "image/jpeg"


def test_tiler_encodes_png_tiles_when_configured(image_path: Path) -> None:
    """Check that the tile format follows the settings."""
    png_tiler: DeepZoomTiler = DeepZoomTiler(config=DeepZoomTilerConfig(format="png"))

    tile: bytes = png_tiler.get_tile(image_path=image_path, level=10, column=0, row=0)

    assert tile.startswith(b"\x89PNG")
    assert png_tiler.media_type == "image/png"


def test_tiler_flattens_transparency_of_jpeg_tiles(tiler: DeepZoomTiler, images_dir: Path) -> None:
    """Check that a transparent image gives opaque JPEG tiles with a white background."""
    transparent_path: Path = images_dir / "transparent.png"
    pyvips.Image.black(10, 10, bands=4).cast("uchar").write_to_file(str(transparent_path))

    tile_image: Any = pyvips.Image.new_from_buffer(
        tiler.get_tile(image_path=transparent_path, level=4, column=0, row=0), ""
    )

    assert not tile_image.hasalpha()
    assert tile_image.avg() > 250


def test_deep_zoom_tiler_serves_dzi_descriptors_as_xml(tiler: DeepZoomTiler) -> None:
    """Check the media type of the descriptor and the configured tile format."""
    assert tiler.descriptor_media_type == "application/xml"
    assert tiler.tile_format == "jpeg"


def test_deep_zoom_tiler_is_built_from_dict_by_racker() -> None:
    """Check that the Deep Zoom tiler is registered in ``racker`` under ``deepzoom``."""
    built_tiler: TilerAbstract = racker.instantiate_from_dict(
        base_class=TilerAbstract,
        config_dict={"type": "deepzoom", "tile_size": 512, "format": "png"},
    )

    assert isinstance(built_tiler, DeepZoomTiler)
    assert built_tiler.tile_settings.tile_size == 512
    assert built_tiler.tile_format == "png"


def test_deep_zoom_tiler_config_rejects_unknown_tile_format() -> None:
    """Check that only formats OpenSeadragon and the tiler support are accepted."""
    with pytest.raises(ValidationError, match=r"format"):
        DeepZoomTilerConfig(format="gif")
