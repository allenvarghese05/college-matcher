"""One Opus call per session x profile snapshot x mode x k (React StrictMode guard)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.llm import LLMClient
from app.db.models import RecommendationSetRow
from app.db.session import dispose_engine, get_sessionmaker
from tests.counselor_fixtures import (
    CASSETTE_DIR,
    SCENARIO_K,
    FakeRetriever,
    ScriptedAnthropic,
    ScriptedParse,
    make_app,
    run_api_scenario,
    scenario_profile,
    script_recommendation,
)

pytestmark = pytest.mark.usefixtures("requires_db")


class _RaisingRetriever(FakeRetriever):
    async def retrieve(self, *a: object, **k: object) -> list:  # type: ignore[override,type-arg]
        raise ValueError("retrieved again")


async def _scenario() -> str:
    llm = LLMClient(mode="replay", cassette_dir=CASSETTE_DIR)
    app = make_app(llm, FakeRetriever())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        run = await run_api_scenario(c)
    await dispose_engine()
    return run.session_id


async def _post(llm: LLMClient, retriever: FakeRetriever, sid: str, k: int) -> list:  # type: ignore[type-arg]
    app = make_app(llm, retriever)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        url = f"/api/sessions/{sid}/recommendations"
        out = list(await asyncio.gather(c.post(url, json={"k": k}), c.post(url, json={"k": k})))
    await dispose_engine()
    return out


async def _n_sets(sid: str) -> int:
    async with get_sessionmaker()() as db:
        return int(
            (
                await db.execute(
                    select(func.count()).where(RecommendationSetRow.session_id == uuid.UUID(sid))
                )
            ).scalar_one()
        )


async def test_repeat_request_reuses_recent_set_without_retrieval_or_opus(tmp_path: Path) -> None:
    sid = await _scenario()
    # empty cassette dir + failing retriever: any retrieval or Opus call would error out
    llm = LLMClient(mode="replay", cassette_dir=tmp_path)
    app = make_app(llm, _RaisingRetriever())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post(f"/api/sessions/{sid}/recommendations", json={"k": SCENARIO_K})
        r2 = await c.post(f"/api/sessions/{sid}/recommendations", json={"k": SCENARIO_K})
    await dispose_engine()
    assert r1.status_code == 200, r1.text
    assert r1.json() == r2.json()
    assert r1.json()["groundedness"] == 1.0
    assert all(r["net_price_basis"] for r in r1.json()["recommendations"])
    assert await _n_sets(sid) == 1


async def test_different_k_is_a_new_request(tmp_path: Path) -> None:
    sid = await _scenario()
    llm = LLMClient(mode="replay", cassette_dir=tmp_path)
    app = make_app(llm, _RaisingRetriever())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/sessions/{sid}/recommendations", json={"k": SCENARIO_K + 1})
    await dispose_engine()
    assert r.status_code == 422 and "retrieved again" in r.text


async def test_recent_set_is_not_reused_after_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.counselor import orchestrator

    sid = await _scenario()
    monkeypatch.setattr(orchestrator, "RECENT_SET_WINDOW_S", 0.0)
    llm = LLMClient(mode="replay", cassette_dir=tmp_path)
    app = make_app(llm, _RaisingRetriever())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/sessions/{sid}/recommendations", json={"k": SCENARIO_K})
    await dispose_engine()
    assert r.status_code == 422 and "retrieved again" in r.text


async def test_concurrent_duplicates_share_one_opus_call(tmp_path: Path) -> None:
    sid = await _scenario()
    k = SCENARIO_K + 1  # not served from the scenario's recent set
    fake = ScriptedAnthropic()
    script_recommendation(fake, scenario_profile(), k)  # exactly ONE scripted Opus reply
    item = fake.queues["json_schema"][0]
    assert isinstance(item, ScriptedParse)
    item.delay_s = 0.3  # both requests arrive while the first is still in Opus
    llm = LLMClient(mode="live", cassette_dir=tmp_path, anthropic_client=fake)
    r1, r2 = await _post(llm, FakeRetriever(), sid, k)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r1.json() == r2.json()
    assert sum(1 for _, kw in fake.calls if kw["model"] == "claude-opus-5-5") == 1
    assert await _n_sets(sid) == 2  # the scenario's set + this one
