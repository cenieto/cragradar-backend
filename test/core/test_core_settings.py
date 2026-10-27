"""Settings read from the YAML file of the ConfigMap and from environment variables."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from test.conftest import ISSUER

from cragradar_backend.core.settings import SETTINGS_FILE_ENVIRONMENT_VARIABLE, Settings
from cragradar_backend.repos.local import LocalRepository
from cragradar_backend.tiler.deepzoom import DeepZoomTiler

SETTINGS_YAML: str = """
oidc:
  issuer: http://from-file/auth/realms/cragradar
  jwks_url: http://keycloak/certs
database:
  url: postgresql://cragradar:secret@postgres-rw:5432/cragradar
repository:
  type: local
  base_url: /storage
  base_root: /data/images
  path_generator:
    type: date
    timezone: Europe/Madrid
tiler:
  type: deepzoom
  tile_size: 510
upload:
  staging_root: /data/staging
"""


@pytest.fixture
def settings_file(work_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write the YAML settings file and point ``CRAGRADAR_SETTINGS_FILE`` at it."""
    settings_file: Path = work_dir / "settings.yaml"
    settings_file.write_text(SETTINGS_YAML)
    monkeypatch.setenv(SETTINGS_FILE_ENVIRONMENT_VARIABLE, str(settings_file))
    return settings_file


def test_settings_are_read_from_the_file(settings_file: Path) -> None:
    """Check that the file builds the repository and tiler and fills the defaults."""
    settings: Settings = Settings()  # type: ignore[call-arg]

    assert isinstance(settings.repository, LocalRepository)
    assert settings.repository.base_root == Path("/data/images")
    assert isinstance(settings.tiler, DeepZoomTiler)
    assert settings.tiler.tile_settings.tile_size == 510
    assert settings.pyramid.compression == "jpeg"


def test_environment_overrides_the_file(
    settings_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check that nested environment variables win over the file and keep their siblings."""
    monkeypatch.setenv("CRAGRADAR_OIDC__ISSUER", ISSUER)
    monkeypatch.setenv("CRAGRADAR_DATABASE__URL", "postgresql://app:from-secret@db:5432/app")

    settings: Settings = Settings()  # type: ignore[call-arg]

    assert settings.oidc.issuer == ISSUER
    assert settings.oidc.jwks_url == "http://keycloak/certs"
    assert settings.database.url.get_secret_value().endswith("from-secret@db:5432/app")


def test_postgresql_url_uses_the_asyncpg_driver(settings_file: Path) -> None:
    """Check that the CloudNativePG URI is turned into an asyncpg URL."""
    settings: Settings = Settings()  # type: ignore[call-arg]

    assert settings.database.async_url.startswith("postgresql+asyncpg://cragradar:secret@")


def test_missing_required_section_is_rejected() -> None:
    """Check that settings without a file nor environment fail validation."""
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
