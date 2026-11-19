"""Session routes (contract: ``app.schemas`` module docstring), mounted under ``/api``.

Dependencies (override in tests via ``app.dependency_overrides``):
``get_llm_client``, ``get_retriever``, ``get_orchestrator``, ``get_session``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMClient, LLMError, get_llm_client
from app.core.logging import get_logger
from app.counselor.orchestrator import (
    CounselorOrchestrator,
    NotReady,
    RetrieverProtocol,
    SessionNotFound,
    TurnEvent,
    get_chat_session,
    latest_profile,
)
from app.db.models import ChatSession, Turn
from app.db.session import get_session, get_sessionmaker
from app.schemas import (
    RecommendationSet,
    RecommendRequest,
    SessionCreate,
    SessionOut,
    SessionState,
    StudentProfile,
    TurnIn,
    TurnOut,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
log = get_logger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def get_retriever() -> RetrieverProtocol:
    """Retriever with the shared embedder. Imports are lazy and guarded: retrieval and
    the embedder land in parallel branches; until then this returns 503."""
    try:
        from app.retrieval.embedder import get_embedder  # type: ignore[import-not-found,unused-ignore]
        from app.retrieval.retriever import Retriever  # type: ignore[import-not-found,unused-ignore]
    except ImportError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "retriever unavailable") from exc
    retriever: RetrieverProtocol = Retriever(embedder=get_embedder())
    return retriever


def get_orchestrator(llm: LLMClient = Depends(get_llm_client)) -> CounselorOrchestrator:
    return CounselorOrchestrator(llm=llm, sessionmaker=get_sessionmaker())


def _session_out(row: ChatSession) -> SessionOut:
    return SessionOut(id=row.id, mode=row.mode, created_at=row.created_at)  # type: ignore[arg-type]


async def _require_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    try:
        return await get_chat_session(db, session_id)
    except SessionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found") from None


async def _check_session_exists(session_id: uuid.UUID) -> None:
    """Short-lived session: nothing is held open across an SSE stream or an Opus call."""
    async with get_sessionmaker()() as db:
        await _require_session(db, session_id)


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate | None = None, db: AsyncSession = Depends(get_session)
) -> SessionOut:
    row = ChatSession(mode=(body or SessionCreate()).mode)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _session_out(row)


@router.get("/{session_id}", response_model=SessionState)
async def get_session_state(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> SessionState:
    row = await _require_session(db, session_id)
    profile = await latest_profile(db, session_id)
    turns = (
        (await db.execute(select(Turn).where(Turn.session_id == session_id).order_by(Turn.idx)))
        .scalars()
        .all()
    )
    return SessionState(
        session=_session_out(row),
        profile=profile,
        turns=[
            TurnOut(idx=t.idx, role=t.role, text=t.text, interrupted=t.interrupted, at=t.at)  # type: ignore[arg-type]
            for t in turns
        ],
        ready=profile.is_ready(),
        missing=profile.missing_for_recommendation(),
    )


@router.post("/{session_id}/turns")
async def post_turn(
    session_id: uuid.UUID,
    body: TurnIn,
    orch: CounselorOrchestrator = Depends(get_orchestrator),
) -> StreamingResponse:
    await _check_session_exists(session_id)  # 404 before the stream starts

    async def events() -> AsyncIterator[str]:
        turn = orch.handle_turn(session_id, body.text, "chat")
        try:
            async for ev in turn:
                yield ev.sse()
        except Exception as exc:  # never break the SSE framing with a raw 500
            log.error("turn_failed", error=type(exc).__name__)
            yield TurnEvent("error", {"message": "Something went wrong. Please retry."}).sse()
        finally:
            await turn.aclose()  # client disconnect: close the model stream, save partial text

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/{session_id}/recommendations", response_model=RecommendationSet)
async def post_recommendations(
    session_id: uuid.UUID,
    body: RecommendRequest | None = None,
    orch: CounselorOrchestrator = Depends(get_orchestrator),
    retriever: RetrieverProtocol = Depends(get_retriever),
) -> RecommendationSet:
    req = body or RecommendRequest()
    try:
        result, _ = await orch.recommend(session_id, retriever, mode=req.mode, k=req.k)
    except SessionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found") from None
    except NotImplementedError as exc:  # e.g. a retrieval mode not built yet
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(exc) or "not implemented") from exc
    except NotReady as exc:
        detail: dict[str, Any] = {"message": "profile not ready", "missing": exc.missing}
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from None
    except LLMError as exc:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if exc.retryable else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(code, "recommendation model unavailable") from exc
    except ValueError as exc:  # invalid retrieval input (e.g. unknown state/region)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return result


@router.post(
    "/{session_id}/resume",
    response_model=StudentProfile,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def post_resume(session_id: uuid.UUID) -> StudentProfile:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "resume parsing not implemented yet")
