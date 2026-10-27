"""Path generator that stores files in one folder per day."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator

from cragradar_backend.racker.registry import racker
from cragradar_backend.repos.abcs import PathGeneratorAbstract, PathGeneratorConfigAbstract


class DatePathGeneratorConfig(PathGeneratorConfigAbstract):
    """Configuration of ``DatePathGenerator``.

    Daily folders are created at the repository root.

    Attributes:
        timezone: IANA name of the timezone that decides the current day.
    """

    type: Literal["date"] = "date"
    timezone: str = "UTC"

    @field_validator("timezone", mode="after")
    @classmethod
    def validate_timezone(
        cls,
        value: str,
    ) -> str:
        """Check that the timezone is a valid IANA timezone name.

        Args:
            value: Timezone name to check.

        Returns:
            str: The timezone name, unchanged.

        Raises:
            ValueError: If ``value`` is not a known IANA timezone name.
        """
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(
                f"Invalid timezone '{value}'. Use an IANA name such as 'UTC' or 'Europe/Madrid'."
            ) from error
        return value

    @property
    def tzinfo(
        self,
    ) -> ZoneInfo:
        """Return the timezone object of ``timezone``.

        Returns:
            ZoneInfo: Timezone used to compute the current day.
        """
        return ZoneInfo(self.timezone)


def utc_now() -> datetime:
    """Return the current time in UTC.

    Returns:
        datetime: Timezone-aware current time.
    """
    return datetime.now(tz=UTC)


class DatePathGenerator(PathGeneratorAbstract):
    """Path generator that stores files in ``YYYY/MM/DD`` folders of the repository.

    The day is taken from ``clock``, converted to the configured timezone. Pass a clock
    that returns a fixed time to get a known date, for example in tests.
    """

    def __init__(
        self,
        config: DatePathGeneratorConfig,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Initialize the date path generator with a configuration object.

        Args:
            config: Configuration of the path generator.
            clock: Function returning the current time as a timezone-aware datetime.
        """
        super().__init__(config=config)
        self.tzinfo: ZoneInfo = config.tzinfo
        self.clock: Callable[[], datetime] = clock

    def generate_path(
        self,
        file_name: str,
    ) -> Path:
        """Generate the path of a file inside the folder of the current day.

        Args:
            file_name: Name of the file to store; only its last part is used.

        Returns:
            Path: ``YYYY / MM / DD / <file name>``, with the date of
                ``clock`` in the configured timezone.

        Raises:
            InvalidFileNameError: If the name of the file cannot be used.
            ValueError: If ``clock`` returns a datetime without timezone.
        """
        last_name_part: str = self._get_file_name(file_name)
        current_time: datetime = self.clock()
        is_naive_time: bool = current_time.tzinfo is None
        if is_naive_time:
            raise ValueError("The clock must return a timezone-aware datetime")

        date_today: date = current_time.astimezone(self.tzinfo).date()
        date_subdir: str = date_today.strftime("%Y/%m/%d")
        return Path(date_subdir) / last_name_part


racker.register(
    class_=DatePathGenerator,
    config_class=DatePathGeneratorConfig,
    base_class=PathGeneratorAbstract,
)
