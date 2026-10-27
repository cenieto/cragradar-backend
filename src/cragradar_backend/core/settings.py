"""Settings of every backend process (api, tiles, worker), read with pydantic-settings.

Sources, from highest to lowest priority:

1. Values passed to ``Settings(...)``, used by tests.
2. ``CRAGRADAR_*`` environment variables. Nested fields use ``__``, such as
   ``CRAGRADAR_OIDC__ISSUER``. Kubernetes sets the values that depend on the environment or
   are secret this way. ``repository`` and ``tiler`` are built by ``racker`` and are only
   read from the file: pydantic-settings does not split variables into their fields.
3. The YAML file named by ``CRAGRADAR_SETTINGS_FILE``, mounted from a ConfigMap.
4. Field defaults.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

import cragradar_backend.repos  # noqa: F401  # registers the repositories in racker
import cragradar_backend.tiler  # noqa: F401  # registers the tilers in racker
from cragradar_backend.racker.validators import Built
from cragradar_backend.repos.abcs import RepositoryAbstract
from cragradar_backend.tiler.abcs import TilerAbstract
from cragradar_backend.tiler.deepzoom import DeepZoomTiler, DeepZoomTilerConfig

SETTINGS_FILE_ENVIRONMENT_VARIABLE: str = "CRAGRADAR_SETTINGS_FILE"
"""Environment variable holding the path of the YAML settings file."""

GIBIBYTE: int = 1024**3


class SectionSettings(BaseModel):
    """Base of the settings sections: immutable, no extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class OidcSettings(SectionSettings):
    """Validation of the access tokens issued by Keycloak.

    Attributes:
        issuer: Public issuer URL. It must equal the ``iss`` claim of the tokens, as seen by
            the browser.
        jwks_url: URL of the signing keys, reachable from inside the cluster.
        audience: Audience the tokens must be issued for.
        signing_keys_cache_seconds: How long downloaded signing keys are reused.
    """

    issuer: str
    jwks_url: str
    audience: str = "cragradar-backend"
    signing_keys_cache_seconds: int = Field(default=300, gt=0)


class DatabaseSettings(SectionSettings):
    """Connection to PostgreSQL.

    Attributes:
        url: Connection URL, such as the ``uri`` key of the ``postgres-app`` Secret created by
            CloudNativePG. ``postgresql://`` URLs are accepted.
        echo: Log every SQL statement.
    """

    url: SecretStr
    echo: bool = False

    @property
    def async_url(
        self,
    ) -> str:
        """Return the URL with the asyncpg driver, as SQLAlchemy needs it.

        Returns:
            str: ``postgresql+asyncpg://...`` for PostgreSQL URLs; other URLs unchanged.
        """
        url: str = self.url.get_secret_value()
        is_plain_postgresql_url: bool = url.startswith(("postgresql://", "postgres://"))
        if not is_plain_postgresql_url:
            return url
        return "postgresql+asyncpg://" + url.split("://", 1)[1]


class UploadSettings(SectionSettings):
    """Resumable uploads.

    Attributes:
        staging_root: Folder where uploads are written while they are received and until the
            worker has processed them. It must be on a volume shared with the worker.
        max_size_bytes: Largest upload accepted.
    """

    staging_root: Path
    max_size_bytes: int = Field(default=10 * GIBIBYTE, gt=0)


class PyramidSettings(SectionSettings):
    """Pyramidal TIFF written by the worker for each image.

    Attributes:
        tile_size: Width and height of the TIFF tiles in pixels.
        compression: Compression of the TIFF tiles.
        quality: Quality of lossy compressions, from 1 to 100.
    """

    tile_size: int = Field(default=256, gt=0)
    compression: Literal["jpeg", "webp", "deflate", "lzw"] = "jpeg"
    quality: int = Field(default=90, ge=1, le=100)


class WorkerSettings(SectionSettings):
    """Ingest worker.

    Attributes:
        poll_interval_seconds: Wait between two checks for new uploads when the queue is empty.
        lease_seconds: Time an image stays assigned to a worker without news from it. When it
            expires, another worker takes the image over.
    """

    poll_interval_seconds: float = Field(default=2.0, gt=0)
    lease_seconds: int = Field(default=120, gt=0)


class Settings(BaseSettings):
    """Settings of the backend.

    Attributes:
        oidc: Validation of access tokens.
        database: Connection to PostgreSQL.
        repository: Repository that stores originals and pyramids, given as its configuration
            dictionary, such as ``{"type": "local", "base_root": "/data/images", ...}``.
        tiler: Tiler that describes pyramids and cuts their tiles, given as its configuration
            dictionary. Defaults to a Deep Zoom tiler with its default settings.
        upload: Resumable uploads.
        pyramid: Pyramidal TIFF written for each image.
        worker: Ingest worker.
    """

    model_config = SettingsConfigDict(
        env_prefix="CRAGRADAR_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    oidc: OidcSettings
    database: DatabaseSettings
    repository: Built[RepositoryAbstract]
    tiler: Built[TilerAbstract] = Field(
        default_factory=lambda: DeepZoomTiler(config=DeepZoomTilerConfig())
    )
    upload: UploadSettings
    pyramid: PyramidSettings = PyramidSettings()
    worker: WorkerSettings = WorkerSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read init values, then environment variables, then the YAML settings file.

        Args:
            settings_cls: The settings class.
            init_settings: Values passed to the constructor.
            env_settings: ``CRAGRADAR_*`` environment variables.
            dotenv_settings: Unused: no ``.env`` file is read.
            file_secret_settings: Unused: secrets come as environment variables.

        Returns:
            tuple[PydanticBaseSettingsSource, ...]: Sources from highest to lowest priority.
        """
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        settings_file: str | None = os.environ.get(SETTINGS_FILE_ENVIRONMENT_VARIABLE)
        is_settings_file_given: bool = settings_file is not None
        if is_settings_file_given:
            sources.append(
                YamlConfigSettingsSource(settings_cls, yaml_file=Path(str(settings_file)))
            )
        return tuple(sources)


@lru_cache
def get_settings() -> Settings:
    """Read the settings once per process.

    Returns:
        Settings: The validated settings, with the repository and tiler already built.

    Raises:
        pydantic.ValidationError: If a required value is missing or a value is invalid.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment and file
