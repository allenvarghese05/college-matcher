from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_session

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    db_ok = False
    try:
        db_ok = (await session.execute(text("SELECT 1"))).scalar_one() == 1
    except Exception as exc:  # DB down must not 500 the health route
        log.warning("health_db_unreachable", error=type(exc).__name__)
    return {"status": "ok", "db": db_ok}
