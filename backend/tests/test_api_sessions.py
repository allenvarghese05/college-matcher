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
    assert retriever.loggers[0] is not None  # the turn logger is passed through
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
    rec_cassette, cas = _copy_cassettes(tmp_path)
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


def _copy_cassettes(tmp_path: Path) -> tuple[Path, dict]:  # type: ignore[type-arg]
    for f in CASSETTE_DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    rec_cassette = next(
        p
        for p in tmp_path.glob("parse-*.json")
        if json.loads(p.read_text())["request"]["model"] == "claude-opus-5-5"
    )
    return rec_cassette, json.loads(rec_cassette.read_text())


async def test_digit_reasons_are_dropped_and_counted(
    tmp_path: Path, retriever: FakeRetriever
) -> None:
    path, cas = _copy_cassettes(tmp_path)
    out = json.loads(cas["response"]["text"])
    out["recommendations"][0]["reasons"].append("Only 17% of applicants get in.")
    cas["response"]["text"] = json.dumps(out)
    path.write_text(json.dumps(cas))
    async for c in _client(tmp_path, retriever):
        run = await run_api_scenario(c)
    reasons = run.recommendations["recommendations"][0]["reasons"]
    assert reasons == out["recommendations"][0]["reasons"][:-1]
    async with get_sessionmaker()() as db:
        row = await db.get(RecommendationSetRow, uuid.UUID(run.recommendations["id"]))
        assert row is not None and row.retrieval_trace["reason_digit_violations"] == 1


class _RaisingRetriever(FakeRetriever):
    def __init__(self, exc: Exception):
        super().__init__()
        self.exc = exc

    async def retrieve(self, *a: object, **k: object) -> list:  # type: ignore[override,type-arg]
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "code"),
    [(NotImplementedError("mode not built"), 501), (ValueError("bad region"), 422)],
)
async def test_retriever_errors_map_to_http(exc: Exception, code: int) -> None:
    # reach readiness with the real scenario first, then swap in a failing retriever
    async for c in _client(CASSETTE_DIR, FakeRetriever()):
        run = await run_api_scenario(c)
    async for c in _client(CASSETTE_DIR, _RaisingRetriever(exc)):
        r = await c.post(f"/api/sessions/{run.session_id}/recommendations", json={"k": 3})
    assert r.status_code == code


async def test_recommendations_unknown_session_404(api: AsyncClient) -> None:
    r = await api.post(f"/api/sessions/{uuid.uuid4()}/recommendations", json={"k": 3})
    assert r.status_code == 404
