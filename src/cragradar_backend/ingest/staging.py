"""Location of the files of an image while it is uploaded and processed."""

import uuid
from pathlib import Path


def get_upload_path(
    staging_root: Path,
    image_id: uuid.UUID,
) -> Path:
    """Get the file that receives the bytes of an upload.

    Args:
        staging_root: Folder of the staging files.
        image_id: Image being uploaded.

    Returns:
        Path: ``<staging_root>/<image id>.upload``.
    """
    return staging_root / f"{image_id}.upload"


def get_pyramid_scratch_path(
    staging_root: Path,
    image_id: uuid.UUID,
) -> Path:
    """Get the file the worker writes the pyramid into before storing it.

    Args:
        staging_root: Folder of the staging files.
        image_id: Image being processed.

    Returns:
        Path: ``<staging_root>/<image id>.pyramid.tif``.
    """
    return staging_root / f"{image_id}.pyramid.tif"
