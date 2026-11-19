"""Async Alembic environment. DATABASE_URL comes from app settings."""

from __future__ import annotations

import asyncio
import importlib
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)


def _load_metadata() -> Any:
    """Import model metadata lazily so migrations work before models exist."""
    try:
        models = importlib.import_module("app.db.models")
    except ModuleNotFoundError as exc:
        if exc.name != "app.db.models":
            raise  # a real import error inside models.py should surface
        return None
    base = getattr(models, "Base", None)
    return getattr(models, "metadata", None) or (base.metadata if base is not None else None)


target_metadata = _load_metadata()


def _include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    # Never autogenerate drops for tables Alembic doesn't know about (e.g. extension tables).
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
    )
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
