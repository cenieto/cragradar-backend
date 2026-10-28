"""Fixtures shared by the tests of the API, the tile server and the worker."""

import os
import shutil
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from cragradar_backend.core.database import get_session
from cragradar_backend.core.security import AccessTokenVerifier, get_token_verifier
from cragradar_backend.core.settings import Settings, get_settings
from cragradar_backend.models import Base
from cragradar_backend.tiles.cache import PhysicalPyramidPathCache, get_path_cache
from test.config import TMP_DIR

ISSUER: str = "http://cragradar.test/auth/realms/cragradar"
AUDIENCE: str = "cragradar-backend"

signing_private_key: rsa.RSAPrivateKey = rsa.generate_private_key(
    public_exponent=65537, key_size=2048
)
signing_public_jwk: jwt.PyJWK = jwt.PyJWK(
    jwt.algorithms.RSAAlgorithm.to_jwk(signing_private_key.public_key(), as_dict=True),
    algorithm="RS256",
)

TokenFactory = Callable[..., str]


def make_token(
    subject: str = "user-1",
    roles: tuple[str, ...] = (),
    **claim_overrides: Any,
) -> str:
    """Sign an access token like Keycloak does, with realm roles and the given claims."""
    now: int = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "iat": now,
        "exp": now + 300,
        "realm_access": {"roles": list(roles)},
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, signing_private_key, algorithm="RS256")


def bearer(
    token: str,
) -> dict[str, str]:
    """Build the ``Authorization`` header of a token."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``CRAGRADAR_*`` variable, so settings come only from the tests."""
    name: str
    for name in list(os.environ):
        is_cragradar_variable: bool = name.startswith("CRAGRADAR_")
        if is_cragradar_variable:
            monkeypatch.delenv(name)


@pytest.fixture
def work_dir() -> Iterator[Path]:
    """Give a folder for the database, repository and staging files; delete it afterwards."""
    work_dir: Path = TMP_DIR / "backend"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    yield work_dir
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture
def settings(work_dir: Path) -> Settings:
    """Build settings with a SQLite database, a local repository and a staging folder."""
    return Settings(
        oidc={"issuer": ISSUER, "jwks_url": "http://keycloak.test/certs"},
        database={"url": f"sqlite+aiosqlite:///{work_dir / 'test.db'}"},
        repository={
            "type": "local",
            "base_url": "/storage",
            "base_root": str(work_dir / "images"),
            "path_generator": {"type": "date"},
        },
        upload={"staging_root": str(work_dir / "staging"), "max_size_bytes": 10_000_000},
        worker={"poll_interval_seconds": 0.1, "lease_seconds": 60},
    )


@pytest.fixture
def session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Create the tables and give a factory of sessions on the test database."""
    sync_url: str = settings.database.async_url.replace("sqlite+aiosqlite", "sqlite")
    sync_engine: Any = create_engine(sync_url)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    return async_sessionmaker(
        create_async_engine(settings.database.async_url, poolclass=NullPool),
        expire_on_commit=False,
    )


def override_dependencies(
    app: FastAPI,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Make an app use the test settings, database, signing key and a fresh path cache."""

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        """Give a session on the test database."""
        async with session_factory() as session:
            yield session

    test_verifier: AccessTokenVerifier = AccessTokenVerifier(
        issuer=ISSUER, audience=AUDIENCE, resolve_signing_key=lambda token: signing_public_jwk
    )
    test_path_cache: PhysicalPyramidPathCache = PhysicalPyramidPathCache(max_entries=16)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_token_verifier] = lambda: test_verifier
    app.dependency_overrides[get_path_cache] = lambda: test_path_cache


@pytest.fixture
def api_client(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Iterator[TestClient]:
    """Give a client of the API app wired to the test settings and database."""
    from cragradar_backend.api.main import app

    override_dependencies(app=app, settings=settings, session_factory=session_factory)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def tiles_client(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Iterator[TestClient]:
    """Give a client of the tile app wired to the test settings and database."""
    from cragradar_backend.tiles.main import app

    override_dependencies(app=app, settings=settings, session_factory=session_factory)
    yield TestClient(app)
    app.dependency_overrides.clear()


def write_gradient(path: Path, width: int = 1000, height: int = 600) -> Path:
    """Write a grey gradient PNG of the given size."""
    import pyvips

    path.parent.mkdir(parents=True, exist_ok=True)
    pyvips.Image.xyz(width, height)[0].cast("uchar").write_to_file(str(path))
    return path


def queue_upload(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    source_path: Path,
    file_name: str = "crag.png",
) -> Any:
    """Record a complete upload of ``source_path``, as the tus endpoints leave it."""
    import asyncio
    import uuid

    from cragradar_backend.ingest.staging import get_upload_path
    from cragradar_backend.models.image import Image, ImageStatus

    image_id: uuid.UUID = uuid.uuid4()
    upload_path: Path = get_upload_path(settings.upload.staging_root, image_id)
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, upload_path)

    async def insert() -> None:
        """Insert the uploaded image row."""
        async with session_factory() as session:
            session.add(
                Image(
                    id=image_id,
                    file_name=file_name,
                    size_bytes=upload_path.stat().st_size,
                    status=ImageStatus.UPLOADED,
                    created_by="editor-1",
                )
            )
            await session.commit()

    asyncio.run(insert())
    return image_id


def ingest_upload(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    source_path: Path,
) -> Any:
    """Queue an upload of ``source_path`` and let the worker build its pyramid."""
    import asyncio

    from cragradar_backend.worker.jobs import ClaimedImage, claim_next_image, process_image

    image_id: Any = queue_upload(settings, session_factory, source_path)

    async def process() -> None:
        """Claim and process the queued image."""
        claimed_image: ClaimedImage | None = await claim_next_image(
            session_factory, lease_seconds=60
        )
        assert claimed_image is not None
        await process_image(session_factory, settings, claimed_image)

    asyncio.run(process())
    return image_id
