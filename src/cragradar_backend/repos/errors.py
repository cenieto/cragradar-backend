"""Errors raised by repositories."""


class RepositoryError(Exception):
    """A repository could not store a file.

    The original error, such as an ``OSError`` from the file system, is kept as
    ``__cause__``.
    """


class InvalidFileNameError(RepositoryError, ValueError):
    """A file name cannot be used to store a file.

    Raised for names that leave no usable file name, such as an empty name, ``.``,
    ``..`` or a name containing a NUL character.
    """


class FileAlreadyStoredError(RepositoryError):
    """A file already exists at the location and overwriting was not requested."""


class StoredFileNotFoundError(RepositoryError, LookupError):
    """No file is stored at the requested path inside the repository."""
