"""Unit tests for the path generators and their ``racker`` registration."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from cragradar_backend.racker.registry import racker
from cragradar_backend.repos.abcs import PathGeneratorAbstract
from cragradar_backend.repos.errors import InvalidFileNameError, RepositoryError
from cragradar_backend.repos.path import (
    DatePathGenerator,
    DatePathGeneratorConfig,
    FixedPathGenerator,
    FixedPathGeneratorConfig,
)
from cragradar_backend.repos.path.date import utc_now

LATE_EVENING_UTC: datetime = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)


@pytest.fixture
def file_name() -> str:
    """Give a file name that includes folders that must be dropped."""
    return "incoming/uploads/photo.jpg"


# --------------------------------------------------------------------------- #
# FixedPathGenerator
# --------------------------------------------------------------------------- #


def test_fixed_path_generator_places_file_at_the_repository_root(
    file_name: str,
) -> None:
    """Check that only the file name is kept, relative to the repository root."""
    fixed_path_generator: FixedPathGenerator = FixedPathGenerator(config=FixedPathGeneratorConfig())

    assert fixed_path_generator.generate_path(file_name) == Path("photo.jpg")


def test_fixed_path_generator_keeps_its_config() -> None:
    """Check that the path generator exposes the config it was built with."""
    fixed_config: FixedPathGeneratorConfig = FixedPathGeneratorConfig()

    assert FixedPathGenerator(config=fixed_config).config is fixed_config


# --------------------------------------------------------------------------- #
# DatePathGenerator
# --------------------------------------------------------------------------- #


def test_date_path_generator_places_file_in_folder_of_the_clock_date(
    file_name: str,
) -> None:
    """Check that the file goes to ``YYYY/MM/DD`` for the date of the clock."""
    date_path_generator: DatePathGenerator = DatePathGenerator(
        config=DatePathGeneratorConfig(),
        clock=lambda: LATE_EVENING_UTC,
    )

    assert date_path_generator.generate_path(file_name) == Path("2026/03/15/photo.jpg")


def test_date_path_generator_uses_the_day_of_the_configured_timezone(
    file_name: str,
) -> None:
    """Check that 23:30 UTC already falls on the next day in Madrid (UTC+1)."""
    date_path_generator: DatePathGenerator = DatePathGenerator(
        config=DatePathGeneratorConfig(timezone="Europe/Madrid"),
        clock=lambda: LATE_EVENING_UTC,
    )

    assert date_path_generator.generate_path(file_name) == Path("2026/03/16/photo.jpg")


def test_date_path_generator_accepts_clock_in_another_timezone(
    file_name: str,
) -> None:
    """Check that a clock time with any offset is converted to the configured timezone."""
    tokyo_morning: datetime = datetime(2026, 3, 16, 8, 30, tzinfo=timezone(timedelta(hours=9)))
    date_path_generator: DatePathGenerator = DatePathGenerator(
        config=DatePathGeneratorConfig(),
        clock=lambda: tokyo_morning,
    )

    assert date_path_generator.generate_path(file_name) == Path("2026/03/15/photo.jpg")


def test_date_path_generator_raises_when_clock_returns_naive_datetime(
    file_name: str,
) -> None:
    """Check that a datetime without timezone is rejected instead of guessed."""
    date_path_generator: DatePathGenerator = DatePathGenerator(
        config=DatePathGeneratorConfig(),
        clock=lambda: datetime(2026, 3, 15, 23, 30),
    )

    with pytest.raises(ValueError, match=r"timezone-aware"):
        date_path_generator.generate_path(file_name)


def test_utc_now_returns_timezone_aware_current_time() -> None:
    """Check that the default clock returns the current time in UTC."""
    current_time: datetime = utc_now()

    assert current_time.tzinfo is UTC
    assert abs(current_time - datetime.now(tz=UTC)) < timedelta(seconds=5)


def test_date_path_generator_config_uses_utc_by_default() -> None:
    """Check that the timezone defaults to UTC."""
    assert DatePathGeneratorConfig().tzinfo == ZoneInfo("UTC")


def test_date_path_generator_config_raises_when_timezone_is_unknown() -> None:
    """Check that a name that is not an IANA timezone is rejected."""
    with pytest.raises(ValidationError, match=r"Invalid timezone 'Mars/Olympus'"):
        DatePathGeneratorConfig(timezone="Mars/Olympus")


# --------------------------------------------------------------------------- #
# File names
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["fixed", "date"])
def path_generator(request: pytest.FixtureRequest) -> PathGeneratorAbstract:
    """Build each path generator, so the file name checks are tested on both."""
    is_fixed_path_generator: bool = request.param == "fixed"
    if is_fixed_path_generator:
        return FixedPathGenerator(config=FixedPathGeneratorConfig())
    return DatePathGenerator(
        config=DatePathGeneratorConfig(),
        clock=lambda: LATE_EVENING_UTC,
    )


@pytest.mark.parametrize("unusable_name", ["", ".", "..", "uploads/..", "/"])
def test_path_generators_raise_when_name_has_no_usable_file_name(
    path_generator: PathGeneratorAbstract,
    unusable_name: str,
) -> None:
    """Check that names leaving no file name, or pointing to a parent, are rejected."""
    with pytest.raises(InvalidFileNameError, match=r"has no usable file name"):
        path_generator.generate_path(unusable_name)


def test_path_generators_raise_when_name_contains_nul_character(
    path_generator: PathGeneratorAbstract,
) -> None:
    """Check that a NUL character, which no file system accepts, is rejected."""
    with pytest.raises(InvalidFileNameError, match=r"NUL character"):
        path_generator.generate_path("photo\x00.jpg")


def test_invalid_file_name_error_is_a_repository_and_value_error() -> None:
    """Check that callers catching ``RepositoryError`` or ``ValueError`` also catch it."""
    assert issubclass(InvalidFileNameError, RepositoryError)
    assert issubclass(InvalidFileNameError, ValueError)


# --------------------------------------------------------------------------- #
# racker registration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("config_dict", "expected_class"),
    [
        ({"type": "fixed"}, FixedPathGenerator),
        ({"type": "date"}, DatePathGenerator),
    ],
)
def test_path_generators_are_built_from_dict_by_racker(
    config_dict: dict[str, str],
    expected_class: type[PathGeneratorAbstract],
) -> None:
    """Check that each path generator is registered in ``racker`` under its ``type``."""
    path_generator: PathGeneratorAbstract = racker.instantiate_from_dict(
        base_class=PathGeneratorAbstract,
        config_dict=config_dict,
    )

    assert type(path_generator) is expected_class


def test_path_generator_configs_reject_unknown_fields() -> None:
    """Check that a misspelled field fails validation instead of being ignored."""
    with pytest.raises(ValidationError, match=r"base_pth"):
        racker.instantiate_from_dict(
            base_class=PathGeneratorAbstract,
            config_dict={"type": "fixed", "base_pth": "/repository"},
        )
