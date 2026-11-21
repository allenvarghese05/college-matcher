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


def _trace(n_within: int = 0, **filters: Any) -> dict[str, Any]:
    f: dict[str, Any] = {
        "max_distance_miles": 250,
        "regions": None,
        "outside_home_state": False,
        "budget_cap": 2000,
        "budget_ceiling": 15000,
        "budget_source": "bracket_default",
        "n_within_cap": n_within,
    }
    f.update(filters)
    return {"relaxed": ["budget"], "filters": f}


BELLA_TRACE = _trace()


def _notes(trace: dict[str, Any] | None, n: int, prices: list[int] | None = None) -> list[str]:
    s = search_notes.summarize(trace, n_schools=n, k=10)
    if prices is not None:
        s = search_notes.with_shown_prices(s, prices)
    return search_notes.notices(s)


def test_relaxed_budget_nothing_within_cap() -> None:
    budget, few = _notes(BELLA_TRACE, 4, [6123, 9800, 14200])
    assert budget.startswith("No school we found has a net price within your $2,000 budget")
    assert "up to about $15,000" in budget and "app's usual stretch" in budget
    assert "from about $6,123 to $14,200" in budget  # prices of the schools shown
    # the too-few notice must not contradict the widened budget
    assert few.startswith("Only 4 schools match your other filters (within about 250 miles")
    assert "$15,000" not in few and "everything you asked" not in few
    assert "didn't widen your distance or regions" in few
    assert "))" not in budget + few


@pytest.mark.parametrize("n_within", [1, 2])
def test_relaxed_budget_some_within_cap(n_within: int) -> None:
    budget, _ = _notes(_trace(n_within), 5, [1900, 7000])
    noun = "1 school we found fits" if n_within == 1 else "2 schools we found fit"
    assert budget.startswith(f"Only {noun} within your $2,000 budget, so we added the closest")
    assert "No school" not in budget
    assert "from about $1,900 to $7,000" in budget


def test_prestige_relaxed_shows_cap_and_actual_range() -> None:
    t = _trace(1, budget_cap=10000, budget_ceiling=None, budget_source=None)
    (budget,) = _notes(t, 10, [9500, 61000])
    assert "within your $10,000 budget" in budget and "closest options we found" in budget
    assert "from about $9,500 to $61,000" in budget


def test_too_few_without_relaxation() -> None:
    # bracket default: the app's choice, stated separately, not as something asked for
    f = {"max_distance_miles": 150, "budget_ceiling": 12000, "budget_source": "bracket_default"}
    t = {"relaxed": [], "filters": f}
    (few,) = _notes(t, 1)
    assert few.startswith("Only 1 school matches everything you asked for (within about 150")
    assert "the app's default for your family's income range" in few
    assert "didn't widen your search" in few and "))" not in few
    # a stated cap is something the student asked for
    t2 = {"relaxed": [], "filters": {"budget_ceiling": 23000, "budget_source": "cap",
                                     "budget_cap": 20000}}  # fmt: skip
    (few2,) = _notes(t2, 3)
    assert "(a net price within your $20,000 budget)" in few2
    # leave-home + distance: home-state exclusion is mentioned
    t3 = {"relaxed": [], "filters": {"max_distance_miles": 2000, "outside_home_state": True}}
    (few3,) = _notes(t3, 2)
    assert "(within about 2,000 miles of home, outside your home state)" in few3


def test_notices_quiet_when_nothing_to_say() -> None:
    s = search_notes.summarize({"relaxed": [], "filters": {}}, n_schools=10, k=10)
    assert not search_notes.needs_disclosure(s) and search_notes.notices(s) == []
    zero = _notes(None, 0)
    assert zero and zero[0].startswith("No school matched everything you asked for.")


def test_recommender_sees_search_notes_only_when_needed() -> None:
    p = StudentProfile()
    assert "<search_notes>" not in build_user_message(p, [], 10)
    s = search_notes.summarize(BELLA_TRACE, 4, 10)
    assert "<search_notes>" in build_user_message(p, [], 10, s)


async def _run(retriever: FakeRetriever, fake: ScriptedAnthropic, tmp: Path) -> tuple[Any, Any]:
    llm = LLMClient(mode="record", cassette_dir=tmp, anthropic_client=fake)
    app = make_app(llm, retriever)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        run = await run_api_scenario(c, k=10)
        again = await c.post(
            f"/api/sessions/{run.session_id}/recommendations",
            json={"mode": "hybrid_rerank", "k": 10},
        )
    await dispose_engine()
    return run, again


@pytest.mark.usefixtures("requires_db")
async def test_fewer_than_k_end_to_end(tmp_path: Path) -> None:
    """2 candidate rows + a relaxed budget: the API returns < k schools, says why, quotes
    only prices on the list, and Opus is told; a reused set returns the same notices."""
    retriever = FakeRetriever(limit=2)
    retriever.last_trace = BELLA_TRACE  # type: ignore[attr-defined]
    thin = retriever.candidates(scenario_profile(), 40)
    fake = ScriptedAnthropic()
    script_scenario(fake)
    fake.add_parse(
        "json_schema",
        ScriptedParse(output=recommendation_output(thin, 10), usage=usage(5200, 900, 2100, 0)),
    )
    run, again = await _run(retriever, fake, tmp_path)

    body = RecommendationSet.model_validate(run.recommendations)
    n_schools = len({c.unitid for c in thin})
    assert 1 <= len(body.recommendations) <= n_schools < 10
    assert [r.rank for r in body.recommendations] == list(range(1, len(body.recommendations) + 1))
    assert body.groundedness == 1.0
    assert body.relaxed == ["budget"] and body.too_few is True
    budget, few = body.notices
    assert budget.startswith("No school we found has a net price within your $2,000 budget")
    shown = [int(c.facts["net_price"]) for c in thin  # type: ignore[arg-type]
             if c.unitid in {r.unitid for r in body.recommendations}]  # fmt: skip
    assert f"${min(shown):,}" in budget and f"${max(shown):,}" in budget
    assert few.startswith(f"Only {n_schools} school") and "other filters" in few
    rec_calls = [kw for _, kw in fake.calls if "<candidates>" in json.dumps(kw, default=str)]
    assert rec_calls and "<search_notes>" in json.dumps(rec_calls[-1], default=str)
    assert again.status_code == 200 and again.json()["notices"] == body.notices


class _EmptyRetriever(FakeRetriever):
    def candidates(self, profile: StudentProfile, k: int) -> list[Any]:
        return []


@pytest.mark.usefixtures("requires_db")
async def test_zero_results_end_to_end(tmp_path: Path) -> None:
    """Nothing matches: 200, no Opus call, groundedness 1.0, an honest notice, and the
    reused set says the same."""
    retriever = _EmptyRetriever()
    retriever.last_trace = {  # type: ignore[attr-defined]
        "relaxed": [],
        "filters": {"max_distance_miles": 10, "budget_cap": None, "budget_ceiling": 12000,
                    "budget_source": "bracket_default"},
    }  # fmt: skip
    fake = ScriptedAnthropic()
    script_scenario(fake)  # no recommender response queued: an Opus call would fail
    run, again = await _run(retriever, fake, tmp_path)

    body = RecommendationSet.model_validate(run.recommendations)
    assert body.recommendations == [] and body.groundedness == 1.0
    assert body.too_few is True and body.relaxed == []
    assert body.notices[0].startswith(
        "No school matched everything you asked for (within about 10 miles of home)."
    )
    assert not [kw for _, kw in fake.calls if "<candidates>" in json.dumps(kw, default=str)]
    assert again.status_code == 200 and again.json()["notices"] == body.notices
