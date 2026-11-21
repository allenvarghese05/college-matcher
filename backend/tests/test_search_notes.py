"""Honest disclosure of a relaxed budget / too few matches, unit and end to end."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.llm import LLMClient
from app.counselor import search_notes
from app.counselor.recommender import build_user_message
from app.db.session import dispose_engine
from app.schemas import RecommendationSet, StudentProfile
from tests.counselor_fixtures import (
    FakeRetriever,
    ScriptedAnthropic,
    ScriptedParse,
    make_app,
    recommendation_output,
    run_api_scenario,
    scenario_profile,
    script_scenario,
    usage,
)

BELLA_TRACE: dict[str, Any] = {
    "relaxed": ["budget"],
    "filters": {
        "max_distance_miles": 250,
        "regions": None,
        "budget_cap": 2000,
        "budget_ceiling": 15000,
        "budget_source": "bracket_default",
        "cheapest_price": 6123,
    },
}


def test_summary_and_notices_for_relaxed_budget() -> None:
    s = search_notes.summarize(BELLA_TRACE, n_schools=4, k=10)
    assert s["relaxed"] == ["budget"] and s["too_few"] is True and s["n_schools"] == 4
    assert search_notes.needs_disclosure(s)
    budget, few = search_notes.notices(s)
    assert "$2,000 budget" in budget and "$15,000" in budget and "$6,123" in budget
    assert few.startswith("Only 4 schools match") and "250 miles" in few
    assert "didn't widen" in few


def test_notices_quiet_when_nothing_to_say() -> None:
    s = search_notes.summarize({"relaxed": [], "filters": {}}, n_schools=10, k=10)
    assert not search_notes.needs_disclosure(s) and search_notes.notices(s) == []
    zero = search_notes.notices(search_notes.summarize(None, n_schools=0, k=10))
    assert zero and zero[0].startswith("No school matched")
    one = search_notes.notices(search_notes.summarize(None, n_schools=1, k=10))
    assert one[0].startswith("Only 1 school matches")


def test_recommender_sees_search_notes_only_when_needed() -> None:
    p = StudentProfile()
    assert "<search_notes>" not in build_user_message(p, [], 10)
    s = search_notes.summarize(BELLA_TRACE, 4, 10)
    assert "<search_notes>" in build_user_message(p, [], 10, s)


@pytest.mark.usefixtures("requires_db")
async def test_fewer_than_k_end_to_end(tmp_path: Path) -> None:
    """2 candidate rows + a relaxed budget: the API returns < k schools, says why, and
    Opus is told; a repeat request (reused set) returns the same notices."""
    retriever = FakeRetriever(limit=2)
    retriever.last_trace = BELLA_TRACE  # type: ignore[attr-defined]
    thin = retriever.candidates(scenario_profile(), 40)
    fake = ScriptedAnthropic()
    script_scenario(fake)
    fake.add_parse(
        "json_schema",
        ScriptedParse(output=recommendation_output(thin, 10), usage=usage(5200, 900, 2100, 0)),
    )
    llm = LLMClient(mode="record", cassette_dir=tmp_path, anthropic_client=fake)
    app = make_app(llm, retriever)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        run = await run_api_scenario(c, k=10)
        again = await c.post(
            f"/api/sessions/{run.session_id}/recommendations",
            json={"mode": "hybrid_rerank", "k": 10},
        )
    await dispose_engine()

    body = RecommendationSet.model_validate(run.recommendations)
    n_schools = len({c.unitid for c in thin})
    assert 1 <= len(body.recommendations) <= n_schools < 10
    assert [r.rank for r in body.recommendations] == list(range(1, len(body.recommendations) + 1))
    assert body.groundedness == 1.0
    assert body.relaxed == ["budget"] and body.too_few is True
    assert any("$2,000" in n for n in body.notices)
    assert any(n.startswith(f"Only {n_schools} school") for n in body.notices)
    rec_calls = [kw for _, kw in fake.calls if "<candidates>" in json.dumps(kw, default=str)]
    assert rec_calls and "<search_notes>" in json.dumps(rec_calls[-1], default=str)
    assert again.status_code == 200 and again.json()["notices"] == body.notices
