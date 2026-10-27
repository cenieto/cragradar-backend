"""Abstract repositories and path generators, and the ``racker`` registries of their bases."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from cragradar_backend.racker.registry import racker
from cragradar_backend.repos.errors import InvalidFileNameError, StoredFileNotFoundError

T_co = TypeVar("T_co", str, bytes, covariant=True)


class ReadableFile(Protocol[T_co]):
    """File-like object opened in text or binary mode, such as ``UploadFile.file``."""

    def read(self, size: int = -1, /) -> T_co:
        """Read the content of the file.

        Args:
            size: Maximum number of characters or bytes to read; ``-1`` reads everything.

        Returns:
            T_co: The content read, as ``str`` in text mode or ``bytes`` in binary mode.
        """
        ...


class BaseConfig(BaseModel):
    """Base configuration of repositories and path generators: immutable, no extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class PathGeneratorConfigAbstract(BaseConfig):
    """Base configuration of path generators."""

    type: str = "base"


class PathGeneratorAbstract(ABC):
    """Base class of objects that decide where a file is stored inside a repository.

    Generated paths are relative to the ``base_url`` of the repository.
    """

    def __init__(
        self,
        config: PathGeneratorConfigAbstract,
    ) -> None:
        """Initialize the path generator with a configuration object.

        Args:
            config: Configuration of the path generator.
        """
        self.config: PathGeneratorConfigAbstract = config

    @abstractmethod
    def generate_path(
        self,
        file_name: str,
    ) -> Path:
        """Generate the path where a file is stored, relative to the repository root.

        Args:
            file_name: Name of the file to store.

        Returns:
            Path: Relative path of the file, including its name.

        Raises:
            InvalidFileNameError: If the name of the file cannot be used.
        """

    @staticmethod
    def _get_file_name(
        file_name: str,
    ) -> str:
        """Get the last part of a file name, rejecting names that cannot be stored.

        Folders in the name are dropped, so a file can never be written outside the
        folder chosen by the path generator.

        Args:
            file_name: Name of the file, possibly with folders.

        Returns:
            str: Last part of the file name, such as ``photo.jpg`` for ``uploads/photo.jpg``.

        Raises:
            InvalidFileNameError: If the name has no last part (``""``, ``.``, ``/``), is
                ``..``, or contains a NUL character.
        """
        last_name_part: str = Path(file_name).name
        is_missing_file_name: bool = last_name_part in ("", "..")
        if is_missing_file_name:
            raise InvalidFileNameError(f"File name {file_name!r} has no usable file name")

        has_nul_character: bool = "\x00" in last_name_part
        if has_nul_character:
            raise InvalidFileNameError(f"File name {file_name!r} contains a NUL character")

        return last_name_part


class RepositoryConfigAbstract(BaseConfig):
    """Base configuration of repositories.

    Attributes:
        base_url: URL path under which every stored file is served, such as
            ``/tiles/storage`` for ``http://app.com/tiles/storage/<file path>``.
        base_root: Physical location where every file is stored, such as a folder.
    """

    base_url: str
    base_root: Path

    @field_validator("base_url", mode="after")
    @classmethod
    def validate_base_url(
        cls,
        value: str,
    ) -> str:
        """Check that the base URL is a URL path and remove its trailing slashes.

        Args:
            value: Base URL to check, such as ``/tiles/storage/``.

        Returns:
            str: The base URL without trailing slashes, such as ``/tiles/storage``; ``/``
                stays ``/``.

        Raises:
            ValueError: If ``value`` does not start with ``/``.
        """
        is_url_path: bool = value.startswith("/")
        if not is_url_path:
            raise ValueError(
                f"base_url {value!r} must be a URL path starting with '/', such as '/tiles/storage'"
            )
        return "/" + value.strip("/")


class RepositoryAbstract(ABC):
    """Base class of objects that store files under ``base_root`` and serve them under ``base_url``.

    A stored file is identified by its path relative to both: the file at
    ``base_root / 2026/10/26/sketch.tif`` is served at ``base_url/2026/10/26/sketch.tif``.
    """

    def __init__(
        self,
        config: RepositoryConfigAbstract,
    ) -> None:
        """Initialize the repository with a configuration object.

        Args:
            config: Configuration of the repository.
        """
        self.config: RepositoryConfigAbstract = config
        self.base_url: str = config.base_url
        self.base_root: Path = config.base_root

    def build_url(
        self,
        file_path: Path,
    ) -> str:
        """Build the URL path of a stored file.

        Args:
            file_path: Path of the file relative to ``base_root``, as returned by ``save``.

        Returns:
            str: ``base_url/<file path>``, such as ``/tiles/storage/2026/10/26/sketch.tif``.
        """
        return f"{self._get_url_prefix()}{file_path.as_posix()}"

    def _get_url_prefix(
        self,
    ) -> str:
        """Get ``base_url`` ending with exactly one slash.

        Returns:
            str: Prefix of every file URL, such as ``/tiles/storage/``.
        """
        return self.base_url.rstrip("/") + "/"

    def _get_file_path_from_url(
        self,
        url: str,
    ) -> str:
        """Get the path of a file relative to ``base_root`` from its URL.

        Args:
            url: Full URL or URL path of the file, already decoded, such as
                ``http://app.com/tiles/storage/2026/10/26/sketch.tif``.

        Returns:
            str: The part of the URL path after ``base_url``, such as
                ``2026/10/26/sketch.tif``.

        Raises:
            StoredFileNotFoundError: If the URL path is not under ``base_url``.
        """
        url_path: str = urlsplit(url).path
        url_prefix: str = self._get_url_prefix()
        is_under_base_url: bool = url_path.startswith(url_prefix)
        if not is_under_base_url:
            raise StoredFileNotFoundError(f"URL {url!r} is not under {self.base_url!r}")
        return url_path[len(url_prefix) :]

    @abstractmethod
    def save(
        self,
        source_file: ReadableFile[str] | ReadableFile[bytes],
        file_name: str,
        overwrite: bool = False,
    ) -> Path:
        """Save a file to the repository.

        Args:
            source_file: Content to save, read in chunks.
            file_name: Name to store the file under.
            overwrite: Replace a file already stored at the same location. When
                ``False``, an existing file is kept and an error is raised.

        Returns:
            Path: Path of the saved file relative to ``base_root``. ``build_url`` turns it
                into the URL that ``resolve_path`` accepts.

        Raises:
            InvalidFileNameError: If the name of the file cannot be used.
            RepositoryError: If the file could not be saved, including when a file
                already exists at the location and ``overwrite`` is ``False``.
        """

    @abstractmethod
    def resolve_path(
        self,
        url: str,
    ) -> Path:
        """Compute the physical location of a stored file from its URL.

        The part of the URL after ``base_url`` is used as a path inside ``base_root``,
        without searching. The result must stay inside ``base_root``, so a URL can never
        reach other files, for example with ``..`` or an absolute path.

        Args:
            url: Full URL or URL path of the file, already decoded, such as
                ``/tiles/storage/2026/10/26/sketch.tif``.

        Returns:
            Path: Physical location of the stored file.

        Raises:
            StoredFileNotFoundError: If the URL is not under ``base_url``, the path leaves
                ``base_root``, or no file is stored there.
        """


racker.add_base(base_class=PathGeneratorAbstract)
racker.add_base(base_class=RepositoryAbstract)
