from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

import setvault_core.models  # noqa: F401 — registers all model modules
from alembic import context
from setvault_core.models import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

env_url = os.environ.get("DATABASE_URL")
if env_url:
    # Alembic's Config is a ConfigParser with %-interpolation, so a URL-encoded
    # password (p%40ss) must have its % escaped or set_main_option raises.
    config.set_main_option("sqlalchemy.url", env_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
