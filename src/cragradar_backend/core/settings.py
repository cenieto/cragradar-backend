"""Configuration, read from ``CRAGRADAR_*`` environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRAGRADAR_")

    # Public issuer URL: must equal the `iss` claim of the tokens, as seen by the browser.
    oidc_issuer: str
    # Internal URL of the signing keys, reachable from inside the cluster.
    oidc_jwks_url: str
    oidc_audience: str = "cragradar-backend"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
