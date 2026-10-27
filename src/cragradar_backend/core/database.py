"""Asynchronous SQLAlchemy engine and sessions."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cragradar_backend.core.settings import DatabaseSettings, get_settings


def build_engine(
    database_settings: DatabaseSettings,
) -> AsyncEngine:
    """Build the engine of a database.

    Args:
        database_settings: Connection URL and options.

    Returns:
        AsyncEngine: Engine with a connection pool; connections are checked before reuse.
    """
    return create_async_engine(
        database_settings.async_url,
        echo=database_settings.echo,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory of the process, built once from the settings.

    Returns:
        async_sessionmaker[AsyncSession]: Factory of sessions that keep objects usable after
            commit.
    """
    engine: AsyncEngine = build_engine(database_settings=get_settings().database)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency giving one session per request.

    Yields:
        AsyncSession: The session, closed when the request ends.
    """
    session_factory: async_sessionmaker[AsyncSession] = get_session_factory()
    async with session_factory() as session:
        yield session
