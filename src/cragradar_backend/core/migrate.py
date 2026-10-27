"""Entry point ``cragradar-migrate``: Alembic, configured for the packaged migrations.

Takes the arguments of the ``alembic`` command, such as ``upgrade head`` or
``revision --autogenerate -m "add tags"``. The database comes from the settings.
"""

import sys
from pathlib import Path

from alembic.config import CommandLine, Config

MIGRATIONS_DIR: Path = Path(__file__).parent.parent / "migrations"


def build_alembic_config() -> Config:
    """Build the Alembic configuration without an ``alembic.ini`` file.

    Returns:
        Config: Configuration pointing at the packaged migrations.
    """
    alembic_config: Config = Config()
    alembic_config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return alembic_config


def main(
    arguments: list[str] | None = None,
) -> None:
    """Run an Alembic command.

    Args:
        arguments: Arguments of the ``alembic`` command; defaults to the command line.
    """
    command_line: CommandLine = CommandLine(prog="cragradar-migrate")
    options = command_line.parser.parse_args(sys.argv[1:] if arguments is None else arguments)
    command_line.run_cmd(build_alembic_config(), options)
