"""Embedder warm-up at startup and non-blocking query embedding (first-query latency)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import main
from app.retrieval.embedder import FakeEmbedder, set_embedder
from app.retrieval.major_match import by_vector


class _CountingEmbedder(FakeEmbedder):
    def __init__(self, delay_s: float = 0.0) -> None:
        super().__init__()
        self.delay_s = delay_s
        self.threads: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.threads.append(threading.current_thread().name)
        time.sleep(self.delay_s)  # blocking, like a real model call
        return super().embed(texts)


async def test_lifespan_warms_embedder_in_background_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMBEDDER", raising=False)
    emb = _CountingEmbedder(delay_s=0.3)
    set_embedder(emb)
    try:
        t0 = time.perf_counter()
        async with main.lifespan(main.create_app()):
            assert time.perf_counter() - t0 < 0.2, "startup waited for the warm-up"
            for _ in range(100):
                if emb.threads:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.35)
        assert len(emb.threads) == 1
        assert emb.threads[0] != threading.main_thread().name
    finally:
        set_embedder(None)


async def test_lifespan_skips_warmup_with_fake_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDER", "fake")
    called: list[bool] = []
    monkeypatch.setattr(main, "warm_embedder", lambda: called.append(True))
    async with main.lifespan(main.create_app()):
        await asyncio.sleep(0.05)
    assert called == []


def test_warm_embedder_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(FakeEmbedder):
        def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("model download failed")

    set_embedder(Broken())
    try:
        main.warm_embedder()
    finally:
        set_embedder(None)


@pytest.mark.usefixtures("requires_db")
async def test_query_embedding_does_not_block_event_loop(db_session: AsyncSession) -> None:
    emb = _CountingEmbedder(delay_s=0.3)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    t = asyncio.create_task(ticker())
    try:
        res = await by_vector(db_session, emb, "fixing cars and engines", 3)
    finally:
        t.cancel()
    assert res and emb.threads[0] != threading.main_thread().name
    assert ticks >= 5, f"event loop was blocked during embedding (ticks={ticks})"
