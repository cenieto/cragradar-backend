"""Database models. Importing this package registers every table in ``Base.metadata``."""

from cragradar_backend.models.base import Base
from cragradar_backend.models.image import Image, ImageStatus

__all__ = ["Base", "Image", "ImageStatus"]
