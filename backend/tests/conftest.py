from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import dispose_engine, get_engine
from app.main import create_app

BACKEND = Path(__file__).resolve().parents[1]


def _test_db_name() -> str | None:
    """Database name in DATABASE_URL if it is a dedicated test DB (``*_test``)."""
    name = make_url(get_settings().DATABASE_URL).database or ""
    return name if name.endswith("_test") else None


async def _ensure_test_db() -> None:
    """Create the ``*_test`` database if missing (CI and `make test`). Never other DBs."""
    name = _test_db_name()
    if name is None or not name.replace("_", "").isalnum():
        return  # only plain identifiers are ever interpolated into CREATE DATABASE
    url = make_url(get_settings().DATABASE_URL).set(database="postgres")
    engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with asyncio.timeout(3):
            async with engine.connect() as conn:
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                )
                if not exists:
                    await conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception:
        pass  # server down: _db_reachable reports it
    finally:
        await engine.dispose()


async def _db_reachable() -> bool:
    await _ensure_test_db()
    try:
        async with asyncio.timeout(3):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await dispose_engine()


def _skip_or_fail_no_db() -> None:
    msg = f"Postgres unreachable at {get_settings().DATABASE_URL.split('@')[-1]}"
    if os.environ.get("REQUIRE_DB") == "1":
        pytest.fail(msg)
    pytest.skip(msg + " (run `make db-up`)")


@pytest.fixture(scope="session")
async def db_available() -> bool:
    return await _db_reachable()


@pytest.fixture
async def requires_db(db_available: bool) -> None:
    """Skip (rather than fail) DB tests when Postgres isn't running locally.

    In CI set REQUIRE_DB=1 so an unreachable DB is a hard failure.
    """
    if not db_available:
        _skip_or_fail_no_db()


def _migrate() -> None:
    """`alembic upgrade head` on DATABASE_URL. Runs in a thread (env.py calls asyncio.run)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()  # no ini file -> env.py skips fileConfig, pytest logging untouched
    cfg.set_main_option("script_location", str(BACKEND / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def loaded_db(db_available: bool) -> AsyncIterator[None]:
    """Once per test session: migrate, then load the committed fixture (idempotent upsert).

    CIP embeddings come from data/fixtures/cip_embeddings.jsonl; any cip_code row
    still without one (file not generated yet) gets a FakeEmbedder vector so pgvector
    queries work. This COMMITS the sample data, so it refuses (fails) unless the
    database name ends in ``_test`` or TEST_DB_WRITES=1 is set.
    Skips when Postgres is unreachable (fails under REQUIRE_DB=1).
    """
    if not db_available:
        _skip_or_fail_no_db()
    if _test_db_name() is None and os.environ.get("TEST_DB_WRITES") != "1":
        db = make_url(get_settings().DATABASE_URL).database
        pytest.fail(
            f"refusing to load test data (incl. FakeEmbedder vectors) into database {db!r}: "
            "point DATABASE_URL at a *_test database (`make test` uses matcher_test) "
            "or set TEST_DB_WRITES=1"
        )
    from app.retrieval.embedder import FakeEmbedder
    from ingest.load import load_fixture

    await asyncio.to_thread(_migrate)
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session, session.begin():
            await load_fixture(session, fallback_embedder=FakeEmbedder())
    finally:
        await engine.dispose()
    yield


@pytest.fixture
async def db_session(loaded_db: None) -> AsyncIterator[AsyncSession]:
    """AsyncSession inside an outer transaction that is rolled back after the test.

    Depends on ``loaded_db`` (schema + sample data present). ``session.commit()`` in
    code under test only releases a SAVEPOINT, so nothing a test writes survives.
    """
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            session = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            try:
                yield session
            finally:
                await session.close()
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()
