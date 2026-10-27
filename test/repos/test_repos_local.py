"""Unit tests for ``LocalRepository`` and its ``racker`` registration."""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError
from test.config import FIXTURES_DIR, TMP_DIR

from cragradar_backend.racker.registry import racker
from cragradar_backend.repos.abcs import RepositoryAbstract
from cragradar_backend.repos.errors import (
    InvalidFileNameError,
    RepositoryError,
    StoredFileNotFoundError,
)
from cragradar_backend.repos.local import LocalRepository, LocalRepositoryConfig
from cragradar_backend.repos.path import (
    DatePathGenerator,
    FixedPathGenerator,
    FixedPathGeneratorConfig,
)


class FileWithUnsupportedContent:
    """File whose content is neither ``str`` nor ``bytes``."""

    def read(self, size: int = -1, /) -> int:
        """Return an integer instead of text or bytes."""
        return 42


class ChunkRecordingFile:
    """In-memory file that records the size of every read and can fail mid-way."""

    def __init__(self, content: str | bytes, failing_read_number: int = 0) -> None:
        """Store the content, and the read number that raises ``OSError`` (``0``: never)."""
        self.content: str | bytes = content
        self.failing_read_number: int = failing_read_number
        self.read_sizes: list[int] = []
        self.position: int = 0

    def read(self, size: int = -1, /) -> str | bytes:
        """Return the next ``size`` characters or bytes, failing on the configured read."""
        self.read_sizes.append(size)
        is_failing_read: bool = len(self.read_sizes) == self.failing_read_number
        if is_failing_read:
            raise OSError("connection lost while reading")
        chunk: str | bytes = self.content[self.position : self.position + size]
        self.position += len(chunk)
        return chunk


@pytest.fixture
def repository_dir() -> Iterator[Path]:
    """Give a folder under ``TMP_DIR`` for the repository and delete it afterwards."""
    repository_dir: Path = TMP_DIR / "local_repository"
    yield repository_dir
    if repository_dir.is_dir():
        shutil.rmtree(repository_dir)
    else:
        repository_dir.unlink(missing_ok=True)


@pytest.fixture
def example_file_path() -> Path:
    """Give the path of the input file saved by the tests."""
    return FIXTURES_DIR / "repos" / "example.md"


@pytest.fixture
def local_repository(repository_dir: Path) -> LocalRepository:
    """Build a local repository that stores every file directly in ``repository_dir``."""
    return LocalRepository(
        config=LocalRepositoryConfig(
            base_url="/files",
            base_root=repository_dir,
            path_generator=FixedPathGenerator(config=FixedPathGeneratorConfig()),
        )
    )


def test_local_repository_saves_text_file(
    local_repository: LocalRepository,
    repository_dir: Path,
    example_file_path: Path,
) -> None:
    """Check that a file opened in text mode is written with the same content."""
    with open(example_file_path) as example_file:
        saved_path: Path = local_repository.save(example_file, file_name="example.md")

    assert saved_path == Path("example.md")
    assert (repository_dir / saved_path).read_text() == example_file_path.read_text()


def test_local_repository_saves_binary_file(
    local_repository: LocalRepository,
    repository_dir: Path,
    example_file_path: Path,
) -> None:
    """Check that a file opened in binary mode is written with the same bytes."""
    with open(example_file_path, "rb") as example_file:
        saved_path: Path = local_repository.save(example_file, file_name="example.md")

    assert saved_path == Path("example.md")
    assert (repository_dir / saved_path).read_bytes() == example_file_path.read_bytes()


def test_local_repository_raises_repository_error_when_folder_cannot_be_created(
    local_repository: LocalRepository,
    repository_dir: Path,
    example_file_path: Path,
) -> None:
    """Check that a file system error is raised as ``RepositoryError`` keeping its cause."""
    repository_dir.parent.mkdir(parents=True, exist_ok=True)
    repository_dir.write_text("a file where the repository folder should be")

    with (
        open(example_file_path) as example_file,
        pytest.raises(RepositoryError, match=r"Could not save .*example.md") as raised_error,
    ):
        local_repository.save(example_file, file_name="example.md")

    assert isinstance(raised_error.value.__cause__, OSError)


def test_local_repository_raises_repository_error_when_content_is_unsupported(
    local_repository: LocalRepository,
) -> None:
    """Check that content other than text or bytes is raised as ``RepositoryError``."""
    with pytest.raises(RepositoryError, match=r"numbers.txt") as raised_error:
        local_repository.save(FileWithUnsupportedContent(), file_name="numbers.txt")

    assert isinstance(raised_error.value.__cause__, TypeError)


def test_local_repository_logs_saved_path(
    local_repository: LocalRepository,
    repository_dir: Path,
    example_file_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check that each saved file is logged at info level with its path."""
    with caplog.at_level("INFO"), open(example_file_path) as example_file:
        saved_path: Path = local_repository.save(example_file, file_name="example.md")

    assert f"File saved: {repository_dir / saved_path}" in caplog.text


def test_local_repository_is_built_from_nested_dict_by_racker(
    repository_dir: Path,
) -> None:
    """Check that the repository and its path generator are both built from one dict."""
    repository: RepositoryAbstract = racker.instantiate_from_dict(
        base_class=RepositoryAbstract,
        config_dict={
            "type": "local",
            "base_url": "/files",
            "base_root": str(repository_dir),
            "path_generator": {"type": "date"},
        },
    )

    assert isinstance(repository, LocalRepository)
    assert isinstance(repository.path_generator, DatePathGenerator)


def test_local_repository_config_raises_when_path_generator_type_is_unknown() -> None:
    """Check that a path generator of no registered type fails validation."""
    with pytest.raises(ValidationError, match=r"path_generator"):
        LocalRepositoryConfig.model_validate({"path_generator": {"type": "unknown"}})


def test_local_repository_keeps_existing_file_by_default(
    local_repository: LocalRepository,
    repository_dir: Path,
    example_file_path: Path,
) -> None:
    """Check that saving onto an existing file raises and leaves that file untouched."""
    repository_dir.mkdir(parents=True)
    existing_path: Path = repository_dir / "example.md"
    existing_path.write_text("content saved earlier")

    with (
        open(example_file_path) as example_file,
        pytest.raises(
            RepositoryError, match=r"File already exists: .*overwrite=True"
        ) as raised_error,
    ):
        local_repository.save(example_file, file_name="example.md")

    assert isinstance(raised_error.value.__cause__, FileExistsError)
    assert existing_path.read_text() == "content saved earlier"


@pytest.mark.parametrize("open_mode", ["r", "rb"])
def test_local_repository_replaces_existing_file_when_overwrite_is_true(
    local_repository: LocalRepository,
    repository_dir: Path,
    example_file_path: Path,
    open_mode: str,
) -> None:
    """Check that ``overwrite=True`` replaces an existing file in text and binary mode."""
    repository_dir.mkdir(parents=True)
    (repository_dir / "example.md").write_text("content saved earlier")

    with open(example_file_path, open_mode) as example_file:
        saved_path: Path = local_repository.save(
            example_file, file_name="example.md", overwrite=True
        )

    assert (repository_dir / saved_path).read_bytes() == example_file_path.read_bytes()


@pytest.fixture
def small_chunks(monkeypatch: pytest.MonkeyPatch) -> int:
    """Make the repository copy files in chunks of 4 so tests use several chunks."""
    monkeypatch.setattr(LocalRepository, "CHUNK_SIZE", 4)
    return 4


def test_local_repository_copies_file_in_chunks(
    local_repository: LocalRepository,
    repository_dir: Path,
    small_chunks: int,
) -> None:
    """Check that the file is read in ``CHUNK_SIZE`` pieces and written back complete."""
    recording_file: ChunkRecordingFile = ChunkRecordingFile(content=b"0123456789")

    saved_path: Path = local_repository.save(recording_file, file_name="chunks.bin")

    assert recording_file.read_sizes == [small_chunks, small_chunks, small_chunks, small_chunks]
    assert (repository_dir / saved_path).read_bytes() == b"0123456789"


def test_local_repository_saves_empty_file(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that an empty file is saved as an empty file."""
    saved_path: Path = local_repository.save(ChunkRecordingFile(content=""), file_name="empty.txt")

    assert (repository_dir / saved_path).read_bytes() == b""


def test_local_repository_removes_partial_file_when_reading_fails_mid_way(
    local_repository: LocalRepository,
    repository_dir: Path,
    small_chunks: int,
) -> None:
    """Check that a failed copy leaves no partial file, so the save can be retried."""
    failing_file: ChunkRecordingFile = ChunkRecordingFile(
        content="0123456789", failing_read_number=2
    )

    with pytest.raises(RepositoryError, match=r"Could not save 'upload.txt'") as raised_error:
        local_repository.save(failing_file, file_name="upload.txt")

    assert isinstance(raised_error.value.__cause__, OSError)
    retried_path: Path = local_repository.save(
        ChunkRecordingFile(content="0123456789"), file_name="upload.txt"
    )
    assert (repository_dir / retried_path).read_text() == "0123456789"


def test_local_repository_writes_text_as_utf_8_by_default(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that text is encoded as UTF-8 when no encoding is configured."""
    saved_path: Path = local_repository.save(
        ChunkRecordingFile(content="Señal"), file_name="crag.txt"
    )

    assert (repository_dir / saved_path).read_bytes() == "Señal".encode()


def test_local_repository_writes_text_with_configured_encoding(
    repository_dir: Path,
) -> None:
    """Check that text is encoded with the encoding of the config."""
    latin_1_repository: LocalRepository = LocalRepository(
        config=LocalRepositoryConfig(
            base_url="/files",
            base_root=repository_dir,
            path_generator=FixedPathGenerator(config=FixedPathGeneratorConfig()),
            encoding="latin-1",
        )
    )

    saved_path: Path = latin_1_repository.save(
        ChunkRecordingFile(content="Señal"), file_name="crag.txt"
    )

    assert (repository_dir / saved_path).read_bytes() == "Señal".encode("latin-1")


def test_local_repository_raises_and_removes_file_when_text_cannot_be_encoded(
    repository_dir: Path,
) -> None:
    """Check that text the encoding cannot represent raises and leaves no file."""
    ascii_repository: LocalRepository = LocalRepository(
        config=LocalRepositoryConfig(
            base_url="/files",
            base_root=repository_dir,
            path_generator=FixedPathGenerator(config=FixedPathGeneratorConfig()),
            encoding="ascii",
        )
    )

    with pytest.raises(RepositoryError, match=r"crag.txt") as raised_error:
        ascii_repository.save(ChunkRecordingFile(content="Señal"), file_name="crag.txt")

    assert isinstance(raised_error.value.__cause__, UnicodeEncodeError)
    assert not (repository_dir / "crag.txt").exists()


def test_local_repository_config_raises_when_encoding_is_unknown(
    repository_dir: Path,
) -> None:
    """Check that an encoding Python does not know is rejected."""
    with pytest.raises(ValidationError, match=r"Unknown encoding 'utf-9'"):
        LocalRepositoryConfig(
            base_url="/files",
            base_root=repository_dir,
            path_generator=FixedPathGenerator(config=FixedPathGeneratorConfig()),
            encoding="utf-9",
        )


@pytest.fixture
def existing_file_path(repository_dir: Path) -> Path:
    """Create the file ``example.md`` in the repository with earlier content."""
    repository_dir.mkdir(parents=True)
    existing_file_path: Path = repository_dir / "example.md"
    existing_file_path.write_text("content saved earlier")
    return existing_file_path


def test_local_repository_overwrite_keeps_existing_file_when_copy_fails(
    local_repository: LocalRepository,
    repository_dir: Path,
    existing_file_path: Path,
    small_chunks: int,
) -> None:
    """Check that a failed overwrite leaves the old file unchanged and no temporary file."""
    failing_file: ChunkRecordingFile = ChunkRecordingFile(
        content="new content", failing_read_number=2
    )

    with pytest.raises(RepositoryError, match=r"Could not save 'example.md'"):
        local_repository.save(failing_file, file_name="example.md", overwrite=True)

    assert existing_file_path.read_text() == "content saved earlier"
    assert list(repository_dir.iterdir()) == [existing_file_path]


def test_local_repository_overwrite_leaves_no_temporary_file(
    local_repository: LocalRepository,
    repository_dir: Path,
    existing_file_path: Path,
) -> None:
    """Check that a successful overwrite leaves only the final file in the folder."""
    local_repository.save(ChunkRecordingFile(content="new"), file_name="example.md", overwrite=True)

    assert list(repository_dir.iterdir()) == [existing_file_path]
    assert existing_file_path.read_text() == "new"


def test_local_repository_overwrite_keeps_existing_file_when_replace_fails(
    local_repository: LocalRepository,
    repository_dir: Path,
    existing_file_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that a failed final rename keeps the old file and removes the temporary one."""

    def failing_replace(source: Path, destination: Path) -> None:
        """Fail like a rename refused by the file system."""
        raise PermissionError("rename refused")

    monkeypatch.setattr("cragradar_backend.repos.local.os.replace", failing_replace)

    with pytest.raises(RepositoryError, match=r"Could not save") as raised_error:
        local_repository.save(
            ChunkRecordingFile(content="new"), file_name="example.md", overwrite=True
        )

    assert isinstance(raised_error.value.__cause__, PermissionError)
    assert existing_file_path.read_text() == "content saved earlier"
    assert list(repository_dir.iterdir()) == [existing_file_path]


def test_local_repository_overwrite_creates_file_that_does_not_exist_yet(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that ``overwrite=True`` also saves a file that is new."""
    saved_path: Path = local_repository.save(
        ChunkRecordingFile(content="new"), file_name="new.txt", overwrite=True
    )

    assert list(repository_dir.iterdir()) == [repository_dir / saved_path]
    assert (repository_dir / saved_path).read_text() == "new"


def test_local_repository_overwrite_gives_same_permissions_as_a_new_file(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that the temporary file does not leave owner-only permissions on the result."""
    new_file_path: Path = local_repository.save(
        ChunkRecordingFile(content="a"), file_name="new.txt"
    )
    overwritten_path: Path = local_repository.save(
        ChunkRecordingFile(content="b"), file_name="other.txt", overwrite=True
    )

    assert (repository_dir / overwritten_path).stat().st_mode == (
        repository_dir / new_file_path
    ).stat().st_mode


def test_local_repository_raises_invalid_file_name_error_before_writing(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that an unusable name is reported clearly and nothing is created."""
    with pytest.raises(InvalidFileNameError, match=r"'uploads/\.\.' has no usable file name"):
        local_repository.save(ChunkRecordingFile(content="data"), file_name="uploads/..")

    assert not repository_dir.exists()


# --------------------------------------------------------------------------- #
# base_url, build_url and resolve_path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("base_url", "expected_base_url"),
    [("/files", "/files"), ("/tiles/storage/", "/tiles/storage"), ("/", "/")],
)
def test_local_repository_config_keeps_base_url_without_trailing_slash(
    repository_dir: Path, base_url: str, expected_base_url: str
) -> None:
    """Check that ``base_url`` is normalised, so URLs never get a double slash."""
    config: LocalRepositoryConfig = LocalRepositoryConfig(
        base_url=base_url,
        base_root=repository_dir,
        path_generator=FixedPathGenerator(config=FixedPathGeneratorConfig()),
    )

    assert config.base_url == expected_base_url


def test_local_repository_config_raises_when_base_url_is_not_a_url_path(
    repository_dir: Path,
) -> None:
    """Check that ``base_url`` must start with ``/``."""
    with pytest.raises(ValidationError, match=r"must be a URL path starting with '/'"):
        LocalRepositoryConfig(
            base_url="files",
            base_root=repository_dir,
            path_generator=FixedPathGenerator(config=FixedPathGeneratorConfig()),
        )


def test_local_repository_builds_url_of_a_saved_file(local_repository: LocalRepository) -> None:
    """Check that the URL of a file is its relative path under ``base_url``."""
    assert local_repository.build_url(Path("2026/10/26/sketch.tif")) == (
        "/files/2026/10/26/sketch.tif"
    )


def test_local_repository_resolves_url_of_saved_file_to_its_physical_location(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that the URL of a saved file leads to the file under ``base_root``."""
    saved_path: Path = local_repository.save(
        ChunkRecordingFile(content="data"), file_name="sketch.png"
    )

    resolved_path: Path = local_repository.resolve_path(url=local_repository.build_url(saved_path))

    assert resolved_path == (repository_dir / "sketch.png").resolve()
    assert resolved_path.read_text() == "data"


def test_local_repository_resolves_full_url_with_host(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that a full URL, as requested by OpenSeadragon, is accepted."""
    local_repository.save(ChunkRecordingFile(content="data"), file_name="sketch.png")

    resolved_path: Path = local_repository.resolve_path(url="http://app.com/files/sketch.png")

    assert resolved_path == (repository_dir / "sketch.png").resolve()


def test_local_repository_resolves_urls_of_a_date_path_generator(repository_dir: Path) -> None:
    """Check that URLs with date folders resolve inside ``base_root``."""
    date_repository: RepositoryAbstract = racker.instantiate_from_dict(
        base_class=RepositoryAbstract,
        config_dict={
            "type": "local",
            "base_url": "/tiles/storage",
            "base_root": str(repository_dir),
            "path_generator": {"type": "date"},
        },
    )

    saved_path: Path = date_repository.save(
        ChunkRecordingFile(content="data"), file_name="sketch.png"
    )
    saved_url: str = date_repository.build_url(saved_path)

    assert saved_url == f"/tiles/storage/{saved_path.as_posix()}"
    assert date_repository.resolve_path(url=saved_url).read_text() == "data"


@pytest.fixture
def outside_file_path(repository_dir: Path) -> Iterator[Path]:
    """Write a file next to, but outside, the repository folder."""
    outside_file_path: Path = TMP_DIR / "outside_local_repository.txt"
    outside_file_path.parent.mkdir(parents=True, exist_ok=True)
    outside_file_path.write_text("secret")
    yield outside_file_path
    outside_file_path.unlink()


@pytest.mark.parametrize("url", ["/other/sketch.png", "/filesystem/sketch.png", "/files"])
def test_local_repository_raises_when_url_is_not_under_base_url(
    local_repository: LocalRepository, url: str
) -> None:
    """Check that URLs outside ``base_url``, even sharing its prefix, are not stored files."""
    with pytest.raises(StoredFileNotFoundError, match=r"is not under '/files'"):
        local_repository.resolve_path(url=url)


def test_local_repository_raises_when_no_file_is_stored_at_the_url(
    local_repository: LocalRepository,
) -> None:
    """Check that a URL with no stored file is reported as not stored."""
    with pytest.raises(StoredFileNotFoundError, match=r"No file stored at '/files/missing.png'"):
        local_repository.resolve_path(url="/files/missing.png")


def test_local_repository_raises_when_relative_path_leaves_base_root(
    local_repository: LocalRepository,
    outside_file_path: Path,
) -> None:
    """Check that ``..`` cannot reach an existing file outside ``base_root``."""
    with pytest.raises(StoredFileNotFoundError):
        local_repository.resolve_path(url=f"/files/../{outside_file_path.name}")


def test_local_repository_raises_when_absolute_path_leaves_base_root(
    local_repository: LocalRepository,
    outside_file_path: Path,
) -> None:
    """Check that an absolute path after ``base_url`` cannot reach a file outside ``base_root``."""
    with pytest.raises(StoredFileNotFoundError):
        local_repository.resolve_path(url=f"/files/{outside_file_path}")


def test_local_repository_raises_when_url_points_to_a_folder(
    local_repository: LocalRepository,
    repository_dir: Path,
) -> None:
    """Check that a folder inside ``base_root`` is not a stored file."""
    (repository_dir / "2026").mkdir(parents=True)

    with pytest.raises(StoredFileNotFoundError):
        local_repository.resolve_path(url="/files/2026")
