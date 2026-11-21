"""Prepare the eval smoke database: create it (``*_test`` names only), migrate, load the
committed ~200-school fixture. Idempotent; used by ``make eval-replay`` and CI.

The replay cassettes in ``backend/tests/cassettes/evals`` were recorded against exactly
this state (fixture data, FakeEmbedder queries), so don't point it at a database that
other tests write schools into (pytest's ``matcher_test`` gets extra rows).

    DATABASE_URL=postgresql+asyncpg://matcher:matcher@localhost:5433/matcher_evalsmoke_test \
        uv run python ../evals/db_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [p for p in (str(_REPO), str(_REPO / "backend")) if p not in sys.path]

import asyncio  # noqa: E402

from sqlalchemy import make_url, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402

BACKEND = _REPO / "backend"


async def ensure_database(url: str) -> str:
    name = make_url(url).database or ""
    if not name.endswith("_test") or not name.replace("_", "").isalnum():
        raise SystemExit(f"refusing to set up {name!r}: eval smoke DB name must end in _test")
    admin = create_async_engine(
        make_url(url).set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()
    return name


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


async def load() -> None:
    from app.db.session import dispose_engine, get_sessionmaker
    from ingest.load import load_fixture

    try:
        async with get_sessionmaker()() as session, session.begin():
            counts = await load_fixture(session)
    finally:
        await dispose_engine()
    print(f"fixture loaded: {counts.institutions} institutions, {counts.programs} programs")


def main() -> int:
    url = get_settings().DATABASE_URL
    name = asyncio.run(ensure_database(url))
    migrate()
    asyncio.run(load())
    print(f"eval DB ready: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
