"""End-to-end through ASGI: replay cassettes (tests/cassettes) + FakeRetriever, no network."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.llm import LLMClient
from app.db.models import ClaimRow, RecommendationRow, RecommendationSetRow, TurnMetricRow
from app.db.session import dispose_engine, get_sessionmaker
from tests.counselor_fixtures import (
    CASSETTE_DIR,
    SCENARIO,
    SCENARIO_K,
    FakeRetriever,
    make_app,
    run_api_scenario,
)

pytestmark = pytest.mark.usefixtures("requires_db")


async def _client(cassette_dir: Path, retriever: FakeRetriever) -> AsyncIterator[AsyncClient]:
    llm = LLMClient(mode="replay", cassette_dir=cassette_dir)
    app = make_app(llm, retriever)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture
async def api(retriever: FakeRetriever) -> AsyncIterator[AsyncClient]:
    async for c in _client(CASSETTE_DIR, retriever):
        yield c


async def test_full_session_replay(api: AsyncClient, retriever: FakeRetriever) -> None:
    run = await run_api_scenario(api)

    # SSE: per turn tokens..., profile, ready, done
    for events in run.turn_events:
        names = [n for n, _ in events]
        assert names[-3:] == ["profile", "ready", "done"]
        assert set(names[:-3]) == {"token"} and len(names) > 3
    readiness = [next(d for n, d in ev if n == "ready") for ev in run.turn_events]
    assert [r["ready"] for r in readiness] == [False, False, True]
    assert readiness[0]["missing"] == ["home_state", "income_bracket"]
    assert readiness[1]["missing"] == ["income_bracket"]
    assert readiness[2]["missing"] == []
    first_reply = next(d for n, d in run.turn_events[0] if n == "done")["assistant_text"]
    assert first_reply == "".join(SCENARIO[0].reply_chunks)
    assert "If money weren't involved and you weren't getting paid" in first_reply

    # session state
    st = run.state
    assert st["ready"] is True and st["missing"] == []
    assert [(t["idx"], t["role"]) for t in st["turns"]] == [
        (0, "user"), (1, "assistant"), (2, "user"), (3, "assistant"), (4, "user"), (5, "assistant"),
    ]  # fmt: skip
    prof = st["profile"]
    assert prof["home_state"]["value"] == "OH"
    assert prof["income_bracket"]["value"] == "48-75k"
    assert prof["sat"]["value"] == 1310 and prof["gpa"]["value"] == 3.7
    assert prof["interests"]["value"] == ["coding", "building games"]

    # recommendations
    rs = run.recommendations
    assert rs["groundedness"] == 1.0
    assert rs["retrieval_mode"] == "hybrid_rerank"
    assert retriever.calls == [(40, "hybrid_rerank")]
    recs = rs["recommendations"]
    assert [r["rank"] for r in recs] == list(range(1, SCENARIO_K + 1))
    candidates = {c.unitid: c for c in retriever.candidates(_profile(st), 40)}
    for r in recs:
        cand = candidates[r["unitid"]]
        assert r["name"] == cand.name and r["city"] == cand.city and r["state"] == cand.state
        assert r["cip_title"] == cand.cip_title and r["admission_band"] == cand.admission_band
        assert r["claims"] and all(c["verified"] for c in r["claims"])
        assert not any(ch.isdigit() for reason in r["reasons"] for ch in reason)

    async with get_sessionmaker()() as db:
        set_row = await db.get(RecommendationSetRow, uuid.UUID(rs["id"]))
        assert set_row is not None and set_row.groundedness == 1.0
        assert len(set_row.retrieval_trace["candidates"]) == len(candidates)
        n_recs = (
            await db.execute(select(func.count()).where(RecommendationRow.set_id == set_row.id))
        ).scalar_one()
        n_claims = (
            await db.execute(
                select(func.count())
                .select_from(ClaimRow)
                .join(RecommendationRow)
                .where(RecommendationRow.set_id == set_row.id, ClaimRow.verified.is_(True))
            )
        ).scalar_one()
        stages = set(
            (
                await db.execute(
                    select(TurnMetricRow.stage).where(
                        TurnMetricRow.session_id == uuid.UUID(run.session_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert n_recs == SCENARIO_K
    assert n_claims == sum(len(r["claims"]) for r in recs)
    assert stages == {
        "extract", "reply_total", "reply_ttft", "retrieve", "recommend", "groundedness",
    }  # fmt: skip


def _profile(state: dict) -> object:  # type: ignore[type-arg]
    from app.schemas import StudentProfile

    return StudentProfile.model_validate(state["profile"])


async def test_injected_wrong_claim_is_unverified(tmp_path: Path, retriever: FakeRetriever) -> None:
    for f in CASSETTE_DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    rec_cassette = next(
        p
        for p in tmp_path.glob("parse-*.json")
        if json.loads(p.read_text())["request"]["model"] == "claude-opus-5-5"
    )
    cas = json.loads(rec_cassette.read_text())
    out = json.loads(cas["response"]["text"])
    target = out["recommendations"][0]["claims"][0]
    assert target["field"] == "net_price"
    true_value = target["value"]
    target["value"] = "$1,234"  # hallucinated price
    cas["response"]["text"] = json.dumps(out)
    rec_cassette.write_text(json.dumps(cas))

    async for c in _client(tmp_path, retriever):
        run = await run_api_scenario(c)
    rs = run.recommendations
    claims = [cl for r in rs["recommendations"] for cl in r["claims"]]
    bad = rs["recommendations"][0]["claims"][0]
    assert bad["verified"] is False
    assert bad["value"] == "$1,234" and bad["db_value"] == true_value
    assert rs["groundedness"] == pytest.approx((len(claims) - 1) / len(claims))
    assert all(cl["verified"] for cl in claims if cl is not bad)


async def test_turn_stream_headers_and_errors(api: AsyncClient) -> None:
    missing = uuid.uuid4()
    r = await api.post(f"/api/sessions/{missing}/turns", json={"text": "hi"})
    assert r.status_code == 404
    assert (await api.get(f"/api/sessions/{missing}")).status_code == 404

    sid = (await api.post("/api/sessions", json={})).json()["id"]
    r = await api.post(f"/api/sessions/{sid}/turns", json={"text": ""})
    assert r.status_code == 422

    # a message with no cassette: stream still opens, then reports an error event
    r = await api.post(f"/api/sessions/{sid}/turns", json={"text": "unrecorded message"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    assert r.text.startswith("event: error\ndata: ")


async def test_recommendations_require_ready_profile(api: AsyncClient) -> None:
    sid = (await api.post("/api/sessions", json={"mode": "text"})).json()["id"]
    r = await api.post(f"/api/sessions/{sid}/recommendations", json={"k": 5})
    assert r.status_code == 409
    assert r.json()["detail"]["missing"] == ["home_state", "income_bracket", "interests"]
    state = (await api.get(f"/api/sessions/{sid}")).json()
    assert state["ready"] is False and state["turns"] == []


async def test_resume_not_implemented(api: AsyncClient) -> None:
    sid = (await api.post("/api/sessions")).json()["id"]
    assert (await api.post(f"/api/sessions/{sid}/resume")).status_code == 501
