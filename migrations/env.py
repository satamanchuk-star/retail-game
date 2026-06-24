"""Alembic environment: поддержка async SQLAlchemy и автогенерации миграций."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from app.services.orm import Base
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    """URL БД: сначала переменная окружения, потом значение из alembic.ini."""
    env_url = os.getenv("PROFIT_CHAIN_DATABASE_URL")
    if env_url:
        return env_url
    return config.get_main_option("sqlalchemy.url", "sqlite+aiosqlite:///./dev.db")


def run_migrations_offline() -> None:
    """Генерировать SQL без подключения к БД."""
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_online() -> None:
    """Применить миграции через async engine."""
    engine = create_async_engine(_db_url())

    def _do_migrations(sync_conn):  # type: ignore[no-untyped-def]
        context.configure(
            connection=sync_conn,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    async with engine.begin() as connection:
        await connection.run_sync(_do_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
