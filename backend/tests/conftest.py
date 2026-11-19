from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import dispose_engine, get_engine
from app.main import create_app


async def _db_reachable() -> bool:
    try:
        async with asyncio.timeout(3):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await dispose_engine()


@pytest.fixture(scope="session")
async def db_available() -> bool:
    return await _db_reachable()


@pytest.fixture
async def requires_db(db_available: bool) -> None:
    """Skip (rather than fail) DB tests when Postgres isn't running locally.

    In CI set REQUIRE_DB=1 so an unreachable DB is a hard failure.
    """
    import os

    if not db_available:
        msg = f"Postgres unreachable at {get_settings().DATABASE_URL.split('@')[-1]}"
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(msg)
        pytest.skip(msg + " (run `make db-up`)")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()
