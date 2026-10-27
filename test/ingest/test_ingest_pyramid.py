"""Conversion of uploads into pyramidal tiled TIFFs."""

from pathlib import Path
from typing import Any

import pytest
import pyvips
from test.conftest import write_gradient

from cragradar_backend.core.settings import PyramidSettings
from cragradar_backend.ingest.pyramid import build_pyramid
from cragradar_backend.tiler.abcs import ImageSize
from cragradar_backend.tiler.errors import UnreadableImageError


def test_pyramid_is_tiled_with_one_page_per_halving(work_dir: Path) -> None:
    """Check that a 1000x600 image gives tiled pages of 1000, 500, 250... pixels wide."""
    source_path: Path = write_gradient(work_dir / "gradient.png")
    target_path: Path = work_dir / "gradient.pyramid.tif"

    image_size: ImageSize = build_pyramid(source_path, target_path, PyramidSettings(tile_size=128))

    assert image_size == ImageSize(width=1000, height=600)
    first_page: Any = pyvips.Image.new_from_file(str(target_path))
    page_count: int = int(first_page.get("n-pages"))
    page_widths: list[int] = [
        int(pyvips.Image.new_from_file(str(target_path), page=page).width)
        for page in range(page_count)
    ]
    assert page_widths[:3] == [1000, 500, 250]
    assert int(first_page.get("tile-width")) == 128


def test_transparent_image_is_flattened(work_dir: Path) -> None:
    """Check that an RGBA image becomes a 3-band image, as JPEG compression requires."""
    source_path: Path = work_dir / "transparent.png"
    pyvips.Image.black(300, 200, bands=4).write_to_file(str(source_path))
    target_path: Path = work_dir / "transparent.pyramid.tif"

    build_pyramid(source_path, target_path, PyramidSettings())

    assert int(pyvips.Image.new_from_file(str(target_path)).bands) == 3


def test_file_that_is_not_an_image_is_rejected(work_dir: Path) -> None:
    """Check that a text file is reported as unreadable."""
    source_path: Path = work_dir / "notes.png"
    source_path.write_text("not an image")

    with pytest.raises(UnreadableImageError):
        build_pyramid(source_path, work_dir / "notes.pyramid.tif", PyramidSettings())
