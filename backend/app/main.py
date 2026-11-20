"""FastAPI app factory. Run: `uvicorn app.main:app --reload --port 8000` from backend/."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, sessions, voice
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine

log = get_logger(__name__)


def warm_embedder() -> None:
    """Load the embedding model and run one query so the first retrieval isn't ~3s
    slower. Runs in a worker thread; failures are logged, never raised."""
    from app.retrieval.embedder import get_embedder

    t0 = time.perf_counter()
    try:
        embedder = get_embedder()
        embedder.embed(["warm up"])
    except Exception as exc:
        log.warning("embedder_warmup_failed", error=type(exc).__name__)
        return
    ms = round((time.perf_counter() - t0) * 1000, 2)
    log.info("embedder_warm", model=embedder.model_name, ms=ms)


def should_warm_embedder() -> bool:
    return os.environ.get("EMBEDDER", "").lower() != "fake"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log.info("startup", llm_mode=get_settings().LLM_MODE)
    warmup: asyncio.Task[None] | None = None
    if should_warm_embedder():
        # background: startup (and the health check) doesn't wait for the model
        warmup = asyncio.create_task(asyncio.to_thread(warm_embedder))
    yield
    if warmup is not None and not warmup.done():
        warmup.cancel()  # the thread finishes on its own; we just stop awaiting it
    await dispose_engine()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title="College Matcher API", version="2.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(voice.router)
    # Feature routers (rest.py, voice_ws.py) are included here as they land.
    return app


app = create_app()
