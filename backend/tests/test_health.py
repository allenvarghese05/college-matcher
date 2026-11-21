from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.usefixtures("requires_db")
async def test_health_hits_real_db(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": True}


async def test_health_reports_db_false_when_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.session import dispose_engine

    await dispose_engine()
    monkeypatch.setattr(
        get_settings(), "DATABASE_URL", "postgresql+asyncpg://nobody:x@127.0.0.1:1/none"
    )
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": False}
    await dispose_engine()


async def test_cors_allows_vite_dev_origin(client: AsyncClient) -> None:
    resp = await client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
