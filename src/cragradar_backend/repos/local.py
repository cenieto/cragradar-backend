"""Repository that stores files in the local file system."""

import codecs
import logging
import os
import uuid
from pathlib import Path
from typing import IO, Any, ClassVar, Literal

from pydantic import field_validator

from cragradar_backend.racker.registry import racker
from cragradar_backend.racker.validators import Built
from cragradar_backend.repos.abcs import (
    PathGeneratorAbstract,
    ReadableFile,
    RepositoryAbstract,
    RepositoryConfigAbstract,
)
from cragradar_backend.repos.errors import (
    FileAlreadyStoredError,
    RepositoryError,
    StoredFileNotFoundError,
)

logger: logging.Logger = logging.getLogger(__name__)


class LocalRepositoryConfig(RepositoryConfigAbstract):
    """Configuration of ``LocalRepository``.

    ``base_root`` is the folder that holds every file.

    Attributes:
        path_generator: Path generator that decides where each file is stored inside
            ``base_root``. It can be given as its configuration dictionary, which
            ``racker`` builds into the object.
        encoding: Encoding used to write files opened in text mode.
    """

    type: Literal["local"] = "local"
    path_generator: Built[PathGeneratorAbstract]
    encoding: str = "utf-8"

    @field_validator("encoding", mode="after")
    @classmethod
    def validate_encoding(
        cls,
        value: str,
    ) -> str:
        """Check that the encoding is known to Python.

        Args:
            value: Encoding name to check.

        Returns:
            str: The encoding name, unchanged.

        Raises:
            ValueError: If ``value`` is not a known encoding.
        """
        try:
            codecs.lookup(value)
        except LookupError as error:
            raise ValueError(f"Unknown encoding '{value}'") from error
        return value


class LocalRepository(RepositoryAbstract):
    """Repository that writes files to the paths given by its path generator.

    Files are copied in chunks of ``CHUNK_SIZE`` characters or bytes, so large files are
    never held in memory whole.
    """

    CHUNK_SIZE: ClassVar[int] = 1024 * 1024

    def __init__(
        self,
        config: LocalRepositoryConfig,
    ) -> None:
        """Initialize the local repository with a configuration object.

        Args:
            config: Configuration of the repository.
        """
        super().__init__(config=config)
        self.path_generator: PathGeneratorAbstract = config.path_generator
        self.encoding: str = config.encoding

    def save(
        self,
        source_file: ReadableFile[str] | ReadableFile[bytes],
        file_name: str,
        overwrite: bool = False,
    ) -> Path:
        """Save a file inside ``base_root`` at the path given by the path generator.

        Missing folders are created.

        Text files are written with the configured ``encoding``. A failed save never
        leaves a partial file behind:

        - Without ``overwrite``, the file is created in exclusive mode, so an existing
          file is never touched, even by a concurrent save.
        - With ``overwrite``, the content is written to a temporary file in the same
          folder, which then atomically replaces the existing file. The existing file
          stays unchanged until the new content is complete.

        Args:
            source_file: Content to save, opened in text or binary mode.
            file_name: Name to store the file under; only its last part is used.
            overwrite: Replace a file already at the generated path. When ``False``,
                the existing file is kept and ``RepositoryError`` is raised.

        Returns:
            Path: Path of the saved file relative to ``base_root``, such as
                ``2026/10/26/sketch.tif``.

        Raises:
            InvalidFileNameError: If the name of the file cannot be used. Nothing is
                created in that case.
            FileAlreadyStoredError: If a file already exists at the path and
                ``overwrite`` is ``False``.
            RepositoryError: If the file could not be read, encoded or written. The
                original error is kept as ``__cause__``.
        """
        relative_path: Path = self.path_generator.generate_path(file_name=file_name)
        path: Path = self.base_root / relative_path
        save_error_message: str = f"Could not save {file_name!r} to {path}"
        try:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            first_chunk: str | bytes = self._read_first_chunk(source_file)
        except (OSError, TypeError, UnicodeError) as error:
            raise RepositoryError(save_error_message) from error

        written_path: Path = self._build_temporary_path(path=path) if overwrite else path
        try:
            self._write_new_file(
                path=written_path,
                source_file=source_file,
                first_chunk=first_chunk,
            )
        except FileExistsError as error:
            raise FileAlreadyStoredError(
                f"File already exists: {path}. Pass overwrite=True to replace it"
            ) from error
        except (OSError, TypeError, UnicodeError) as error:
            raise RepositoryError(save_error_message) from error

        if overwrite:
            try:
                os.replace(written_path, path)
            except OSError as error:
                written_path.unlink(missing_ok=True)
                raise RepositoryError(save_error_message) from error

        logger.info("File saved: %s", path)
        return relative_path

    def resolve_path(
        self,
        url: str,
    ) -> Path:
        """Compute the physical location of a stored file from its URL.

        The part of the URL after ``base_url`` is used as a path inside ``base_root``,
        without searching. Paths that leave ``base_root``, with ``..`` or as an absolute
        path, are treated as not stored, so a URL can never read other files on the
        machine.

        Args:
            url: Full URL or URL path of the file, already decoded, such as
                ``/tiles/storage/2026/10/26/sketch.tif``.

        Returns:
            Path: Absolute physical path of the stored file.

        Raises:
            StoredFileNotFoundError: If the URL is not under ``base_url``, the path leaves
                ``base_root``, or no file is stored there.
        """
        file_path: str = self._get_file_path_from_url(url=url)
        root_path: Path = self.base_root.resolve()
        local_path: Path = (root_path / file_path).resolve()
        is_stored_file: bool = local_path.is_relative_to(root_path) and local_path.is_file()
        if not is_stored_file:
            raise StoredFileNotFoundError(f"No file stored at {url!r}")
        return local_path

    @staticmethod
    def _build_temporary_path(
        path: Path,
    ) -> Path:
        """Build a unique hidden path, next to ``path``, to write new content into.

        Args:
            path: Final path of the file.

        Returns:
            Path: ``.<file name>.<random hex>.tmp`` in the folder of ``path``.
        """
        return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

    def _write_new_file(
        self,
        path: Path,
        source_file: ReadableFile[str] | ReadableFile[bytes],
        first_chunk: str | bytes,
    ) -> None:
        """Create a file and copy the content into it, deleting it if the copy fails.

        Args:
            path: Path of the file to create; it must not exist yet.
            source_file: File being saved, already read up to ``first_chunk``.
            first_chunk: Content already read from ``source_file``.

        Raises:
            FileExistsError: If a file already exists at ``path``.
            OSError: If the file cannot be created, read or written.
            TypeError: If a later chunk is not of the same type as ``first_chunk``.
            UnicodeError: If text cannot be encoded with the configured encoding.
        """
        target_file: IO[Any] = self._open_new_file(
            path=path,
            is_text_content=isinstance(first_chunk, str),
        )
        try:
            with target_file:
                self._copy_chunks(
                    source_file=source_file,
                    target_file=target_file,
                    first_chunk=first_chunk,
                )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def _read_first_chunk(
        self,
        source_file: ReadableFile[str] | ReadableFile[bytes],
    ) -> str | bytes:
        """Read the first chunk of a file, which tells whether it is text or bytes.

        Args:
            source_file: File to read.

        Returns:
            str | bytes: Up to ``CHUNK_SIZE`` characters or bytes; empty for an empty file.

        Raises:
            TypeError: If the file returns something other than ``str`` or ``bytes``.
        """
        first_chunk: str | bytes = source_file.read(self.CHUNK_SIZE)

        is_supported_content: bool = isinstance(first_chunk, (str, bytes))
        if not is_supported_content:
            raise TypeError("Unsupported file content type")

        return first_chunk

    def _open_new_file(
        self,
        path: Path,
        is_text_content: bool,
    ) -> IO[Any]:
        """Create a file in exclusive mode and open it for writing.

        Args:
            path: Path of the file to create.
            is_text_content: Open in text mode with the configured encoding, instead of
                binary mode.

        Returns:
            IO[Any]: The new, empty file.

        Raises:
            FileExistsError: If a file already exists at ``path``.
        """
        if is_text_content:
            return path.open("x", encoding=self.encoding)
        return path.open("xb")

    def _copy_chunks(
        self,
        source_file: ReadableFile[str] | ReadableFile[bytes],
        target_file: IO[Any],
        first_chunk: str | bytes,
    ) -> None:
        """Copy a file into the target, one chunk at a time.

        Args:
            source_file: File being saved, already read up to ``first_chunk``.
            target_file: Open file the content is written to.
            first_chunk: Content already read from ``source_file``.
        """
        chunk: str | bytes = first_chunk
        while chunk:
            target_file.write(chunk)
            chunk = source_file.read(self.CHUNK_SIZE)


racker.register(
    class_=LocalRepository,
    config_class=LocalRepositoryConfig,
    base_class=RepositoryAbstract,
)
