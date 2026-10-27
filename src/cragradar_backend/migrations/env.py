"""Alembic environment: runs migrations on the database of the settings."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from cragradar_backend.core.database import build_engine
from cragradar_backend.core.settings import get_settings
from cragradar_backend.models import Base


def run_migrations_on_connection(
    connection: Connection,
) -> None:
    """Run the pending migrations in one transaction.

    Args:
        connection: Open connection to the database.
    """
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations() -> None:
    """Connect to the database of the settings and run the pending migrations."""
    engine: AsyncEngine = build_engine(database_settings=get_settings().database)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations_on_connection)
    await engine.dispose()


asyncio.run(run_migrations())
