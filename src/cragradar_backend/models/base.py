"""Declarative base of the database models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Names of constraints and indexes, so that migrations can refer to them."""


class Base(DeclarativeBase):
    """Base class of every model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
