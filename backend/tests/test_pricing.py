"""The student net-price rule (app.retrieval.pricing) end to end.

Real Scorecard figures (2026-11 release, $48-75k bracket):

* UIUC (IL, public): NPT43_PUB $5,924, TUITIONFEE_IN $16,354, TUITIONFEE_OUT $36,706
  -> an Ohio student pays about $5,924 + $20,352 = $26,276 (est_out_of_state).
* Ohio State (OH, public): $9,708 -> in_state for an Ohio student.
* Case Western (OH, private): $24,534 -> private.

The DB-backed tests use UCLA from the committed 200-school fixture.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.counselor.facts import institution_facts, load_db_facts
from app.counselor.groundedness import FactIndex, check_claim
from app.db.models import Institution
from app.retrieval import sql_filters
from app.retrieval.pricing import student_net_price
from app.retrieval.retriever import Retriever, facts_for
from app.schemas import Claim, StudentProfile


def _row(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = dict(
        control=1,
        state="IL",
        net_price_0_30k=None,
        net_price_30_48k=None,
        net_price_48_75k=5924,
        net_price_75_110k=None,
        net_price_110k_plus=None,
        avg_net_price=12000,
        tuition_in_state=16354,
        tuition_out_of_state=36706,
    )
    base.update(kw)
    return SimpleNamespace(**base)


UIUC = _row()
OSU = _row(state="OH", net_price_48_75k=9708, tuition_in_state=13641, tuition_out_of_state=42423)
CWRU = _row(control=2, state="OH", net_price_48_75k=24534)
CWRU.tuition_in_state = CWRU.tuition_out_of_state = 69270


@pytest.mark.parametrize(
    ("row", "bracket", "home", "expected"),
    [
        (UIUC, "48-75k", "OH", (26276, "est_out_of_state")),  # the live bug: was $5,924
        (UIUC, "48-75k", "IL", (5924, "in_state")),
        (UIUC, "48-75k", "il", (5924, "in_state")),  # case-insensitive
        (UIUC, "48-75k", None, (5924, "in_state")),  # unknown home: published figure
        (OSU, "48-75k", "OH", (9708, "in_state")),
        (OSU, "48-75k", "IL", (9708 + 42423 - 13641, "est_out_of_state")),
        (CWRU, "48-75k", "OH", (24534, "private")),
        (CWRU, "48-75k", "TX", (24534, "private")),  # never a surcharge at privates
        (_row(control=3, state="AZ"), "48-75k", "OH", (5924, "private")),  # for-profit
        (_row(tuition_out_of_state=None), "48-75k", "OH", (None, "unknown")),
        (_row(tuition_in_state=None), "48-75k", "OH", (None, "unknown")),
        (_row(tuition_in_state=None), "48-75k", "IL", (5924, "in_state")),  # not needed
        (_row(net_price_48_75k=None), "48-75k", "IL", (None, "unknown")),
        (_row(tuition_out_of_state=16000), "48-75k", "OH", (5924, "est_out_of_state")),  # >= 0
        (UIUC, None, "OH", (12000 + 20352, "est_out_of_state")),  # no bracket: avg price
    ],
)
def test_student_net_price_table(row: Any, bracket: Any, home: Any, expected: Any) -> None:
    assert student_net_price(row, bracket, home) == expected


def test_avg_fallback_is_opt_in_and_follows_the_same_rule() -> None:
    row = _row(net_price_48_75k=None, avg_net_price=8000)
    assert student_net_price(row, "48-75k", "OH") == (None, "unknown")
    assert student_net_price(row, "48-75k", "OH", fallback_to_avg=True) == (
        8000 + 20352,
        "est_out_of_state",
    )
    assert student_net_price(row, "48-75k", "IL", fallback_to_avg=True) == (8000, "in_state")


def test_institution_facts_and_candidate_facts_agree() -> None:
    cols = {c.name for c in Institution.__table__.columns}
    inst = Institution(
        **{k: v for k, v in vars(UIUC).items() if k in cols}, unitid=145637, name="UIUC", city="X"
    )
    f = institution_facts(inst, "48-75k", "OH")
    assert (f["net_price"], f["net_price_basis"]) == (26276, "est_out_of_state")
    assert institution_facts(inst, "48-75k", "IL")["net_price"] == 5924


# ------------------------------------------------------------------ DB-backed

UCLA = 110662  # CA public: $48-75k net price 10,769; tuition in 15,729 / out 53,331
UCLA_OOS = 10769 + 53331 - 15729  # 48,371


def _prof(**fields: Any) -> StudentProfile:
    return StudentProfile.model_validate(
        {k: {"value": v, "confidence": 1.0} for k, v in fields.items()}
    )


OHIO = dict(home_state="OH", income_bracket="48-75k", regions=["CA"])
CALI = dict(home_state="CA", income_bracket="48-75k", regions=["CA"])


@pytest.mark.usefixtures("requires_db")
async def test_retrieval_shows_out_of_state_price(db_session: AsyncSession) -> None:
    # no cap: the 48-75k default ceiling ($20,000) applies to the out-of-state price
    no_cap = await sql_filters.candidates(db_session, _prof(**OHIO), None)
    assert UCLA not in {r.unitid for r in no_cap}
    roomy = 60000  # a cap high enough to keep UCLA for an OH student
    rows = await sql_filters.candidates(db_session, _prof(**OHIO, budget_cap=roomy), None)
    ucla = next(r for r in rows if r.unitid == UCLA)
    assert ucla.net_price_48_75k == 10769  # the published (in-state) figure
    f = facts_for(ucla, "48-75k", "OH")
    assert (f["net_price"], f["net_price_basis"]) == (UCLA_OOS, "est_out_of_state")
    assert facts_for(ucla, "48-75k", "CA")["net_price"] == 10769

    cands = await Retriever().retrieve(
        db_session, _prof(**OHIO, budget_cap=roomy), k=250, mode="sql_only"
    )
    c = next(c for c in cands if c.unitid == UCLA)
    assert c.facts["net_price"] == UCLA_OOS and c.facts["net_price_basis"] == "est_out_of_state"
    cands = await Retriever().retrieve(db_session, _prof(**CALI), k=250, mode="sql_only")
    c = next(c for c in cands if c.unitid == UCLA)
    assert c.facts["net_price"] == 10769 and c.facts["net_price_basis"] == "in_state"


@pytest.mark.usefixtures("requires_db")
async def test_budget_filter_uses_out_of_state_price(db_session: AsyncSession) -> None:
    cap = 20000  # in-state 10,769 fits; out-of-state 48,371 does not
    oh = await sql_filters.candidates(db_session, _prof(**OHIO, budget_cap=cap), None)
    ca = await sql_filters.candidates(db_session, _prof(**CALI, budget_cap=cap), None)
    assert UCLA not in {r.unitid for r in oh}
    assert UCLA in {r.unitid for r in ca}


@pytest.mark.usefixtures("requires_db")
async def test_groundedness_checks_against_out_of_state_price(db_session: AsyncSession) -> None:
    db = await load_db_facts(db_session, [(UCLA, None)], "48-75k", "OH")
    assert db[(UCLA, None)]["net_price"] == UCLA_OOS
    assert db[(UCLA, None)]["net_price_basis"] == "est_out_of_state"
    idx = FactIndex()
    idx.add(UCLA, None, db[(UCLA, None)])

    def claim(value: str) -> Claim:
        return Claim(unitid=UCLA, field="net_price", value=value)

    ok = check_claim(claim("$48,371"), idx)
    assert ok.verified and ok.db_value == "$48,371"
    stale = check_claim(claim("$10,769"), idx)  # the in-state figure is now wrong
    assert not stale.verified and stale.db_value == "$48,371"
