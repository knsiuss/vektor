from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""


def create_engine(database_url: str) -> AsyncEngine:
    """Create a configured AsyncEngine compatible with SQLite and PostgreSQL/Supabase."""
    connect_args: dict[str, Any] = {}
    if database_url.startswith("postgresql+asyncpg"):
        connect_args["statement_cache_size"] = 0

    return create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def init_db(engine: AsyncEngine) -> None:
    """Create database tables from registered metadata if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
