"""What the search could not do, said plainly to the student (SPEC §9 "Relaxation policy").

The retriever never widens the student's stated distance or regions. It may take ONE
relaxation step (a stated budget cap → the bracket default, when fewer than three
schools fit the cap; 0-2 may still fit, ``filters["n_within_cap"]``) and may return
fewer schools than asked for. :func:`summarize` turns its trace into a small dict that
goes to the recommender (so its reasons never claim a school "fits your budget" when it
doesn't) and is persisted with the set. After the recommendations are chosen,
:func:`with_shown_prices` adds the price range of the schools actually shown, and
:func:`notices` renders the student-facing sentences deterministically from those
DB-derived numbers, so no LLM text carries them and every quoted price is on the list.
"""

from __future__ import annotations

from collections.abc import Iterable
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


def with_shown_prices(
    summary: dict[str, Any], prices: Iterable[int | float | str | None]
) -> dict[str, Any]:
    """Add ``shown_prices: {min, max}`` over the recommendations' displayed net prices
    (``facts["net_price"]``, i.e. ``pricing.student_net_price``: the filter's rule
    minus the average-price fallback, so a school with no displayable price is skipped)."""
    ps = [p for p in prices if isinstance(p, int | float)]
    out = dict(summary)
    out["shown_prices"] = {"min": min(ps), "max": max(ps)} if ps else None
    return out


def needs_disclosure(summary: dict[str, Any]) -> bool:
    return bool(summary.get("relaxed")) or bool(summary.get("too_few"))


def _money(v: float | int) -> str:
    return f"${round(v):,}"


def _schools(n: int) -> str:
    return "1 school" if n == 1 else f"{n} schools"


def _location(filters: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if filters.get("max_distance_miles"):
        out.append(f"within about {round(filters['max_distance_miles']):,} miles of home")
    if filters.get("outside_home_state"):
        out.append("outside your home state")
    elif filters.get("regions"):
        out.append("in the places you named")
    return out


def _price_range(summary: dict[str, Any]) -> str:
    shown = summary.get("shown_prices")
    if not shown:
        return ""
    lo, hi = shown["min"], shown["max"]
    if round(lo) == round(hi):
        return f" The one shown here has a net price of about {_money(lo)} a year."
    return f" The ones shown here have net prices from about {_money(lo)} to {_money(hi)} a year."


def _budget_notice(summary: dict[str, Any]) -> str:
    f = summary.get("filters") or {}
    cap, ceiling = f.get("budget_cap"), f.get("budget_ceiling")
    n_within = int(f.get("n_within_cap") or 0)
    budget = f"your {_money(cap)} budget" if cap is not None else "your budget"
    if n_within > 0:
        verb = "fits" if n_within == 1 else "fit"
        msg = f"Only {_schools(n_within)} we found {verb} within {budget}, so we added"
    else:
        msg = f"No school we found has a net price within {budget}, so these are"
    if ceiling is not None:
        msg += (
            f" the closest realistic options, up to about {_money(ceiling)} a year (the app's "
            "usual stretch for your family's income range)."
        )
    else:
        msg += " the closest options we found."
    return msg + _price_range(summary)


def _too_few_notice(summary: dict[str, Any]) -> str:
    f = summary.get("filters") or {}
    n = int(summary.get("n_schools") or 0)
    where = _location(f)
    budget_relaxed = "budget" in (summary.get("relaxed") or [])
    if budget_relaxed:
        # the budget was already widened (see the budget notice): only location is "kept"
        scope = "your other filters"
    else:
        scope = "everything you asked for"
        cap = f.get("budget_cap")
        if f.get("budget_source") == "cap" and cap is not None:
            where = [*where, f"a net price within your {_money(cap)} budget"]
    detail = f" ({', '.join(where)})" if where else ""
    if n == 0:
        msg = f"No school matched {scope}{detail}."
    else:
        verb = "matches" if n == 1 else "match"
        msg = f"Only {_schools(n)} {verb} {scope}{detail}."
    if not budget_relaxed and f.get("budget_source") == "bracket_default":
        msg += (
            f" We also kept to net prices up to about {_money(f['budget_ceiling'])} a year, "
            "the app's default for your family's income range, since you didn't give a budget."
        )
    if budget_relaxed:
        msg += " We didn't widen your distance or regions."
    else:
        msg += " We didn't widen your search on our own."
    msg += (
        " If you'd consider going farther, a different budget or other majors, tell the "
        "counselor and we'll look again."
    )
    return msg


def notices(summary: dict[str, Any]) -> list[str]:
    """Student-facing sentences (empty when nothing needs saying)."""
    out: list[str] = []
    if "budget" in (summary.get("relaxed") or []):
        out.append(_budget_notice(summary))
    if summary.get("too_few"):
        out.append(_too_few_notice(summary))
    return out
