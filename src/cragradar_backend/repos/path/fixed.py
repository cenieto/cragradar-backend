"""Path generator that stores every file in the same folder."""

from pathlib import Path
from typing import Literal

from cragradar_backend.racker.registry import racker
from cragradar_backend.repos.abcs import PathGeneratorAbstract, PathGeneratorConfigAbstract


class FixedPathGeneratorConfig(PathGeneratorConfigAbstract):
    """Configuration of ``FixedPathGenerator``; every file is stored at the repository root."""

    type: Literal["fixed"] = "fixed"


class FixedPathGenerator(PathGeneratorAbstract):
    """Path generator that stores every file directly at the repository root."""

    def __init__(
        self,
        config: FixedPathGeneratorConfig,
    ) -> None:
        """Initialize the fixed path generator with a configuration object.

        Args:
            config: Configuration of the path generator.
        """
        super().__init__(config=config)

    def generate_path(
        self,
        file_name: str,
    ) -> Path:
        """Generate the path of a file at the repository root.

        Args:
            file_name: Name of the file to store; only its last part is used.

        Returns:
            Path: ``<file name>``.

        Raises:
            InvalidFileNameError: If the name of the file cannot be used.
        """
        last_name_part: str = self._get_file_name(file_name)
        return Path(last_name_part)


racker.register(
    class_=FixedPathGenerator,
    config_class=FixedPathGeneratorConfig,
    base_class=PathGeneratorAbstract,
)
