"""Abstract tilers, which cut images into tiles for viewers, and their ``racker`` registry."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from cragradar_backend.racker.registry import racker


@dataclass(frozen=True)
class ImageSize:
    """Size of an image in pixels.

    Attributes:
        width: Width in pixels.
        height: Height in pixels.
    """

    width: int
    height: int


class TilerConfigAbstract(BaseModel):
    """Base configuration of tilers: immutable, no extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    type: str = "base"


class TilerAbstract(ABC):
    """Base class of objects that describe images and cut their tiles on demand."""

    def __init__(
        self,
        config: TilerConfigAbstract,
    ) -> None:
        """Initialize the tiler with a configuration object.

        Args:
            config: Configuration of the tiler.
        """
        self.config: TilerConfigAbstract = config

    @property
    @abstractmethod
    def tile_format(
        self,
    ) -> str:
        """Return the image format of the tiles, also used as their file extension.

        Returns:
            str: Format such as ``jpeg`` or ``png``.
        """

    @property
    @abstractmethod
    def media_type(
        self,
    ) -> str:
        """Return the media type of the tiles.

        Returns:
            str: Media type such as ``image/jpeg``.
        """

    @property
    @abstractmethod
    def descriptor_media_type(
        self,
    ) -> str:
        """Return the media type of the image descriptor.

        Returns:
            str: Media type such as ``application/xml``.
        """

    @abstractmethod
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
            UnreadableImageError: If the file is not an image the tiler can read.
        """

    @abstractmethod
    def describe(
        self,
        image_path: Path,
    ) -> str:
        """Build the descriptor that tells a viewer how the image is tiled.

        Args:
            image_path: Path of the image.

        Returns:
            str: The descriptor document.

        Raises:
            UnreadableImageError: If the file is not an image the tiler can read.
        """

    @abstractmethod
    def get_tile(
        self,
        image_path: Path,
        level: int,
        column: int,
        row: int,
    ) -> bytes:
        """Cut and encode one tile of an image.

        Args:
            image_path: Path of the image.
            level: Zoom level of the tile.
            column: Column of the tile.
            row: Row of the tile.

        Returns:
            bytes: The tile encoded in ``tile_format``.

        Raises:
            UnreadableImageError: If the file is not an image the tiler can read.
            TileNotFoundError: If the level or the tile does not exist.
        """


racker.add_base(base_class=TilerAbstract)
