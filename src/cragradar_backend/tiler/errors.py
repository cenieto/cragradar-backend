"""Errors raised by tilers."""


class TileNotFoundError(LookupError):
    """The requested level or tile does not exist for the image."""


class UnreadableImageError(ValueError):
    """The stored file is not an image that can be read."""
