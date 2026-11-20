"""Load claimable facts straight from Postgres for the groundedness checker.

Fact formats (same convention expected from the retriever's ``Candidate.facts``):
money/count as int, rates as a 0..1 float, ranges as "lo-hi", ``city_state`` "City, ST".

``net_price`` is computed with the same rule the retriever uses
(``app.retrieval.pricing.student_net_price``), so a claim is checked against the exact
value the student is shown (e.g. the out-of-state estimate at a public school in
another state); ``net_price_basis`` says which rule applied.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Institution, Program
from app.retrieval.pricing import student_net_price

BACHELORS = 3


def _range(lo: int | None, hi: int | None) -> str | None:
    return f"{lo}-{hi}" if lo is not None and hi is not None else None


def institution_facts(
    inst: Institution, income_bracket: str | None, home_state: str | None = None
) -> dict[str, Any]:
    net_price, basis = student_net_price(inst, income_bracket, home_state)
    return {
        "net_price": net_price,
        "net_price_basis": basis,
        "admission_rate": inst.admission_rate,
        "sat_range": _range(inst.sat_25, inst.sat_75),
        "act_range": _range(inst.act_25, inst.act_75),
        "completion_rate": inst.completion_rate,
        "median_earnings_10yr": inst.median_earnings_10yr,
        "median_debt": inst.median_debt,
        "undergrad_size": inst.undergrad_size,
        "city_state": f"{inst.city}, {inst.state}",
    }


async def load_db_facts(
    db: AsyncSession,
    keys: Iterable[tuple[int, str | None]],
    income_bracket: str | None,
    home_state: str | None = None,
) -> dict[tuple[int, str | None], dict[str, Any]]:
    keys = set(keys)
    unitids = {u for u, _ in keys}
    if not unitids:
        return {}
    insts = {
        i.unitid: i
        for i in (await db.execute(select(Institution).where(Institution.unitid.in_(unitids))))
        .scalars()
        .all()
    }
    progs = {
        (p.unitid, p.cip4): p
        for p in (
            await db.execute(
                select(Program).where(
                    Program.unitid.in_(unitids), Program.credential_level == BACHELORS
                )
            )
        )
        .scalars()
        .all()
    }
    out: dict[tuple[int, str | None], dict[str, Any]] = {}
    for unitid, cip4 in keys:
        inst = insts.get(unitid)
        if inst is None:
            continue
        facts = institution_facts(inst, income_bracket, home_state)
        prog = progs.get((unitid, cip4)) if cip4 else None
        if prog is not None:
            facts["program_median_earnings"] = prog.median_earnings
            facts["program_median_debt"] = prog.median_debt
        out[(unitid, cip4)] = facts
    return out
