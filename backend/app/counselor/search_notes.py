"""What the search could not do, said plainly to the student (SPEC §9 "Relaxation policy").

The retriever never widens the student's stated distance or regions. It may take ONE
relaxation step (a stated budget cap → the bracket default) and may return fewer
schools than asked for. :func:`summarize` turns its trace into a small dict that goes
to the recommender (so its reasons never claim a school "fits your budget" when it
doesn't) and is persisted with the set; :func:`notices` renders the student-facing
sentences deterministically from DB-derived numbers, so no LLM text carries them.
"""

from __future__ import annotations

from typing import Any


def summarize(trace: dict[str, Any] | None, n_schools: int, k: int) -> dict[str, Any]:
    """``{relaxed, too_few, n_schools, k, filters}`` from a retriever ``last_trace``."""
    trace = trace or {}
    return {
        "relaxed": list(trace.get("relaxed") or []),
        "too_few": n_schools < k,
        "n_schools": n_schools,
        "k": k,
        "filters": dict(trace.get("filters") or {}),
    }


def needs_disclosure(summary: dict[str, Any]) -> bool:
    return bool(summary.get("relaxed")) or bool(summary.get("too_few"))


def _money(v: float | int) -> str:
    return f"${round(v):,}"


def _constraints(filters: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if filters.get("max_distance_miles"):
        out.append(f"within about {round(filters['max_distance_miles']):,} miles of home")
    if filters.get("regions"):
        out.append("in the places you named")
    if filters.get("budget_ceiling") is not None:
        price = f"a net price up to about {_money(filters['budget_ceiling'])} a year"
        if filters.get("budget_source") == "bracket_default":
            price += " (a typical stretch for your family's income range)"
        out.append(price)
    return out


def notices(summary: dict[str, Any]) -> list[str]:
    """Student-facing sentences (empty when nothing needs saying)."""
    out: list[str] = []
    f = summary.get("filters") or {}
    if "budget" in (summary.get("relaxed") or []):
        cap = f.get("budget_cap")
        ceiling = f.get("budget_ceiling")
        msg = (
            f"No school we found has a net price within your {_money(cap)} budget."
            if cap is not None
            else "No school we found fits your budget."
        )
        if ceiling is not None:
            msg += (
                f" These are the closest realistic options, up to about {_money(ceiling)} a "
                "year, which is a typical stretch for your family's income range"
            )
            cheapest = f.get("cheapest_price")
            msg += f"; the lowest is about {_money(cheapest)}." if cheapest is not None else "."
        else:
            msg += " These are the closest realistic options we could find."
        out.append(msg)
    if summary.get("too_few"):
        n = int(summary.get("n_schools") or 0)
        what = ", ".join(_constraints(f)) or "everything you told us"
        if n == 0:
            msg = f"No school matched everything you asked for ({what})."
        else:
            schools = "school matches" if n == 1 else "schools match"
            msg = f"Only {n} {schools} everything you asked for ({what})."
        msg += (
            " We didn't widen your search on our own. If you'd consider going farther, "
            "a higher budget or other majors, tell the counselor and we'll look again."
        )
        out.append(msg)
    return out
